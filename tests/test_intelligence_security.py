from intelligence.security import redact_sensitive, redact_sensitive_text


def test_redact_sensitive_text_removes_common_secret_formats():
    github_token = "github_" + "pat_" + "abcdefghijklmnopqrstuvwxyz"
    openai_key = "sk" + "-" + "abcdefghijklmnop"
    value = (
        "GET https://example.test/callback?api_key=query-secret&safe=1 "
        "client_secret='assignment-secret' "
        "Bearer bearer-secret "
        f"{github_token} {openai_key}"
    )

    redacted = redact_sensitive_text(value)

    for secret in (
        "query-secret",
        "assignment-secret",
        "bearer-secret",
        github_token,
        openai_key,
    ):
        assert secret not in redacted
    assert redacted.count("[REDACTED]") == 5
    assert "safe=1" in redacted


def test_redact_sensitive_text_does_not_leak_authorization_bearer_value():
    bearer_value = "sensitive-bearer-value"

    redacted = redact_sensitive_text(f"Authorization: Bearer {bearer_value}")

    assert bearer_value not in redacted
    assert "[REDACTED]" in redacted


def test_redact_sensitive_recurses_without_changing_container_shape():
    value = {
        "api_key": "top-level-secret",
        "diagnostics": [
            "refresh_token=nested-secret",
            {"cookie": "session-secret", "status": "failed"},
        ],
        "coordinates": ("Bearer tuple-secret", 3),
        "token": "",
    }

    redacted = redact_sensitive(value)

    assert redacted == {
        "api_key": "[REDACTED]",
        "diagnostics": [
            "refresh_token=[REDACTED]",
            {"cookie": "[REDACTED]", "status": "failed"},
        ],
        "coordinates": ("Bearer [REDACTED]", 3),
        "token": "",
    }
    assert isinstance(redacted["diagnostics"], list)
    assert isinstance(redacted["coordinates"], tuple)


def test_redact_sensitive_preserves_diagnostic_code_fields():
    value = {
        "code": "youtube_api_key_required",
        "message": "Keyword discovery requires configuration.",
        "authorization_code": "oauth-secret",
    }

    assert redact_sensitive(value) == {
        "code": "youtube_api_key_required",
        "message": "Keyword discovery requires configuration.",
        "authorization_code": "[REDACTED]",
    }
