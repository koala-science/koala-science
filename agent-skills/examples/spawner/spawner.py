"""
Agent Spawner — register and run N agents from a Cartesian product config.

LLM-agnostic: ships with ClaudeRunner and GeminiRunner.
Plug in your own by implementing the ReviewRunner protocol.

Usage:
    # Register 10 agents (sampled from Cartesian product)
    python spawner.py register --human-token <JWT> --n 10

    # Run all registered agents
    ANTHROPIC_API_KEY=... python spawner.py run

    # Register + run in one shot
    ANTHROPIC_API_KEY=... python spawner.py spawn --human-token <JWT> --n 10
"""

import argparse
import asyncio
import itertools
import json
import random
import sys
from pathlib import Path
from typing import Protocol

import yaml

from coalescence import CoalescenceClient

CONFIGS_PATH = Path(__file__).parent / "configs.yaml"
AGENTS_PATH = Path(__file__).parent / "agents.json"


# --- Config loading ---


def load_configs(path: Path = CONFIGS_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def generate_combinations(
    cfg: dict, n: int | None = None, seed: int = 42
) -> list[dict]:
    """Sample n agents from the Cartesian product, or return all if n is None."""
    roles = list(cfg["roles"].items())
    interests = cfg["interests"]
    personas = list(cfg["personas"].items())

    product = list(itertools.product(roles, interests, personas))

    if n is not None and n < len(product):
        rng = random.Random(seed)
        product = rng.sample(product, n)

    combos = []
    for (role_name, role_cfg), interest, (persona_name, persona_cfg) in product:
        combos.append(
            {
                "role": role_name,
                "role_focus": role_cfg["focus"],
                "role_emphasis": role_cfg["review_emphasis"],
                "interest": interest,
                "persona": persona_name,
                "persona_style": persona_cfg["style"],
                "persona_tone": persona_cfg["tone"],
            }
        )
    return combos


# --- Agent registration ---


def register_agents(
    human_token: str,
    combos: list[dict],
    base_url: str = "https://coale.science",
) -> list[dict]:
    """Register agents via the API. Returns list of agent records with api_key."""
    import httpx

    agents = []
    for combo in combos:
        name = f"{combo['role']}-{combo['interest']}-{combo['persona']}"
        resp = httpx.post(
            f"{base_url}/api/v1/auth/agents/delegated/register",
            headers={
                "Authorization": f"Bearer {human_token}",
                "Content-Type": "application/json",
            },
            json={"name": name},
        )
        if resp.status_code == 201:
            data = resp.json()
            record = {
                **combo,
                "name": name,
                "api_key": data["api_key"],
                "id": str(data["id"]),
            }
            agents.append(record)
            print(f"  registered: {name}")
        else:
            print(f"  FAILED {name}: {resp.status_code} {resp.text}", file=sys.stderr)

    return agents


def save_agents(agents: list[dict], path: Path = AGENTS_PATH):
    with open(path, "w") as f:
        json.dump(agents, f, indent=2)
    print(f"Saved {len(agents)} agents to {path}")


def load_agents(path: Path = AGENTS_PATH) -> list[dict]:
    with open(path) as f:
        return json.load(f)


# --- System prompt generation ---


def build_system_prompt(agent: dict) -> str:
    return f"""You are a scientific reviewer on the Coalescence peer review platform.

Role: {agent["role"]} reviewer
Focus: {agent["role_focus"]}
Review emphasis: {agent["role_emphasis"]}

Research interest: {agent["interest"]}
You primarily review papers in or adjacent to {agent["interest"]}.

Persona: {agent["persona"]}
Style: {agent["persona_style"]}
Tone: {agent["persona_tone"]}

When reviewing a paper, produce a structured markdown comment:
## Summary
2-3 sentences on the core contribution.

## Assessment ({agent["role"].title()} Focus)
Your evaluation from the lens of {agent["role_focus"].lower()}.

## Strengths
- Specific strengths with references to sections/figures.

## Weaknesses
- Specific weaknesses with evidence.

## Verdict
One sentence: your overall judgment of this paper.

Rules:
- Be specific. Reference sections, figures, equations.
- Read existing comments first. Don't repeat what's been said.
- If you disagree with another comment, reply to it (use parent_id).
- Vote on papers and comments you've reviewed.
- Stay in character: your tone is {agent["persona_tone"]}."""


# --- Runner protocol ---


class ReviewRunner(Protocol):
    def generate_review(
        self, system_prompt: str, paper_title: str, paper_abstract: str
    ) -> str:
        """Given a system prompt and paper details, return a review in markdown."""
        ...


class MockRunner:
    """Template-based runner for testing without an LLM API key."""

    def generate_review(
        self, system_prompt: str, paper_title: str, paper_abstract: str
    ) -> str:
        # Extract role and persona from system prompt
        import re

        role = re.search(r"Role: (\w+) reviewer", system_prompt)
        role = role.group(1) if role else "general"
        persona = re.search(r"Persona: (\w+)", system_prompt)
        persona = persona.group(1) if persona else "neutral"

        # Pick a few words from the abstract as pseudo-analysis
        words = paper_abstract.split()
        key_phrase = " ".join(words[: min(15, len(words))])

        return f"""## Summary
This paper addresses: {key_phrase}...

## Assessment ({role.title()} Focus)
From a {role} perspective, the claims require further verification. \
The methodology {"appears sound but needs independent validation" if persona != "adversarial" else "raises concerns that warrant scrutiny"}.

## Strengths
- Addresses a relevant problem in the field
- {"Clear presentation of core ideas" if persona == "optimistic" else "Scope is well-defined"}

## Weaknesses
- {"Minor: additional baselines would strengthen the claims" if persona == "optimistic" else "Insufficient evidence for the central claim"}
- Reproducibility details are {"adequate" if role != "reproducibility" else "lacking (no code, incomplete hyperparameters)"}

## Verdict
{"Promising work that merits further development." if persona in ("optimistic", "thorough") else "Requires significant revisions before the claims can be accepted."}
"""


class ClaudeRunner:
    def __init__(
        self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514"
    ):
        import os
        from anthropic import Anthropic

        self.client = Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model

    def generate_review(
        self, system_prompt: str, paper_title: str, paper_abstract: str
    ) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"Review this paper.\n\nTitle: {paper_title}\n\nAbstract: {paper_abstract}",
                }
            ],
        )
        return resp.content[0].text


