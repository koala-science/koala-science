"""Scrape ICML 2026 OpenReview conversations for koala-science reviewed papers.

Replaces the dead HTML pass (``scrape_icml_openreview.py``). Uses the OpenReview
API2 directly: the anonymous API is challenge-gated, but an authenticated bearer
token clears it.

Pipeline:
  1. Auth: POST /login with $OPENREVIEW_USERNAME / $OPENREVIEW_PASSWORD, or reuse
     a token via $OPENREVIEW_TOKEN / --token-file.
  2. Fetch every ICML 2026 submission with its full reply tree
     (``details=replies``) -> data/icml_2026_openreview_submissions_raw.jsonl.
  3. Match each reviewed paper (title + authors from coalescence_snapshot) to a
     submission: exact normalized-title, else rapidfuzz confirmed by author-surname
     overlap.
  4. Emit per-paper conversations + a 376-row match table (records no-match /
     no-review papers explicitly).

Run from the analysis/ directory, e.g.:
    OPENREVIEW_TOKEN=$(cat /path/or_token.txt) \
        .venv/bin/python scripts/scrape_openreview_conversations.py
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
import psycopg
from rapidfuzz import fuzz, process

API = "https://api2.openreview.net"
VENUE_SUBMISSION_INVITATION = "ICML.cc/2026/Conference/-/Submission"
DB = "postgresql:///coalescence_snapshot"

ROOT = Path(__file__).parent.parent
RAW_OUT = ROOT / "data" / "icml_2026_openreview_submissions_raw.jsonl"
CONV_OUT = ROOT / "data" / "icml_2026_openreview_conversations.jsonl"
MATCH_OUT = ROOT / "data" / "icml_2026_paper_openreview_match.jsonl"

FUZZY_CUTOFF = 90.0
ABS_CUTOFF = 80.0
ACCEPT_VENUES = {"ICML 2026 regular", "ICML 2026 spotlight"}
SCORE_FIELDS = ("overall_recommendation", "confidence", "soundness",
                "presentation", "significance", "originality")
_LEADING_INT = re.compile(r"-?\d+")


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------- #
def norm(s: str) -> str:
    """Normalize a title: lowercase, punctuation -> space, collapse whitespace."""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def unwrap(content: dict) -> dict:
    """Flatten OpenReview ``{field: {"value": v}}`` content to ``{field: v}``."""
    out = {}
    for k, v in content.items():
        out[k] = v["value"] if isinstance(v, dict) and "value" in v else v
    return out


def surnames(authors: list[str]) -> set[str]:
    """Lowercased last-name tokens, for author-overlap confirmation."""
    return {a.split()[-1].lower() for a in authors}


def parse_int(value: str | None) -> int | None:
    """Leading integer of a score string like ``'3'`` or ``'3: accept'``."""
    m = _LEADING_INT.search(str(value))
    return int(m.group()) if m else None


def sig_tail(note: dict) -> str:
    return note["signatures"][0].split("/")[-1]


def has_invitation(note: dict, suffix: str) -> bool:
    return any(i.split("/-/")[-1] == suffix for i in note["invitations"])


def parse_submission(note: dict) -> dict:
    c = unwrap(note["content"])
    return {
        "forum_id": note["forum"],
        "number": note.get("number"),
        "title": c.get("title"),
        "authors": c.get("authors") or [],
        "authorids": c.get("authorids"),
        "abstract": c.get("abstract"),
        "keywords": c.get("keywords"),
        "primary_area": c.get("primary_area"),
        "tldr": c.get("TLDR"),
        "lay_summary": c.get("lay_summary"),
        "link_to_code": c.get("link_to_code"),
        "pdf": c.get("pdf"),
        "venue": c.get("venue"),
        "venueid": c.get("venueid"),
        "paperhash": c.get("paperhash"),
        "cdate": note.get("cdate"),
        "pdate": note.get("pdate"),
    }


def parse_review(note: dict) -> dict:
    c = unwrap(note["content"])
    rec = {
        "reviewer": sig_tail(note),
        "summary": c.get("summary"),
        "strengths_and_weaknesses": c.get("strengths_and_weaknesses"),
        "key_questions_for_authors": c.get("key_questions_for_authors"),
        "limitations": c.get("limitations"),
        "final_justification": c.get("final_justification"),
        "tcdate": note.get("tcdate"),
    }
    for f in SCORE_FIELDS:
        rec[f] = c.get(f)
        rec[f + "_int"] = parse_int(c.get(f))
    return rec


def parse_conversation(note: dict) -> dict:
    """Split a submission's reply tree into typed buckets (edit stubs dropped)."""
    replies = note.get("details", {}).get("replies", [])
    reviews, rebuttals, comments, acks, decisions, meta_reviews = (
        [], [], [], [], [], [])
    for r in replies:
        if has_invitation(r, "Official_Review") and "summary" in r["content"]:
            reviews.append(parse_review(r))
        elif has_invitation(r, "Rebuttal") and "rebuttal" in r["content"]:
            c = unwrap(r["content"])
            rebuttals.append({"author": sig_tail(r), "rebuttal": c.get("rebuttal"),
                              "tcdate": r.get("tcdate")})
        elif has_invitation(r, "Reply_Rebuttal_Comment"):
            c = unwrap(r["content"])
            comments.append({"author": sig_tail(r), "comment": c.get("comment"),
                             "tcdate": r.get("tcdate")})
        elif has_invitation(r, "Rebuttal_Acknowledgement"):
            c = unwrap(r["content"])
            acks.append({"reviewer": sig_tail(r),
                         "acknowledgement": c.get("acknowledgement"),
                         "reasons": c.get("reasons")})
        elif has_invitation(r, "Decision"):
            c = unwrap(r["content"])
            decisions.append({"title": c.get("title"), "decision": c.get("decision"),
                              "comment": c.get("comment"),
                              "reference_correctness_check": c.get("reference_correctness_check")})
        elif has_invitation(r, "Meta_Review"):
            meta_reviews.append(unwrap(r["content"]))

    sub = parse_submission(note)
    return {
        "submission": sub,
        "reviews": reviews,
        "rebuttals": rebuttals,
        "comments": comments,
        "rebuttal_acks": acks,
        "meta_reviews": meta_reviews,
        "decision": decisions[0] if decisions else None,
    }


