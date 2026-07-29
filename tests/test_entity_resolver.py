from agents.discovery.entity_resolver import EntityResolverAgent


def test_entity_resolver_cleans_untrusted_shapes():
    assert EntityResolverAgent.clean_names([" Claude ", "claude", None, {"name": "bad"}]) == [
        "Claude"
    ]
    assert EntityResolverAgent.clean_executives(
        [
            {"name": " Dario Amodei ", "title": "CEO"},
            {"title": "Missing name"},
            "invalid",
        ]
    ) == [{"name": "Dario Amodei", "title": "CEO"}]


def test_relationship_cleaning_supports_multihop_and_rejects_foreign_evidence():
    resolver = EntityResolverAgent(1, "Example")
    relationships = [
        {
            "source": {"name": "Example", "type": "company"},
            "target": {"name": "Stripe", "type": "integration"},
            "type": "integrates with",
            "confidence": 0.82,
            "rationale": "Listed on the integrations page.",
            "evidence_ids": [7, 999, "7"],
        },
        {
            "source": {"name": "Stripe", "type": "company"},
            "target": {"name": "Example Extension", "type": "product"},
            "type": "offers",
            "confidence": 0.7,
            "evidence_ids": [7],
        },
        {
            "source": {"name": "Example", "type": "company"},
            "target": {"name": "Unsupported", "type": "company"},
            "type": "invented_relation",
            "evidence_ids": [7],
        },
    ]

    cleaned = resolver.clean_relationships(relationships, {}, {7})

    assert len(cleaned) == 2
    assert cleaned[0]["relationship_type"] == "integrates_with"
    assert cleaned[0]["evidence_ids"] == [7]
    assert cleaned[1]["source_name"] == "Stripe"
    assert cleaned[1]["target_name"] == "Example Extension"


def test_relationship_confidence_rewards_multiple_strong_sources():
    uncited = EntityResolverAgent.score_confidence(0.9, [])
    cited = EntityResolverAgent.score_confidence(0.8, [0.9, 0.8])

    assert uncited == 0.6
    assert cited > uncited
    assert cited <= 1


def test_person_entities_reuse_legacy_executive_nodes():
    assert EntityResolverAgent.equivalent_entity_types("person") == ("person", "executive")
    assert EntityResolverAgent.equivalent_entity_types("company") == ("company",)
