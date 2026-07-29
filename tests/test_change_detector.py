from agents.ingestion.change_detector import PageChangeMonitor


def test_normalization_removes_known_timestamp_noise():
    first = "Plans updated on July 20, 2026 at 10:45 UTC © 2026 Example"
    second = "Plans updated on July 27, 2026 at 11:15 UTC © 2027 Example"

    assert PageChangeMonitor.normalize_content(first) == PageChangeMonitor.normalize_content(second)


def test_pricing_change_is_meaningful_and_cited_with_excerpts():
    previous = PageChangeMonitor.normalize_content(
        "Starter plan includes analytics and costs $19 per user each month."
    )
    current = PageChangeMonitor.normalize_content(
        "Starter plan includes analytics and automation and costs $29 per user each month."
    )

    analysis = PageChangeMonitor.analyze_change(previous, current, "https://example.com/pricing")

    assert analysis.meaningful is True
    assert analysis.change_type == "pricing"
    assert "$19" in analysis.before_excerpt
    assert "$29" in analysis.after_excerpt
    assert 0 <= analysis.similarity <= 1
    assert 0 < analysis.significance <= 1


def test_whitespace_only_change_is_not_meaningful():
    previous = PageChangeMonitor.normalize_content("One   stable\nproduct description")
    current = PageChangeMonitor.normalize_content("One stable product description")

    analysis = PageChangeMonitor.analyze_change(previous, current, "https://example.com")

    assert analysis.meaningful is False
    assert analysis.similarity == 1.0


def test_reverted_content_is_still_classified_against_latest_snapshot():
    state_a = PageChangeMonitor.normalize_content("Starter plan costs $19 per month.")
    state_b = PageChangeMonitor.normalize_content("Starter plan costs $29 per month.")

    first_change = PageChangeMonitor.analyze_change(state_a, state_b, "https://example.com/pricing")
    reverted_change = PageChangeMonitor.analyze_change(state_b, state_a, "https://example.com/pricing")

    assert first_change.meaningful is True
    assert reverted_change.meaningful is True
    assert "$29" in reverted_change.before_excerpt
    assert "$19" in reverted_change.after_excerpt