def build_index(submissions: list[dict]) -> dict:
    """normalized-title -> list of submission dicts (parsed)."""
    idx: dict[str, list[dict]] = {}
    for s in submissions:
        idx.setdefault(norm(s["title"]), []).append(s)
    return idx


def build_author_index(submissions: list[dict]) -> dict:
    """frozenset of author surnames -> submissions with a non-empty abstract.

    Backs the abstract-confirmed fallback: papers renamed between arxiv and
    OpenReview share no title tokens but keep authors + abstract.
    """
    idx: dict[frozenset, list[dict]] = {}
    for s in submissions:
        if not s.get("abstract"):
            continue
        idx.setdefault(frozenset(surnames(s["authors"])), []).append(s)
    return idx


def match_paper(title: str, abstract: str, authors: list[str], index: dict,
                titles: list[str], author_index: dict,
                cutoff: float = FUZZY_CUTOFF, abs_cutoff: float = ABS_CUTOFF) -> dict:
    """Match one paper to a submission.

    exact title -> fuzzy title + author overlap -> full-author-set + abstract
    similarity (catches full renames) -> none.
    """
    nt = norm(title)
    if nt in index:
        return {"method": "exact", "score": 100.0, "submission": index[nt][0]}

    hit = process.extractOne(nt, titles, scorer=fuzz.token_set_ratio,
                             score_cutoff=cutoff)
    if hit is not None:
        cand = index[hit[0]][0]
        if surnames(authors) & surnames(cand["authors"]):
            return {"method": "fuzzy", "score": float(hit[1]), "submission": cand}

    key = frozenset(surnames(authors))
    if len(key) >= 2 and key in author_index:
        scored = [(fuzz.token_set_ratio(abstract, c["abstract"]), c)
                  for c in author_index[key]]
        best_sim, best = max(scored, key=lambda x: x[0])
        if best_sim >= abs_cutoff:
            return {"method": "author_abstract", "score": float(best_sim),
                    "submission": best}

    return {"method": "none", "score": 0.0, "submission": None}


# --------------------------------------------------------------------------- #
# IO / network
# --------------------------------------------------------------------------- #
def get_token(args) -> str:
    if args.token_file:
        return Path(args.token_file).read_text().strip()
    if os.environ.get("OPENREVIEW_TOKEN"):
        return os.environ["OPENREVIEW_TOKEN"].strip()
    user, pw = os.environ.get("OPENREVIEW_USERNAME"), os.environ.get("OPENREVIEW_PASSWORD")
    if not user or not pw:
        sys.exit("provide --token-file, or $OPENREVIEW_TOKEN, or "
                 "$OPENREVIEW_USERNAME + $OPENREVIEW_PASSWORD")
    resp = httpx.post(f"{API}/login", json={"id": user, "password": pw},
                      headers={"User-Agent": "koala-science-research"}, timeout=30.0)
    if resp.status_code != 200:
        sys.exit(f"login failed: HTTP {resp.status_code} — {resp.text[:200]}")
    return resp.json()["token"]


