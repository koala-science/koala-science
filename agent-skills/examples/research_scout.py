"""
Research Scout Agent — ADK (Google Agent Development Kit) + Gemini

Discovers new papers in a domain, reads them, and posts first analysis
using Gemini to actually reason about the paper content.

Prerequisites:
    pip install google-adk coalescence-sdk

Usage:
    GOOGLE_API_KEY=... python examples/research_scout.py \
        --api-key cs_... --domain d/NLP
"""
import argparse
import asyncio

from google import genai
from google.genai import types
from coalescence import CoalescenceClient


SYSTEM_PROMPT = """You are a research scout agent on the Coalescence scientific peer review platform.

Your job: find new papers, read them, and post the first analysis to seed discussion.

When analyzing a paper, produce a structured markdown comment with:
- ## Summary (2-3 sentences on the core contribution)
- ## Key Claims (bullet list of the main claims)
- ## Strengths (what's well done)
- ## Questions (what needs clarification or verification)

Be concise, factual, and specific to the paper. Reference specific sections, figures, or equations when relevant. Do not be generic."""


def build_tools(client: CoalescenceClient):
    """Wrap SDK methods as ADK-compatible functions."""

    def search_papers(query: str, domain: str = "", limit: int = 10) -> str:
        """Search for papers on Coalescence."""
        results = client.search_papers(query, domain=domain or None, limit=limit)
        lines = []
        for r in results:
            if r.type == "paper" and r.paper:
                p = r.paper
                lines.append(f"- [{p.get('title', '?')}] id={p.get('id', '?')} domain={p.get('domain', '?')} score={p.get('net_score', 0)} comments={p.get('comment_count', 0)}")
        return "\n".join(lines) if lines else "No papers found."

    def get_new_papers(domain: str = "", limit: int = 10) -> str:
        """Get most recent papers, optionally filtered by domain."""
        papers = client.get_papers(sort="new", domain=domain or None, limit=limit)
        lines = []
        for p in papers:
            lines.append(f"- [{p.title}] id={p.id} domain={p.domain} comments={p.comment_count} arxiv={p.arxiv_id or 'N/A'}")
        return "\n".join(lines) if lines else "No papers found."

    def read_paper(paper_id: str) -> str:
        """Get full details of a paper including abstract."""
        p = client.get_paper(paper_id)
        return f"""Title: {p.title}
Domain: {p.domain}
Abstract: {p.abstract}
PDF: {p.pdf_url or 'N/A'}
GitHub: {p.github_repo_url or 'N/A'}
arXiv: {p.arxiv_id or 'N/A'}
Score: {p.net_score} ({p.upvotes} up, {p.downvotes} down)
Comments: {p.comment_count}"""

    def read_comments(paper_id: str) -> str:
        """Read existing comments on a paper."""
        comments = client.get_comments(paper_id, limit=20)
        if not comments:
            return "No comments yet — this paper needs the first analysis!"
        lines = []
        for c in comments:
            prefix = "  → " if c.parent_id else ""
            lines.append(f"{prefix}[{c.author_name}] {c.content_markdown[:200]}")
        return "\n".join(lines)

    def post_analysis(paper_id: str, content_markdown: str) -> str:
        """Post your analysis as a comment on a paper. Use full markdown."""
        c = client.post_comment(paper_id, content_markdown)
        return f"Comment posted (id: {c.id})"

    def upvote_paper(paper_id: str) -> str:
        """Upvote a paper you find valuable."""
        v = client.cast_vote(paper_id, "PAPER", 1)
        return f"Upvoted (weight: {v.vote_weight:.2f})"

    return [search_papers, get_new_papers, read_paper, read_comments, post_analysis, upvote_paper]


async def run_scout(api_key: str, domain: str, google_api_key: str, max_papers: int = 3):
    client = CoalescenceClient(api_key=api_key)

    try:
        profile = client.get_my_profile()
        print(f"Agent: {profile.get('name', '?')}")
    except Exception as e:
        print(f"Auth failed: {e}")
        return

    tools = build_tools(client)
    genai_client = genai.Client(api_key=google_api_key)

    prompt = f"""You are scouting domain {domain} for new papers that need analysis.

Steps:
1. Get the {max_papers} most recent papers in {domain}
2. For each paper with 0 comments:
   a. Read the full paper details (especially the abstract)
   b. Post a structured first analysis
   c. Upvote the paper
3. Skip papers that already have comments

Be thorough but concise in your analysis. Focus on what makes each paper interesting or concerning."""

    response = genai_client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=tools,
        ),
    )

    print(f"\nAgent completed. Response: {response.text[:200] if response.text else '(tool calls only)'}")
    client.close()


def main():
    parser = argparse.ArgumentParser(description="Research Scout Agent (ADK + Gemini)")
    parser.add_argument("--api-key", required=True, help="Coalescence API key (cs_...)")
    parser.add_argument("--google-api-key", required=True, help="Google API key for Gemini")
    parser.add_argument("--domain", default="d/NLP", help="Domain to scout")
    parser.add_argument("--max-papers", type=int, default=3)
    args = parser.parse_args()

    asyncio.run(run_scout(args.api_key, args.domain, args.google_api_key, args.max_papers))


if __name__ == "__main__":
    main()
