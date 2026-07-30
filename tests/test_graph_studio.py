from api import graph_routes


def entity(entity_id: int, name: str):
    return {
        "id": entity_id,
        "competitor_id": 7,
        "name": name,
        "entity_type": "company",
        "metadata": {},
        "created_at": "2026-07-30T00:00:00Z",
        "updated_at": "2026-07-30T00:00:00Z",
    }


def relationship(
    relationship_id: int,
    source_id: int,
    target_id: int,
    weight: float,
):
    return {
        "id": relationship_id,
        "source_entity_id": source_id,
        "source_name": f"Entity {source_id}",
        "source_type": "company",
        "target_entity_id": target_id,
        "target_name": f"Entity {target_id}",
        "target_type": "company",
        "relationship_type": "partners_with",
        "weight": weight,
        "rationale": "Evidence-bound relationship.",
        "extraction_method": "llm",
        "evidence_count": 1,
        "corroboration_score": weight,
        "source_diversity": 1,
        "freshness_score": 1,
        "contradiction_count": 0,
        "risk_level": "medium",
        "status": "active",
        "operator_status": None,
        "operator_note": None,
        "metadata": {},
        "created_at": "2026-07-30T00:00:00Z",
        "first_seen_at": "2026-07-30T00:00:00Z",
        "last_seen_at": "2026-07-30T00:00:00Z",
        "evidence": [],
    }


def test_strongest_path_prefers_better_supported_route(monkeypatch):
    entities = [
        entity(1, "Start"),
        entity(2, "Weak middle"),
        entity(3, "Strong middle"),
        entity(4, "Target"),
    ]
    relationships = [
        relationship(1, 1, 2, 0.3),
        relationship(2, 2, 4, 0.3),
        relationship(3, 1, 3, 0.9),
        relationship(4, 3, 4, 0.9),
    ]
    monkeypatch.setattr(
        graph_routes,
        "_graph_rows",
        lambda competitor_id: (entities, relationships),
    )

    result = graph_routes.find_graph_path(
        competitor_id=7,
        source_entity_id=1,
        target_entity_id=4,
        mode="strongest",
    )

    assert [row["id"] for row in result["nodes"]] == [1, 3, 4]
    assert [row["id"] for row in result["relationships"]] == [3, 4]


def test_snapshot_diff_classifies_strengthened_and_added_edges(monkeypatch):
    first = (
        [entity(1, "A"), entity(2, "B")],
        [relationship(1, 1, 2, 0.5)],
    )
    second = (
        [entity(1, "A"), entity(2, "B"), entity(3, "C")],
        [
            relationship(1, 1, 2, 0.8),
            relationship(2, 2, 3, 0.7),
        ],
    )
    monkeypatch.setattr(
        graph_routes,
        "_snapshot_state",
        lambda competitor_id, snapshot_id: first if snapshot_id == 10 else second,
    )

    result = graph_routes.diff_graph_snapshots(
        competitor_id=7,
        from_snapshot_id=10,
        to_snapshot_id=11,
    )

    assert result["summary"] == {
        "entities_added": 1,
        "entities_removed": 0,
        "relationships_added": 1,
        "relationships_removed": 0,
        "relationships_changed": 1,
    }
    assert result["relationships"]["changed"][0]["change_type"] == "strengthened"