def fetch_all_submissions(token: str, refresh: bool) -> list[dict]:
    if RAW_OUT.exists() and RAW_OUT.stat().st_size > 0 and not refresh:
        print(f"reusing {RAW_OUT.name} (pass --refresh to re-fetch)")
        return [json.loads(l) for l in RAW_OUT.open()]

    headers = {"Authorization": f"Bearer {token}", "User-Agent": "koala-science-research"}
    notes, offset = [], 0
    RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with httpx.Client(headers=headers, timeout=90.0) as client, RAW_OUT.open("w") as f:
        while True:
            resp = client.get(f"{API}/notes", params={
                "invitation": VENUE_SUBMISSION_INVITATION,
                "details": "replies", "limit": 1000, "offset": offset})
            resp.raise_for_status()
            page = resp.json()["notes"]
            if not page:
                break
            for n in page:
                f.write(json.dumps(n, ensure_ascii=False) + "\n")
            notes.extend(page)
            offset += len(page)
            print(f"  fetched {len(notes)} submissions "
                  f"({len(notes)/max(time.time()-started,1e-9):.0f}/s)", flush=True)
            if len(page) < 1000:
                break
    print(f"total submissions: {len(notes)} in {time.time()-started:.0f}s")
    return notes


def load_reviewed_papers() -> list[dict]:
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id::text, title, arxiv_id, abstract, authors
            FROM paper WHERE status = 'reviewed'
        """)
        rows = cur.fetchall()
    papers = []
    for pid, title, arxiv_id, abstract, authors in rows:
        if isinstance(authors, list):
            names = [a["name"] if isinstance(a, dict) else a for a in authors]
        else:
            names = []
        papers.append({"paper_id": pid, "title": title, "arxiv_id": arxiv_id,
                       "abstract": abstract, "authors": names})
    return papers


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--token-file")
    p.add_argument("--refresh", action="store_true",
                   help="re-fetch submissions even if the raw file exists")
    p.add_argument("--cutoff", type=float, default=FUZZY_CUTOFF)
    args = p.parse_args()

    token = get_token(args)
    raw = fetch_all_submissions(token, args.refresh)
    submissions = [parse_submission(n) for n in raw]
    by_forum = {n["forum"]: n for n in raw}

    index = build_index(submissions)
    titles = list(index.keys())
    author_index = build_author_index(submissions)
    print(f"unique submission titles: {len(titles)}")

    papers = load_reviewed_papers()
    print(f"reviewed papers: {len(papers)}")

    match_rows, conversations = [], []
    counts = {"exact": 0, "fuzzy": 0, "author_abstract": 0, "none": 0}
    zero_review = 0
    n_accepted = 0
    for pap in papers:
        m = match_paper(pap["title"], pap["abstract"], pap["authors"], index,
                        titles, author_index, args.cutoff)
        counts[m["method"]] += 1
        row = {"paper_id": pap["paper_id"], "our_title": pap["title"],
               "arxiv_id": pap["arxiv_id"], "match_method": m["method"],
               "score": round(m["score"], 1)}
        if m["submission"] is None:
            row.update({"status": "no_match", "forum_id": None, "n_reviews": None,
                        "venue": None, "accepted": False})
            match_rows.append(row)
            continue

        forum_id = m["submission"]["forum_id"]
        venue = m["submission"]["venue"]
        accepted = venue in ACCEPT_VENUES
        n_accepted += accepted
        conv = parse_conversation(by_forum[forum_id])
        n_rev = len(conv["reviews"])
        if n_rev == 0:
            zero_review += 1
        row.update({"status": "matched", "forum_id": forum_id, "n_reviews": n_rev,
                    "venue": venue, "accepted": accepted})
        match_rows.append(row)
        conversations.append({
            "paper_id": pap["paper_id"], "our_title": pap["title"],
            "arxiv_id": pap["arxiv_id"], "forum_id": forum_id,
            "match": {"method": m["method"], "score": round(m["score"], 1),
                      "matched_title": m["submission"]["title"]},
            **conv,
        })

    with MATCH_OUT.open("w") as f:
        for r in match_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with CONV_OUT.open("w") as f:
        for c in conversations:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    n_rev_dist = {}
    for c in conversations:
        k = len(c["reviews"])
        n_rev_dist[k] = n_rev_dist.get(k, 0) + 1
    print(f"\nmatched: exact={counts['exact']} fuzzy={counts['fuzzy']} "
          f"author_abstract={counts['author_abstract']} no_match={counts['none']}")
    print(f"accepted (venue regular/spotlight): {n_accepted}")
    print(f"matched but 0 reviews: {zero_review}")
    print("review-count distribution (n_reviews: papers): "
          f"{dict(sorted(n_rev_dist.items()))}")
    print(f"\nwrote {MATCH_OUT.name} ({len(match_rows)} rows), "
          f"{CONV_OUT.name} ({len(conversations)} rows)")


if __name__ == "__main__":
    main()
