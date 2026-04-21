"""Tests for Dataset loading, collections, and accessors."""
from datetime import datetime


class TestDatasetLoad:

    def test_load_counts(self, ds):
        assert len(ds.papers) == 3
        assert len(ds.comments) == 4
        assert len(ds.actors) == 3
        assert len(ds.events) == 5
        assert len(ds.domains) == 2

    def test_repr(self, ds):
        assert "3 papers" in repr(ds)
        assert "4 comments" in repr(ds)

    def test_summary(self, ds):
        s = ds.summary()
        assert "Papers:" in s
        assert "Actors:" in s

    def test_load_missing_file(self, tmp_path):
        """Missing JSONL files should result in empty collections, not errors."""
        from coalescence.data import Dataset
        (tmp_path / "papers.jsonl").write_text("")
        ds = Dataset.load(str(tmp_path))
        assert len(ds.papers) == 0
        assert len(ds.comments) == 0


class TestPaperCollection:

    def test_filter_by_domain(self, ds):
        nlp = ds.papers["d/NLP"]
        assert len(nlp) == 2

        bio = ds.papers["d/Bioinformatics"]
        assert len(bio) == 1

    def test_domain_not_found(self, ds):
        import pytest
        with pytest.raises(KeyError):
            ds.papers["d/DoesNotExist"]

    def test_get_by_id(self, ds):
        p = ds.papers.get("p1")
        assert p is not None
        assert p.title == "Attention Is All You Need"

        assert ds.papers.get("nonexistent") is None

    def test_by_author(self, ds):
        alice_papers = ds.papers.by_author("a1")
        assert len(alice_papers) == 2  # p1 and p3

    def test_domains_list(self, ds):
        assert set(ds.papers.domains) == {"d/NLP", "d/Bioinformatics"}

    def test_embeddings(self, ds):
        emb = ds.papers.embeddings()
        assert emb.shape == (2, 768)  # only p1 and p3 have embeddings

    def test_embedding_ids(self, ds):
        ids = ds.papers.embedding_ids()
        assert len(ids) == 2
        assert "p1" in ids
        assert "p3" in ids

    def test_to_df(self, ds):
        df = ds.papers.to_df()
        assert len(df) == 3
        assert "title" in df.columns
        assert "domain" in df.columns

    def test_chaining(self, ds):
        result = ds.papers["d/NLP"].by_author("a1")
        assert len(result) == 1  # only p1 (p3 is Bioinformatics)

    def test_iter_and_bool(self, ds):
        assert bool(ds.papers)
        titles = [p.title for p in ds.papers]
        assert len(titles) == 3


class TestCommentCollection:

    def test_by_author(self, ds):
        bot_comments = ds.comments.by_author("a2")
        assert len(bot_comments) == 1

    def test_for_paper(self, ds):
        p1_comments = ds.comments.for_paper("p1")
        assert len(p1_comments) == 3  # c1, c2, c3

    def test_roots_for(self, ds):
        roots = ds.comments.roots_for("p1")
        assert len(roots) == 1  # only c1

    def test_children(self, ds):
        children = ds.comments.children("c1")
        assert len(children) == 2  # c2 and c3

    def test_subtree(self, ds):
        tree = ds.comments.subtree("c1")
        assert len(tree) == 3  # c1, c2, c3

    def test_subtree_leaf(self, ds):
        tree = ds.comments.subtree("c2")
        assert len(tree) == 1  # just c2 (no children)

    def test_thread_embeddings(self, ds):
        emb = ds.comments.thread_embeddings()
        assert emb.shape == (1, 768)  # only c1 has thread_embedding

    def test_get(self, ds):
        c = ds.comments.get("c1")
        assert c is not None
        assert c.author_name == "Bot1"


class TestActorCollection:

    def test_humans(self, ds):
        assert len(ds.actors.humans) == 2  # Alice and Bob

    def test_agents(self, ds):
        assert len(ds.actors.agents) == 1  # Bot1

    def test_get(self, ds):
        a = ds.actors.get("a1")
        assert a is not None
        assert a.name == "Alice"


class TestEventCollection:

    def test_of_type(self, ds):
        comments = ds.events.of_type("COMMENT_POSTED")
        assert len(comments) == 3

    def test_by_actor(self, ds):
        alice_events = ds.events.by_actor("a1")
        assert len(alice_events) == 3  # e1, e4, e6


class TestDomainCollection:

    def test_get_by_name(self, ds):
        d = ds.domains.get("d/NLP")
        assert d is not None
        assert d.subscriber_count == 10

    def test_get_by_id(self, ds):
        d = ds.domains.get("d1")
        assert d is not None
        assert d.name == "d/NLP"

    def test_len(self, ds):
        assert len(ds.domains) == 2


class TestTimelineFilters:

    def test_created_after(self, ds):
        march = datetime(2026, 3, 1)
        recent = ds.papers.created_after(march)
        assert len(recent) == 2  # p1 (Mar 1), p2 (Mar 15) — p3 is Feb

    def test_created_before(self, ds):
        march = datetime(2026, 3, 1)
        old = ds.papers.created_before(march)
        assert len(old) == 1  # p3 (Feb 1)

    def test_created_range(self, ds):
        start = datetime(2026, 3, 1)
        end = datetime(2026, 3, 10)
        window = ds.papers.created_after(start).created_before(end)
        assert len(window) == 1  # p1 (Mar 1) — p2 is Mar 15

    def test_last_activity_after(self, ds):
        """Papers with events after March 2 should include p1."""
        march_2 = datetime(2026, 3, 2)
        active = ds.papers.last_activity_after(march_2)
        # p1 has events on Mar 2, 3 — should be active
        assert any(p.id == "p1" for p in active)

    def test_last_activity_on_comments(self, ds):
        """Comments with replies after a date."""
        march_3 = datetime(2026, 3, 3)
        active = ds.comments.last_activity_after(march_3)
        # c1 has replies on Mar 3 and Mar 4
        assert any(c.id == "c1" for c in active)

    def test_actor_last_activity(self, ds):
        march_3 = datetime(2026, 3, 3)
        active = ds.actors.last_activity_after(march_3)
        # a1 has events on Mar 3 (e4)
        assert any(a.id == "a1" for a in active)

    def test_chained_with_domain(self, ds):
        march = datetime(2026, 3, 1)
        result = ds.papers["d/NLP"].created_after(march)
        assert len(result) == 2

    def test_comments_timeline_chain(self, ds):
        march_3 = datetime(2026, 3, 3)
        result = ds.comments.by_author("a1").created_after(march_3)
        # a1's comment c2 is on Mar 3 — should be included (created_after is >=)
        assert len(result) == 1  # c2


class TestInteractionGraph:

    def test_graph_nodes(self, ds):
        G = ds.interaction_graph()
        assert G.number_of_nodes() == 3

    def test_graph_has_edges(self, ds):
        G = ds.interaction_graph()
        assert G.number_of_edges() > 0

    def test_node_attributes(self, ds):
        G = ds.interaction_graph()
        assert G.nodes["a1"]["type"] == "human"
        assert G.nodes["a1"]["name"] == "Alice"

    def test_edge_relations(self, ds):
        G = ds.interaction_graph()
        relations = set()
        for u, v, data in G.edges(data=True):
            relations.add(data.get("relation"))
        # Should have at least commented_on or replied_to
        assert "commented_on" in relations or "replied_to" in relations
