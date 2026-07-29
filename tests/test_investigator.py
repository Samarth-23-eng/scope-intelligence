from agents.analysis.investigator import InvestigationAgent
from intelligence.retrieval import RetrievalHit


def hit(chunk_id=10, evidence_id=20, url="https://example.com/source"):
    return RetrievalHit(
        chunk_id=chunk_id,
        evidence_id=evidence_id,
        document_id=1,
        document_version_id=1,
        source_url=url,
        title="Source title",
        source_type="first_party_website",
        content="Evidence-backed source content.",
        published_at=None,
        collected_at=None,
        score=0.03,
        retrieval_methods=("semantic", "lexical"),
        metadata={},
    )


def test_investigation_plan_fallback_respects_step_budget():
    agent = InvestigationAgent(1, "Example")

    plan = agent._fallback_plan("Is Example expanding?", 2)

    assert len(plan) == 2
    assert all(item["question"] and item["search_query"] for item in plan)


def test_investigation_rejects_hallucinated_citation_ids():
    available = {20: hit()}

    assert InvestigationAgent._valid_ids([20, "20", 999, "bad"], available) == [20]


def test_investigation_fallback_remains_citation_bound():
    agent = InvestigationAgent(1, "Example")
    source = hit()

    payload = agent._fallback_step({"question": "What changed?"}, [source])

    assert payload["findings"][0]["evidence_ids"] == [20]
    assert payload["findings"][0]["chunk_ids"] == [10]
    assert payload["findings"][0]["status"] == "provisional"


def test_investigation_source_diversity_counts_domains_not_pages():
    hits = [
        hit(chunk_id=1, url="https://example.com/a"),
        hit(chunk_id=2, url="https://example.com/b"),
        hit(chunk_id=3, url="https://github.com/example/repo"),
    ]

    assert InvestigationAgent._source_diversity(hits) == 2


def test_investigation_honors_cancel_requested_while_queued(monkeypatch):
    agent = InvestigationAgent(1, "Example")
    monkeypatch.setattr(
        agent,
        "_load_investigation",
        lambda _investigation_id: {
            "status": "queued",
            "cancel_requested_at": "2026-07-28T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        agent,
        "_finish_cancelled",
        lambda investigation_id, completed: {
            "id": investigation_id,
            "status": "cancelled",
            "completed": completed,
        },
    )
    monkeypatch.setattr(
        agent,
        "_start",
        lambda _investigation_id: (_ for _ in ()).throw(
            AssertionError("cancelled queued investigation must not start")
        ),
    )

    result = agent.run(7)

    assert result["status"] == "cancelled"
