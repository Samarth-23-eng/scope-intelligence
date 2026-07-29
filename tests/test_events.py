from datetime import datetime, timedelta, timezone

from intelligence.events import EventFusionEngine, EventObservation


def observation(
    source_id: int,
    statement: str,
    *,
    event_type: str = "partnership",
    days_ago: int = 0,
) -> EventObservation:
    return EventObservation(
        source_kind="claim",
        source_id=source_id,
        event_type=event_type,
        statement=statement,
        confidence=0.8,
        verification_status="supported",
        impact_level="high",
        occurred_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        source_count=2,
    )


def test_similarity_ignores_common_words_and_case():
    score = EventFusionEngine.similarity(
        "Acme announced a cloud partnership with Contoso",
        "CONTOSO and Acme expand their cloud partnership",
    )

    assert score >= 0.5


def test_cluster_fuses_similar_observations_inside_time_window():
    engine = EventFusionEngine(7)
    clusters = engine.cluster(
        [
            observation(
                1,
                "Acme announced a cloud partnership with Contoso",
            ),
            observation(
                2,
                "Contoso and Acme expand their cloud partnership",
                days_ago=12,
            ),
        ]
    )

    assert len(clusters) == 1
    assert len(clusters[0]) == 2


def test_cluster_keeps_different_event_types_separate():
    engine = EventFusionEngine(7)
    clusters = engine.cluster(
        [
            observation(1, "Acme opens a new India engineering center"),
            observation(
                2,
                "Acme opens a new India engineering center",
                event_type="hiring",
            ),
        ]
    )

    assert len(clusters) == 2


def test_cluster_keeps_old_repeated_events_separate():
    engine = EventFusionEngine(7)
    clusters = engine.cluster(
        [
            observation(1, "Acme launches its Atlas analytics product"),
            observation(
                2,
                "Acme launches the Atlas analytics product",
                days_ago=220,
            ),
        ]
    )

    assert len(clusters) == 2


def test_impact_mapping_prioritizes_severity_and_significance():
    assert EventFusionEngine.impact_for("acquisition") == "critical"
    assert EventFusionEngine.impact_for("hiring") == "medium"
    assert (
        EventFusionEngine.impact_for("website", significance=0.75)
        == "high"
    )
    assert EventFusionEngine.impact_for("risk", severity="critical") == "critical"


def test_correlation_scoring_ignores_profile_wide_common_tokens():
    score, overlap = EventFusionEngine.correlation_score(
        "Acme launches Atlas cloud analytics",
        "Acme appoints a new finance director",
        same_type=False,
        days_apart=4,
        ignored_tokens={"acme"},
    )

    assert score < 0.1
    assert overlap == 0


def test_correlation_scoring_rewards_distinctive_shared_theme():
    score, overlap = EventFusionEngine.correlation_score(
        "Acme launches Atlas cloud analytics platform",
        "Atlas cloud analytics platform expands into India",
        same_type=True,
        days_apart=14,
        ignored_tokens={"acme"},
    )

    assert overlap >= 0.5
    assert score >= 0.5


def test_event_type_is_inferred_from_claim_language():
    assert (
        EventFusionEngine.infer_type(
            "business_move",
            "Acme acquired Contoso in October 2023.",
        )
        == "acquisition"
    )
    assert (
        EventFusionEngine.infer_type(
            "strategic_signal",
            "Acme appointed Jane Doe as Chief Product Officer.",
        )
        == "leadership"
    )


def test_claim_date_extracts_exact_and_approximate_statement_dates():
    created = datetime(2026, 7, 28, tzinfo=timezone.utc)
    exact, exact_basis = EventFusionEngine.claim_date(
        "Acme acquired Contoso on October 19, 2023.",
        None,
        created,
    )
    approximate, approximate_basis = EventFusionEngine.claim_date(
        "Acme announced the merger in February 2023.",
        None,
        created,
    )

    assert exact.date().isoformat() == "2023-10-19"
    assert exact_basis == "statement_date"
    assert approximate.date().isoformat() == "2023-02-15"
    assert approximate_basis == "statement_month"
