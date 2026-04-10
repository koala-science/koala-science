"""
Reproducibility Runner — uses OpenHands to clone repos, run code,
and produce evidence-based reproducibility reviews.

OpenHands is an AI coding agent that reasons about what to do:
reads the README, figures out install steps, adapts when things fail,
runs tests, and reports results. This is not a bash script.

Requirements:
    - Python 3.12+ (OpenHands requirement)
    - Docker running (OpenHands sandbox)
    - pip install openhands-ai (in a Python 3.12 venv)

Usage:
    from repro_runner import ReproRunner
    runner = ReproRunner(llm_api_key="...", llm="gemini")
    review = runner.generate_review(system_prompt, title, abstract,
                                     github_url="https://github.com/...")

If the paper has no GitHub repo, falls back to checklist-based review
using the LLM directly.
"""

import json
import os
import textwrap


# --- OpenHands integration ---

REPRO_TASK_TEMPLATE = """\
You are assessing the reproducibility of a scientific paper.

Paper: {title}
Repository: {github_url}

Your task:
1. Clone the repository
2. Read the README and understand the project structure
3. Identify the main dependencies and install them
4. Find and run the test suite (if any)
5. Identify the main experiment scripts
6. Try to run a minimal experiment or demo (if documented)
7. Check for common reproducibility issues:
   - Hardcoded paths
   - Missing data files
   - Undocumented GPU/hardware requirements
   - Missing environment specs
   - Pinned vs unpinned dependencies

After your investigation, write a final summary in this exact format:

---REPRODUCIBILITY_REPORT---
## Environment Setup
[What you found about setting up the environment]

## Code Structure
[How the repo is organized, entry points, test suite]

## Execution Results
[What happened when you tried to run things]

## Issues Found
[Specific reproducibility problems you encountered]

## Verdict
[FULLY_REPRODUCIBLE / PARTIALLY_REPRODUCIBLE / NOT_REPRODUCIBLE / CANNOT_ASSESS]
[One paragraph justification]
---END_REPORT---
"""


def run_openhands_task(
    task: str,
    llm_model: str = "gemini/gemini-2.5-flash",
    llm_api_key: str | None = None,
    max_iterations: int = 30,
    timeout: int = 600,
    python_bin: str | None = None,
) -> str:
    """
    Run a task through OpenHands headless mode.
    Returns the agent's trajectory as text.

    Uses a subprocess with the correct Python 3.12+ interpreter
    since OpenHands requires it.
    """
    python = python_bin or _find_openhands_python()
    if not python:
        raise RuntimeError(
            "Cannot find Python 3.12+ with openhands installed. "
            "Install with: uv venv /tmp/openhands-env --python 3.12 && "
            "source /tmp/openhands-env/bin/activate && pip install openhands-ai"
        )

    # Write the task runner script
    runner_script = textwrap.dedent(f"""\
        import asyncio
        import json
        import sys
        import os

        os.environ.setdefault("LLM_MODEL", {json.dumps(llm_model)})
        os.environ.setdefault("LLM_API_KEY", {json.dumps(llm_api_key or "")})

        from openhands.core.main import run_controller
        from openhands.core.config import OpenHandsConfig
        from openhands.core.config.llm_config import LLMConfig
        from openhands.events.action import MessageAction

        config = OpenHandsConfig()
        config.default_agent = "CodeActAgent"
        config.max_iterations = {max_iterations}
        config.llms["llm"] = LLMConfig(
            model={json.dumps(llm_model)},
            api_key={json.dumps(llm_api_key or os.environ.get("GOOGLE_API_KEY", ""))},
        )
        config.runtime = "docker"
        config.sandbox.timeout = {timeout}
        config.sandbox.use_host_network = False

        task = {json.dumps(task)}
        action = MessageAction(content=task)

        async def main():
            state = await run_controller(
                config=config,
                initial_user_action=action,
                headless_mode=True,
            )
            if state and hasattr(state, 'history'):
                # Extract agent messages from trajectory
                messages = []
                for event in state.history:
                    if hasattr(event, 'content') and event.content:
                        messages.append(event.content)
                    elif hasattr(event, 'message') and event.message:
                        messages.append(event.message)
                print("---TRAJECTORY_START---")
                print("\\n---EVENT---\\n".join(messages[-20:]))  # last 20 events
                print("---TRAJECTORY_END---")
            else:
                print("---TRAJECTORY_START---")
                print("Agent completed but no trajectory available")
                print("---TRAJECTORY_END---")

        asyncio.run(main())
    """)

    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(runner_script)
        script_path = f.name

    try:
        result = subprocess.run(
            [python, script_path],
            capture_output=True,
            text=True,
            timeout=timeout + 60,  # extra buffer
            env={
                **os.environ,
                "LLM_API_KEY": llm_api_key or os.environ.get("GOOGLE_API_KEY", ""),
            },
        )

        output = result.stdout + result.stderr

        # Extract trajectory
        if "---TRAJECTORY_START---" in output:
            start = output.index("---TRAJECTORY_START---") + len(
                "---TRAJECTORY_START---"
            )
            end = (
                output.index("---TRAJECTORY_END---")
                if "---TRAJECTORY_END---" in output
                else len(output)
            )
            return output[start:end].strip()
        else:
            return output[-5000:]  # last 5KB of output

    except subprocess.TimeoutExpired:
        return f"OpenHands timed out after {timeout}s"
    finally:
        os.unlink(script_path)


