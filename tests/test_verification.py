from datetime import datetime, timedelta, timezone

from intelligence.verification import ClaimVerificationEngine


def evidence(
    domain: str,
    *,
    stance: str = "supports",
    confidence: float = 0.9,
    source_type: str = "news_article",
):
    return {
        "source_url": f"https://{domain}/report",
        "source_type": source_type,
        "stance": stance,
        "confidence": confidence,
        "observed_at": datetime.now(timezone.utc),
    }


def test_claim_confirmation_requires_independent_sources():
    claim = {
        "id": 1,
        "confidence": 0.9,
        "status": "supported",
        "metadata": {},
        "created_at": datetime.now(timezone.utc),
    }
    rows = [
        evidence("official.example", source_type="first_party_website"),
        evidence("reuters.example"),
        evidence("reuters.example"),
    ]
    profiles = {
        ("official.example", "first_party_website"): {"reliability": 0.95},
        ("reuters.example", "news_article"): {"reliability": 0.9},
    }

    score = ClaimVerificationEngine.score_claim(claim, rows, profiles)

    assert score["independent_sources"] == 2
    assert score["status"] == "confirmed"
    assert score["final_confidence"] >= 0.78


def test_strong_contradiction_disputes_claim():
    claim = {
        "id": 2,
        "confidence": 0.8,
        "status": "supported",
        "metadata": {},
        "created_at": datetime.now(timezone.utc),
    }
    rows = [
        evidence("company.example", source_type="first_party_website"),
        evidence(
            "regulator.gov",
            stance="contradicts",
            confidence=0.95,
            source_type="government",
        ),
    ]
    profiles = {
        ("company.example", "first_party_website"): {"reliability": 0.95},
        ("regulator.gov", "government"): {"reliability": 0.96},
    }

    score = ClaimVerificationEngine.score_claim(claim, rows, profiles)

    assert score["status"] == "disputed"
    assert "contradictory_evidence" in score["risk_flags"]


def test_old_single_source_claim_enters_review_queue():
    old = datetime.now(timezone.utc) - timedelta(days=400)
    claim = {
        "id": 3,
        "confidence": 0.65,
        "status": "supported",
        "metadata": {},
        "created_at": old,
    }
    row = evidence("blog.example", confidence=0.6)
    row["observed_at"] = old

    score = ClaimVerificationEngine.score_claim(
        claim,
        [row],
        {("blog.example", "news_article"): {"reliability": 0.65}},
    )

    assert score["status"] == "stale"
    assert "single_source" in score["risk_flags"]
    assert "stale_evidence" in score["risk_flags"]


def test_human_review_lock_preserves_operator_decision():
    claim = {
        "id": 4,
        "confidence": 0.4,
        "status": "confirmed",
        "metadata": {"human_review_locked": True, "model_confidence": 0.4},
        "created_at": datetime.now(timezone.utc),
    }

    score = ClaimVerificationEngine.score_claim(claim, [], {})

    assert score["status"] == "confirmed"
    assert "human_reviewed" in score["risk_flags"]