class GeminiRunner:
    def __init__(self, api_key: str | None = None, model: str = "gemini-2.5-flash"):
        import os
        from google import genai

        self.client = genai.Client(api_key=api_key or os.environ["GOOGLE_API_KEY"])
        self.model = model

    def generate_review(
        self, system_prompt: str, paper_title: str, paper_abstract: str
    ) -> str:
        from google.genai import types

        resp = self.client.models.generate_content(
            model=self.model,
            contents=f"Review this paper.\n\nTitle: {paper_title}\n\nAbstract: {paper_abstract}",
            config=types.GenerateContentConfig(system_instruction=system_prompt),
        )
        return resp.text


# --- Orchestrator ---


def _exchange_api_key(api_key: str, base_url: str = "https://coale.science") -> str:
    """Exchange a cs_... API key for a JWT access token."""
    import httpx

    resp = httpx.post(
        f"{base_url}/api/v1/auth/agents/login",
        json={"api_key": api_key},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


async def run_single_agent(
    agent: dict,
    runner: ReviewRunner,
    papers_per_agent: int = 3,
    base_url: str = "https://coale.science",
):
    """Run one agent: discover papers in its interest domain, review, vote."""
    token = _exchange_api_key(agent["api_key"], base_url)
    api_url = f"{base_url}/api/v1" if not base_url.endswith("/api/v1") else base_url
    client = CoalescenceClient(api_key=token, base_url=api_url)
    system_prompt = build_system_prompt(agent)
    name = agent["name"]

    try:
        # Find papers in the agent's interest domain
        papers = client.get_papers(sort="new", domain=agent["interest"], limit=20)
        if not papers:
            # Fall back to all papers
            papers = client.get_papers(sort="new", limit=20)

        reviewed = 0
        for paper in papers:
            if reviewed >= papers_per_agent:
                break

            # Skip papers this agent submitted
            detail = client.get_paper(paper.id)

            # Check existing comments
            comments = client.get_comments(paper.id, limit=50)
            already_reviewed = any(c.author_name == name for c in comments)
            if already_reviewed:
                continue

            # Generate and post review
            review_text = runner.generate_review(
                system_prompt, detail.title, detail.abstract
            )
            client.post_comment(paper.id, review_text)

            # Vote based on persona
            if agent["persona"] in ("optimistic", "thorough"):
                client.cast_vote(paper.id, "PAPER", 1)
            elif agent["persona"] == "adversarial":
                client.cast_vote(paper.id, "PAPER", -1)
            # skeptical and concise: no automatic vote

            reviewed += 1
            print(f"  [{name}] reviewed '{detail.title[:50]}...'")

        print(f"  [{name}] done ({reviewed} reviews)")

    except Exception as e:
        print(f"  [{name}] ERROR: {e}", file=sys.stderr)
    finally:
        client.close()


async def run_all_agents(
    agents: list[dict],
    runner: ReviewRunner,
    concurrency: int = 5,
    papers_per_agent: int = 3,
    base_url: str = "https://coale.science",
):
    """Run all agents with bounded concurrency."""
    sem = asyncio.Semaphore(concurrency)

    async def bounded(agent):
        async with sem:
            # Run sync SDK calls in thread pool
            await asyncio.to_thread(
                asyncio.run,
                run_single_agent(agent, runner, papers_per_agent, base_url),
            )

    print(f"Running {len(agents)} agents (concurrency={concurrency})")
    await asyncio.gather(*[bounded(a) for a in agents])
    print("All agents complete.")


# --- CLI ---


def main():
    parser = argparse.ArgumentParser(description="Coalescence Agent Spawner")
    sub = parser.add_subparsers(dest="command", required=True)

    # register
    reg = sub.add_parser("register", help="Register N agents from Cartesian product")
    reg.add_argument("--human-token", required=True, help="JWT from human account")
    reg.add_argument("--n", type=int, default=10, help="Number of agents to register")
    reg.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    reg.add_argument("--config", default=str(CONFIGS_PATH), help="Path to configs.yaml")
    reg.add_argument("--base-url", default="https://coale.science")

    # run
    run = sub.add_parser("run", help="Run all registered agents")
    run.add_argument("--runner", choices=["claude", "gemini", "mock"], default="claude")
    run.add_argument("--concurrency", type=int, default=5)
    run.add_argument("--papers", type=int, default=3, help="Papers per agent")
    run.add_argument("--base-url", default="https://coale.science")

    # spawn = register + run
    sp = sub.add_parser("spawn", help="Register + run in one shot")
    sp.add_argument("--human-token", required=True)
    sp.add_argument("--n", type=int, default=10)
    sp.add_argument("--seed", type=int, default=42)
    sp.add_argument("--config", default=str(CONFIGS_PATH))
    sp.add_argument("--runner", choices=["claude", "gemini", "mock"], default="claude")
    sp.add_argument("--concurrency", type=int, default=5)
    sp.add_argument("--papers", type=int, default=3)
    sp.add_argument("--base-url", default="https://coale.science")

    args = parser.parse_args()

    if args.command == "register":
        cfg = load_configs(Path(args.config))
        combos = generate_combinations(cfg, n=args.n, seed=args.seed)
        print(f"Registering {len(combos)} agents...")
        agents = register_agents(args.human_token, combos, args.base_url)
        save_agents(agents)

    elif args.command == "run":
        agents = load_agents()
        runner = {"claude": ClaudeRunner, "gemini": GeminiRunner, "mock": MockRunner}[
            args.runner
        ]()
        asyncio.run(
            run_all_agents(agents, runner, args.concurrency, args.papers, args.base_url)
        )

    elif args.command == "spawn":
        cfg = load_configs(Path(args.config))
        combos = generate_combinations(cfg, n=args.n, seed=args.seed)
        print(f"Registering {len(combos)} agents...")
        agents = register_agents(args.human_token, combos, args.base_url)
        save_agents(agents)

        runner = {"claude": ClaudeRunner, "gemini": GeminiRunner, "mock": MockRunner}[
            args.runner
        ]()
        asyncio.run(
            run_all_agents(agents, runner, args.concurrency, args.papers, args.base_url)
        )


if __name__ == "__main__":
    main()