def _find_openhands_python() -> str | None:
    """Find a Python 3.12+ interpreter with openhands installed."""
    candidates = [
        "/tmp/openhands-env/bin/python",
        os.path.expanduser("~/.openhands-env/bin/python"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            import subprocess

            try:
                result = subprocess.run(
                    [candidate, "-c", "import openhands; print('ok')"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and "ok" in result.stdout:
                    return candidate
            except Exception:
                pass
    return None


# --- LLM analysis of execution results ---

REVIEW_SYNTHESIS_PROMPT = """\
You are a reproducibility reviewer on the Coalescence scientific peer review platform.

{system_prompt}

A coding agent (OpenHands) attempted to reproduce the code for this paper.
Analyze the execution trajectory below and write a structured reproducibility review.

Paper: {title}
Abstract: {abstract}
GitHub: {github_url}

--- Agent Execution Trajectory ---
{trajectory}
--- End Trajectory ---

Write your review in markdown. Include:
## Reproducibility Assessment
### Environment Setup
### Code Execution
### Issues Found
### Verdict
Rate: **Fully Reproducible** / **Partially Reproducible** / **Not Reproducible** / **Cannot Assess**

Be specific. Cite exact errors, file names, and commands from the trajectory.
"""

CHECKLIST_PROMPT = """\
{system_prompt}

This paper has no GitHub repository available.

Paper: {title}
Abstract: {abstract}

Write a reproducibility checklist review based only on the abstract:

## Reproducibility Checklist
- [ ] Code publicly available
- [ ] Dataset described or available
- [ ] Hyperparameters specified
- [ ] Baselines identified
- [ ] Compute requirements stated
- [ ] Random seeds / variance reported

## Verdict
**Cannot Assess (No Code Available)**
[What would be needed to reproduce the main results]
"""


class ReproRunner:
    """
    Reproducibility runner powered by OpenHands.

    For papers with GitHub repos: launches OpenHands to clone, install,
    and run the code, then synthesizes a review from the execution results.

    For papers without repos: produces a checklist-based assessment.
    """

    def __init__(
        self,
        llm_api_key: str | None = None,
        llm: str = "gemini",
        openhands_python: str | None = None,
        max_iterations: int = 30,
        sandbox_timeout: int = 600,
    ):
        self.llm = llm
        self.llm_api_key = llm_api_key or os.environ.get("GOOGLE_API_KEY", "")
        self.openhands_python = openhands_python or _find_openhands_python()
        self.max_iterations = max_iterations
        self.sandbox_timeout = sandbox_timeout

        # LLM client for review synthesis
        if llm == "gemini":
            from google import genai

            self.genai_client = genai.Client(api_key=self.llm_api_key)
        elif llm == "claude":
            from anthropic import Anthropic

            self.anthropic_client = Anthropic(
                api_key=llm_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
            )

    def _call_llm(self, prompt: str) -> str:
        if self.llm == "gemini":
            resp = self.genai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            return resp.text
        elif self.llm == "claude":
            resp = self.anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text

    def generate_review(
        self,
        system_prompt: str,
        paper_title: str,
        paper_abstract: str,
        github_url: str | None = None,
        pdf_url: str | None = None,
    ) -> str:
        if github_url and self.openhands_python:
            return self._review_with_openhands(
                system_prompt, paper_title, paper_abstract, github_url
            )
        elif github_url:
            # OpenHands not available, note it in the review
            review = self._review_checklist(system_prompt, paper_title, paper_abstract)
            return (
                review
                + "\n\n*Note: OpenHands sandbox unavailable. Checklist-only review.*"
            )
        else:
            return self._review_checklist(system_prompt, paper_title, paper_abstract)

    def _review_with_openhands(
        self, system_prompt: str, title: str, abstract: str, github_url: str
    ) -> str:
        print(f"    [repro] launching OpenHands for {github_url}...")

        task = REPRO_TASK_TEMPLATE.format(title=title, github_url=github_url)

        llm_model = (
            "gemini/gemini-2.5-flash"
            if self.llm == "gemini"
            else "anthropic/claude-sonnet-4-20250514"
        )

        trajectory = run_openhands_task(
            task=task,
            llm_model=llm_model,
            llm_api_key=self.llm_api_key,
            max_iterations=self.max_iterations,
            timeout=self.sandbox_timeout,
            python_bin=self.openhands_python,
        )

        print("    [repro] OpenHands done. Synthesizing review...")

        # Use LLM to synthesize the trajectory into a review
        prompt = REVIEW_SYNTHESIS_PROMPT.format(
            system_prompt=system_prompt,
            title=title,
            abstract=abstract,
            github_url=github_url,
            trajectory=trajectory[-8000:],  # last 8KB
        )

        return self._call_llm(prompt)

    def _review_checklist(self, system_prompt: str, title: str, abstract: str) -> str:
        prompt = CHECKLIST_PROMPT.format(
            system_prompt=system_prompt,
            title=title,
            abstract=abstract,
        )
        return self._call_llm(prompt)
