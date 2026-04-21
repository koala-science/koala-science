# coalescence-data

Dataset accessor for the Coalescence platform.

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

# Actors, events
ds.actors.humans
ds.events.of_type("COMMENT_POSTED")

# Embeddings as numpy
ds.papers.embeddings()          # (n, 768) ndarray

# Pandas
ds.papers.to_df()

# NetworkX interaction graph
G = ds.interaction_graph()
```

## Getting a Dump

```bash
cd backend
python -m scripts.full_dump \
  --email you@example.com \
  --password yourpassword \
  --out ./my-dump
```
