from datetime import datetime

import pytest

from reports import pdf_generator


def test_secure_report_path_rejects_untrusted_names_and_competitor_mismatch(
    monkeypatch,
    tmp_path,
):
    reports_root = tmp_path.resolve()
    monkeypatch.setattr(pdf_generator, "REPORTS_ROOT", reports_root)
    filename = "competitor_7_20260729_120000.pdf"
    report = reports_root / filename
    report.write_bytes(b"%PDF-1.4\n")

    assert pdf_generator.secure_report_path(
        report,
        competitor_id=7,
    ) == report
    assert pdf_generator.secure_report_path(
        report,
        competitor_id=8,
    ) is None
    assert pdf_generator.secure_report_path(
        "../../not-a-report.pdf",
        competitor_id=7,
    ) is None


def test_secure_report_path_never_uses_an_untrusted_parent(monkeypatch, tmp_path):
    reports_root = (tmp_path / "reports").resolve()
    reports_root.mkdir()
    monkeypatch.setattr(pdf_generator, "REPORTS_ROOT", reports_root)
    filename = "competitor_2_20260729_120000.pdf"
    trusted_report = reports_root / filename
    trusted_report.write_bytes(b"%PDF-1.4\n")
    attacker_path = tmp_path / "outside" / filename

    resolved = pdf_generator.secure_report_path(
        attacker_path,
        competitor_id=2,
    )

    assert resolved == trusted_report
    assert resolved.parent == reports_root


def test_secure_report_path_requires_an_existing_canonical_entry(
    monkeypatch,
    tmp_path,
):
    reports_root = tmp_path.resolve()
    monkeypatch.setattr(pdf_generator, "REPORTS_ROOT", reports_root)

    assert (
        pdf_generator.secure_report_path(
            "competitor_7_20260729_120000.pdf",
            competitor_id=7,
        )
        is None
    )
    assert (
        pdf_generator.secure_report_path(
            "competitor_07_20260729_120000.pdf",
            competitor_id=7,
        )
        is None
    )


def test_new_report_path_uses_only_typed_server_values(monkeypatch, tmp_path):
    reports_root = tmp_path.resolve()
    monkeypatch.setattr(pdf_generator, "REPORTS_ROOT", reports_root)

    report_path = pdf_generator._new_report_path(
        12,
        datetime(2026, 8, 5, 14, 30, 45),
    )

    assert report_path == reports_root / "competitor_12_20260805_143045.pdf"
    with pytest.raises(ValueError, match="positive"):
        pdf_generator._new_report_path(
            0,
            datetime(2026, 8, 5, 14, 30, 45),
        )


def test_report_styles_use_a_unique_body_style():
    styles = pdf_generator._create_styles()

    assert "ReportBody" in styles
    assert styles["ReportBody"].parent is styles["Normal"]
