from datetime import datetime, timedelta, timezone

from intelligence.graph import EvidenceSignal, RelationshipIntelligenceEngine


def signal(source_type, source_key, confidence=0.9, stance="supports", age_days=0):
    return EvidenceSignal(
        evidence_id=1,
        stance=stance,
        source_type=source_type,
        source_key=source_key,
        confidence=confidence,
        observed_at=datetime.now(timezone.utc) - timedelta(days=age_days),
    )


def test_entity_aliases_remove_legal_suffixes_and_add_acronym():
    aliases = RelationshipIntelligenceEngine.aliases_for(
        "Acme Industrial Technologies Private Limited"
    )
    values = {alias for alias, _, _ in aliases}

    assert "Acme Industrial" in values
    assert "AI" in values
    assert (
        RelationshipIntelligenceEngine.normalize_entity_name(
            "Acme Industrial Technologies Pvt. Ltd."
        )
        == "acmeindustrial"
    )


def test_relationship_score_rewards_independent_corroboration():
    one_source = RelationshipIntelligenceEngine.score_relationship(
        0.7,
        [signal("first_party_website", "example.com")],
    )
    two_sources = RelationshipIntelligenceEngine.score_relationship(
        0.7,
        [
            signal("first_party_website", "example.com"),
            signal("news_article", "reuters.com"),
        ],
    )

    assert two_sources["weight"] > one_source["weight"]
    assert one_source["source_diversity"] == 1
    assert two_sources["source_diversity"] == 2
    assert two_sources["risk_level"] == "low"


def test_relationship_score_marks_strong_contradiction_as_disputed():
    result = RelationshipIntelligenceEngine.score_relationship(
        0.8,
        [
            signal("first_party_website", "example.com", confidence=0.9),
            signal(
                "government",
                "regulator.example",
                confidence=0.9,
                stance="contradicts",
            ),
        ],
    )

    assert result["status"] == "disputed"
    assert result["contradiction_count"] == 1
    assert result["risk_level"] == "critical"


def test_graph_metrics_identify_the_most_connected_entity():
    entities = [
        {"id": 1, "name": "Acme", "entity_type": "company"},
        {"id": 2, "name": "Partner A", "entity_type": "partner"},
        {"id": 3, "name": "Partner B", "entity_type": "partner"},
        {"id": 4, "name": "Isolated", "entity_type": "company"},
    ]
    relationships = [
        {"source_entity_id": 1, "target_entity_id": 2, "weight": 0.8},
        {"source_entity_id": 1, "target_entity_id": 3, "weight": 0.9},
    ]

    metrics = RelationshipIntelligenceEngine.graph_metrics(entities, relationships)

    assert metrics["component_count"] == 2
    assert metrics["isolated_entities"] == 1
    assert metrics["strategic_nodes"][0]["entity_id"] == 1
    assert metrics["strategic_nodes"][0]["degree"] == 2
