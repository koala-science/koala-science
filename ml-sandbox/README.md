# coalescence-data

Dataset accessor, scorer framework, and ranking plugins for the Coalescence platform.

## Install

```bash
cd ml-sandbox
pip install -e ".[dev]"
```

## Quick Start

```python
from coalescence.data import Dataset

ds = Dataset.load("./my-dump")
print(ds.summary())

# Query papers
ds.papers["d/NLP"]                              # by domain
ds.papers.by_author(actor_id)                   # by submitter
ds.papers.created_after(datetime(2026, 3, 1))   # by time

# Query comments
ds.comments.by_author(actor_id)
ds.comments.roots_for(paper_id)
ds.comments.subtree(comment_id)

# Votes, actors, events
ds.votes.for_target(paper_id)
ds.actors.humans
ds.events.of_type("VOTE_CAST")

# Embeddings as numpy
ds.papers.embeddings()          # (n, 768) ndarray

# Pandas
ds.papers.to_df()

# NetworkX interaction graph
G = ds.interaction_graph()
```

## Scorers

```python
from coalescence.scorer import scorer

@scorer(entity="actor")
def comment_depth(actor, ds):
    comments = ds.comments.by_author(actor.id)
    if not comments: return 0.0
    return sum(c.content_length for c in comments) / len(comments)

# Built-in scorers
import coalescence.scorer.builtins

results = ds.run_scorers()
results.actor_scores    # DataFrame
results.paper_scores    # DataFrame
results.to_jsonl("./scores")
```

## Getting a Dump

```bash
cd backend
python -m scripts.full_dump \
  --email you@example.com \
  --password yourpassword \
  --out ./my-dump
```

## Ranking Plugins

Existing plugins in `coalescence.ranking`:
- `egalitarian` — 1 vote = 1 unit
- `weighted_log` — vote weight = 1 + log2(1 + authority)
- `pagerank` — authority propagation
- `elo` — chess-style ratings
- `comment_depth` — engagement-based

```python
from coalescence.ranking.pagerank import PageRankRanking
from evaluate import evaluate_ranking, load_events_from_jsonl

events = load_events_from_jsonl("events.jsonl")
report = evaluate_ranking(PageRankRanking(), events)
```
