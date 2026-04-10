"""
Built-in example scorers.

Import this module to register them:
    import coalescence.scorer.builtins
"""
from coalescence.scorer.registry import scorer


@scorer(entity="actor")
def comment_depth(actor, ds):
    """Average comment length — proxy for analysis depth."""
    comments = ds.comments.by_author(actor.id)
    if not comments:
        return 0.0
    return sum(c.content_length for c in comments) / len(comments)


@scorer(entity="actor")
def community_trust(actor, ds):
    """Net score received on all comments — how much the community values this actor."""
    comments = ds.comments.by_author(actor.id)
    return sum(c.net_score for c in comments)


@scorer(entity="actor")
def domain_breadth(actor, ds):
    """Number of distinct domains the actor has contributed to."""
    domains = set()
    for c in ds.comments.by_author(actor.id):
        domains.add(c.paper_domain)
    for p in ds.papers.by_author(actor.id):
        domains.add(p.domain)
    return len(domains)


@scorer(entity="paper")
def engagement(paper, ds):
    """Comment threads + votes — overall engagement level."""
    threads = len(ds.comments.roots_for(paper.id))
    votes = len(ds.votes.for_target(paper.id))
    return threads * 2 + votes


@scorer(entity="paper")
def controversy(paper, ds):
    """Downvote ratio — higher means more controversial."""
    total = paper.upvotes + paper.downvotes
    if total == 0:
        return 0.0
    return paper.downvotes / total
