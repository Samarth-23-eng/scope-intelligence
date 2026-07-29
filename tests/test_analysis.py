from agents.analysis.base import BaseAnalysisAgent
from agents.analysis.predictor import PredictorAgent
from agents.analysis.signal_detector import SignalDetectorAgent
from agents.analysis.summariser import SummariserAgent
from agents.discovery.entity_resolver import EntityResolverAgent
from config.settings import settings
from intelligence.retrieval import EvidencePack, RetrievalHit


def evidence_hit(chunk_id=71, evidence_id=31):
    return RetrievalHit(
        chunk_id=chunk_id,
        evidence_id=evidence_id,
        document_id=9,
        document_version_id=10,
        source_url="https://example.com/news",
        title="Expansion announcement",
        source_type="news",
        content="Example opened a new engineering center in India.",
        published_at=None,
        collected_at=None,
        score=0.8,
        retrieval_methods=("lexical",),
        metadata={},
    )


def test_safe_json_parse_strips_markdown_fence():
    agent = BaseAnalysisAgent(1, "Example")

    parsed = agent.safe_json_parse('```json\n{"signals": []}\n```')

    assert parsed == {"signals": []}


def test_safe_json_parse_recovers_json_surrounded_by_multiple_prose_braces():
    agent = BaseAnalysisAgent(1, "Example")

    parsed = agent.safe_json_parse(
        'Draft {not valid}. Final answer: {"signals": [], "summary": "ready"} trailing.'
    )

    assert parsed == {"signals": [], "summary": "ready"}


def test_structured_output_repairs_invalid_citations_once(monkeypatch):
    agent = BaseAnalysisAgent(1, "Example")
    responses = iter(
        [
            '{"signals":[{"signal":"Expansion","severity":"high","evidence_ids":[999]}]}',
            '{"signals":[{"signal":"Expansion","severity":"high","evidence_ids":[31]}]}',
        ]
    )
    monkeypatch.setattr(agent, "llm_call", lambda **kwargs: next(responses))

    payload = agent.structured_llm_call(
        prompt="Analyze supplied evidence.",
        system_prompt="Return JSON.",
        validator=lambda item: agent.validate_grounded_collection(
            item,
            collection_key="signals",
            statement_key="signal",
            allowed_evidence_ids={31},
            allowed_chunk_ids={71},
            maximum_items=3,
            allowed_values={"severity": {"high", "medium", "low"}},
        ),
    )

    assert payload["signals"][0]["evidence_ids"] == [31]
    assert agent.last_output_diagnostics["status"] == "repaired"
    assert agent.last_output_diagnostics["attempts"] == 2
    assert agent.last_output_diagnostics["grounded_items"] == 1
    assert agent.last_output_diagnostics["rejected_items"] == 1
    assert "unknown evidence_ids" in agent.last_output_diagnostics["validation_errors"][0]


def test_all_llm_agents_share_the_configured_model():
    agents = [
        SummariserAgent(1, "Example"),
        SignalDetectorAgent(1, "Example"),
        PredictorAgent(1, "Example"),
        EntityResolverAgent(1, "Example"),
    ]

    assert {agent.model for agent in agents} == {settings.llm_model}


def test_monitoring_focus_topics_reach_analysis_context():
    agent = SummariserAgent(
        1,
        "Example",
        focus_topics=["India hiring", "partnerships", "India hiring"],
    )

    assert agent.focus_topics == ["India hiring", "partnerships"]
    assert "India hiring" in agent.focus_query()
    assert "partnerships" in agent.focus_prompt()


def test_summariser_falls_back_to_recent_citable_evidence(monkeypatch):
    agent = SummariserAgent(1, "Example")
    prompts = []

    monkeypatch.setattr(
        agent,
        "retrieve_evidence_pack",
        lambda queries, **kwargs: EvidencePack(
            hits=(evidence_hit(),),
            diagnostics={
                "candidate_chunks": 1,
                "selected_chunks": 1,
                "selected_domains": 1,
                "selected_source_types": 1,
            },
        ),
    )
    monkeypatch.setattr(
        agent,
        "llm_call",
        lambda prompt, **kwargs: prompts.append(prompt) or (
            '{"summary":"Evidence-backed summary","confidence":0.9,'
            '"claims":[{"statement":"Example opened an engineering center.",'
            '"claim_type":"business_move","confidence":0.9,'
            '"evidence_ids":[31],"chunk_ids":[71]}]}'
        ),
    )
    monkeypatch.setattr(agent, "save_claim", lambda **kwargs: 501)
    monkeypatch.setattr(agent, "save_insight", lambda **kwargs: True)

    result = agent.collect()

    assert result == "Evidence-backed summary"
    assert "EVIDENCE_ID: 31" in prompts[0]
    assert "CHUNK_ID: 71" in prompts[0]
