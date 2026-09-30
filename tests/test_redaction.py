"""Focused tests for StillDone log and evidence redaction (P-04.02).

Validates:
- Deterministic, provider-neutral redaction for tokens, OAuth material, emails,
  and sensitive external identifiers.
- Redaction before storage and evidence projection.
- Detached tree guarantees (caller input never mutated).
- Idempotency: redact(redact(x)) == redact(x).
- SecretString handling without ever calling get_secret_value() or reveal().
- Safe error handling without repr() or secret plaintext leakage.
- Conservative identifier key policy (MissionId, ActionId, EvidenceId preserved).
- High-confidence text patterns (JWT, Bearer, Basic, ya29, AKIA, email, OAuth URLs).
- Bounded integration into P-03.04 capture_provider_output.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from stilldone.capture import (
    CaptureBounds,
    SanitizedProviderCapture,
    capture_provider_output,
)
from stilldone.config import SecretString
from stilldone.domain.action import ActionId
from stilldone.domain.mission import MissionId
from stilldone.evidence import EvidenceId
from stilldone.redaction import (
    REDACTED_EMAIL,
    REDACTED_IDENTIFIER,
    REDACTED_SECRET,
    RedactionMetadata,
    UnsupportedRedactionTypeError,
    normalize_key,
    redact,
    redact_log_message,
    redact_text,
    redact_with_metadata,
)

# ===========================================================================
# 1. SECRET / TOKEN VALUES UNDER MAPPING KEYS
# ===========================================================================


def test_token_under_sensitive_mapping_key_is_fully_redacted() -> None:
    """1. Token under sensitive mapping key is fully replaced with constant marker."""
    data = {"token": "secret_session_token_12345"}
    result = redact(data)
    assert result["token"] == REDACTED_SECRET
    assert "secret_session_token_12345" not in str(result)


def test_nested_token_is_redacted() -> None:
    """2. Nested token in multi-level dictionary is redacted."""
    data = {"service": {"auth": {"access_token": "ya29.nested_secret_token_abc"}}}
    result = redact(data)
    assert result["service"]["auth"]["access_token"] == REDACTED_SECRET
    assert "ya29.nested_secret_token_abc" not in str(result)


def test_sensitive_mapping_key_normalization() -> None:
    """Keys in snake_case, kebab-case, camelCase, PascalCase, and UPPERCASE are recognized."""
    cases = [
        ("client_secret", "sec1"),
        ("clientSecret", "sec2"),
        ("ClientSecret", "sec3"),
        ("CLIENT_SECRET", "sec4"),
        ("client-secret", "sec5"),
        ("client.secret", "sec6"),
        ("access_token", "sec7"),
        ("accessToken", "sec8"),
        ("AccessToken", "sec9"),
        ("api_key", "sec10"),
        ("apiKey", "sec11"),
        ("x_api_key", "sec12"),
        ("xApiKey", "sec13"),
        ("x-api-key", "sec14"),
        ("X-API-KEY", "sec15"),
        ("password", "sec16"),
        ("passwd", "sec17"),
        ("credential", "sec18"),
        ("credentials", "sec19"),
        ("session_token", "sec20"),
        ("secret_access_key", "sec21"),
        ("awsSecretAccessKey", "sec22"),
        ("aws_session_token", "sec23"),
    ]
    for key, secret_val in cases:
        result = redact({key: secret_val})
        assert result[key] == REDACTED_SECRET, f"Failed to redact key: {key}"
        assert secret_val not in str(result)


# ===========================================================================
# 2. SecretString PROTECTION
# ===========================================================================


def test_secret_string_is_redacted_without_calling_reveal() -> None:
    """3. SecretString is redacted without calling get_secret_value() or reveal()."""

    class GuardedSecretString(SecretString):
        def get_secret_value(self) -> str:
            raise AssertionError("get_secret_value() MUST NEVER be called during redaction")

        def reveal(self) -> str:
            raise AssertionError("reveal() MUST NEVER be called during redaction")

    guarded = GuardedSecretString("ultra_sensitive_secret")
    result = redact(guarded)
    assert result == REDACTED_SECRET

    # Also inside a dictionary under a non-sensitive key
    data = {"ordinary_field": guarded}
    result_dict = redact(data)
    assert result_dict["ordinary_field"] == REDACTED_SECRET

    # Also inside a sequence
    result_seq = redact([guarded])
    assert result_seq == [REDACTED_SECRET]


# ===========================================================================
# 3. CALLER INPUT IMMUTABILITY & DETACHMENT
# ===========================================================================


def test_caller_input_remains_unchanged() -> None:
    """4. Caller input is not mutated and remains isolated from post-redaction changes."""
    original: dict[str, Any] = {
        "token": "secret_abc",
        "nested": {"items": [1, 2, "user@example.com"]},
        "config": {"key": "public_val"},
    }
    original_copy = copy.deepcopy(original)

    result = redact(original)

    # 1. Original input was NOT mutated by redact()
    assert original == original_copy
    assert original["token"] == "secret_abc"
    assert original["nested"]["items"][2] == "user@example.com"

    # 2. Mutating original input after redaction does NOT affect result
    original["nested"]["items"].append("extra_item")
    original["config"]["key"] = "mutated_val"
    assert "extra_item" not in result["nested"]["items"]
    assert result["config"]["key"] == "public_val"

    # 3. Mutating result does NOT affect original input
    result["config"]["key"] = "tampered_result"
    assert original["config"]["key"] == "mutated_val"


# ===========================================================================
# 4. EMAIL ADDRESS REDACTION
# ===========================================================================


def test_email_standalone_is_redacted() -> None:
    """5. Standalone email address is redacted."""
    assert redact("user@example.com") == REDACTED_EMAIL
    assert redact("alice.smith+tag@work-domain.co.uk") == REDACTED_EMAIL


def test_email_embedded_in_text_is_redacted() -> None:
    """6. Email embedded in larger sentences/text is redacted."""
    msg = "Notification sent to bob.jones@sub.example.org regarding schedule."
    expected = f"Notification sent to {REDACTED_EMAIL} regarding schedule."
    assert redact(msg) == expected
    assert "bob.jones@sub.example.org" not in redact(msg)


def test_multiple_emails_in_text_and_structures() -> None:
    """Multiple emails across nested structures and text are all redacted."""
    data = {
        "attendees": ["alice@company.com", "bob@partner.org"],
        "summary": "Meeting with charlie@client.io and dave@vendor.net",
    }
    result = redact(data)
    assert result["attendees"] == [REDACTED_EMAIL, REDACTED_EMAIL]
    assert result["summary"] == f"Meeting with {REDACTED_EMAIL} and {REDACTED_EMAIL}"


# ===========================================================================
# 5. TEXT-LEVEL TOKEN PATTERNS
# ===========================================================================


def test_bearer_token_in_text_is_redacted() -> None:
    """7. Bearer token in text is redacted while preserving prefix."""
    text = "Authorization: Bearer ya29.a0AfH6SM_test_token_12345"
    expected = f"Authorization: Bearer {REDACTED_SECRET}"
    assert redact(text) == expected
    assert "ya29.a0AfH6SM_test_token_12345" not in redact(text)


def test_basic_auth_in_text_is_redacted() -> None:
    """Basic auth credentials in text are redacted."""
    text = "Sending header: Basic dXNlcm5hbWU6cGFzc3dvcmQ="
    expected = f"Sending header: Basic {REDACTED_SECRET}"
    assert redact(text) == expected
    assert "dXNlcm5hbWU6cGFzc3dvcmQ=" not in redact(text)


def test_jwt_token_in_text_is_redacted() -> None:
    """JWT token string in text is replaced with redaction marker."""
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    text = f"Received token: {jwt} from identity provider"
    result = redact(text)
    assert result == f"Received token: {REDACTED_SECRET} from identity provider"
    assert jwt not in result


def test_google_token_in_text_is_redacted() -> None:
    """Google access token pattern (ya29...) in text is redacted."""
    text = "Access granted with ya29.a0AfH6SM9876543210abcdef_token for drive"
    result = redact(text)
    assert result == f"Access granted with {REDACTED_SECRET} for drive"


def test_aws_access_key_id_in_text_is_redacted() -> None:
    """AWS access key ID (AKIA..., ASIA...) is replaced with [REDACTED_IDENTIFIER]."""
    text1 = "Caller identity verified with AKIAIOSFODNN7EXAMPLE key"
    assert redact(text1) == f"Caller identity verified with {REDACTED_IDENTIFIER} key"

    text2 = "Temporary session key ASIAIOSFODNN7EXAMPLE generated"
    assert redact(text2) == f"Temporary session key {REDACTED_IDENTIFIER} generated"


# ===========================================================================
# 6. OAUTH MATERIAL & CALLBACK URL SANITIZATION
# ===========================================================================


def test_oauth_callback_url_code_state_token_material_is_redacted() -> None:
    """8. OAuth callback URL code, state, and token parameters are sanitized.

    Preserves scheme, host, path, and non-sensitive parameters (scope, redirect_uri).
    """
    url = (
        "https://app.stilldone.io/oauth/callback"
        "?code=4/0AX4XfWh_auth_code_secret"
        "&state=sec_state_xyz789"
        "&scope=https://www.googleapis.com/auth/calendar"
    )
    result = redact(url)
    assert "code=4/0AX4XfWh_auth_code_secret" not in result
    assert "state=sec_state_xyz789" not in result
    assert f"code={REDACTED_SECRET}" in result
    assert f"state={REDACTED_SECRET}" in result
    assert "scope=https://www.googleapis.com/auth/calendar" in result
    assert result.startswith("https://app.stilldone.io/oauth/callback?")


def test_oauth_fragment_callback_url_sanitized() -> None:
    """OAuth implicit flow callback URL with fragment parameters is sanitized."""
    url = (
        "https://client.stilldone.app/auth"
        "#access_token=ya29.frag_token_secret"
        "&token_type=Bearer"
        "&state=frag_state_secret"
    )
    result = redact(url)
    assert "ya29.frag_token_secret" not in result
    assert "frag_state_secret" not in result
    assert f"access_token={REDACTED_SECRET}" in result
    assert f"state={REDACTED_SECRET}" in result
    assert "token_type=Bearer" in result


def test_oauth_url_embedded_in_log_text_with_punctuation() -> None:
    """OAuth URL embedded in prose with trailing punctuation is correctly sanitized."""
    log = (
        "Redirected user to "
        "http://localhost:8080/callback?code=splat123&state=state456; "
        "awaiting exchange."
    )
    result = redact(log)
    assert f"code={REDACTED_SECRET}" in result
    assert f"state={REDACTED_SECRET}" in result
    assert "splat123" not in result
    assert "state456" not in result
    assert result.endswith("; awaiting exchange.")


def test_client_secret_refresh_token_access_token_are_redacted() -> None:
    """9. Explicit OAuth secret fields are all redacted."""
    oauth_response = {
        "access_token": "ya29.access_live_123",
        "refresh_token": "1//04xyz_refresh_456",
        "client_secret": "cs_top_secret_789",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
    result = redact(oauth_response)
    assert result["access_token"] == REDACTED_SECRET
    assert result["refresh_token"] == REDACTED_SECRET
    assert result["client_secret"] == REDACTED_SECRET
    assert result["token_type"] == "Bearer"
    assert result["expires_in"] == 3600


# ===========================================================================
# 7. SENSITIVE EXTERNAL IDENTIFIERS VS DOMAIN IDENTIFIERS
# ===========================================================================


def test_sensitive_external_identifiers_under_explicit_keys_are_redacted() -> None:
    """10. Sensitive external identifiers under explicit keys are replaced."""
    data = {
        "account_id": "123456789012",
        "aws_account_id": "999888777666",
        "calendar_id": "primary_cal_xyz",
        "external_calendar_id": "c_google_calendar_888",
        "task_list_id": "list_personal_todo",
        "external_session_id": "sess_runtime_555",
        "external_resource_id": "res_cloud_777",
        "external_id": "ext_tenant_333",
        "access_key_id": "AKIA1234567890ABCDEF",
    }
    result = redact(data)
    for k in data:
        assert result[k] == REDACTED_IDENTIFIER, f"Key {k} was not redacted"
        assert data[k] not in str(result)


def test_mission_action_evidence_ids_not_blindly_redacted() -> None:
    """11. StillDone's own deterministic MissionId, ActionId, and EvidenceId are preserved."""
    m_id = MissionId("11111111-1111-1111-1111-111111111111")
    a_id = ActionId("22222222-2222-2222-2222-222222222222")
    ev_id = EvidenceId("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
    data = {
        "mission_id": m_id.value,
        "action_id": a_id.value,
        "evidence_id": ev_id.value,
        "id": "generic_item_42",
        "step_id": "step_plan_99",
        "correlation_id": "corr_internal_123",
    }
    result = redact(data)
    assert result["mission_id"] == "11111111-1111-1111-1111-111111111111"
    assert result["action_id"] == "22222222-2222-2222-2222-222222222222"
    assert result["evidence_id"] == ev_id.value
    assert result["id"] == "generic_item_42"
    assert result["step_id"] == "step_plan_99"
    assert result["correlation_id"] == "corr_internal_123"

    # Also when passed as dataclass objects
    assert redact(m_id) == "11111111-1111-1111-1111-111111111111"
    assert redact(a_id) == "22222222-2222-2222-2222-222222222222"
    assert redact(ev_id) == ev_id.value


# ===========================================================================
# 8. FAIL-CLOSED AND SECRET ERROR SAFETY
# ===========================================================================


def test_unsupported_arbitrary_object_fails_closed_without_repr_leakage() -> None:
    """12. Unsupported arbitrary object fails closed without echoing repr() or secret plaintext."""

    class SecretContainer:
        def __repr__(self) -> str:
            return "<SecretContainer secret_plaintext='SUPER_SECRET_LEAK_STRING'>"

    obj = SecretContainer()
    with pytest.raises(UnsupportedRedactionTypeError) as exc_info:
        redact(obj)

    err_msg = str(exc_info.value)
    # Proves raw repr and secret string are never present in exception
    assert "SUPER_SECRET_LEAK_STRING" not in err_msg
    assert "<SecretContainer" not in err_msg
    assert "SecretContainer" in err_msg
    assert "Unsupported object type for redaction at 'root'" in err_msg


def test_mapping_with_non_string_key_fails_closed() -> None:
    """Mappings with non-string keys fail closed with safe error message."""
    with pytest.raises(UnsupportedRedactionTypeError, match="Mapping keys must be strings"):
        redact({100: "val"})


def test_non_finite_floats_fail_closed() -> None:
    """NaN and Infinity fail closed in redaction."""
    with pytest.raises(UnsupportedRedactionTypeError, match="Non-finite float"):
        redact(float("nan"))

    with pytest.raises(UnsupportedRedactionTypeError, match="Non-finite float"):
        redact(float("inf"))


# ===========================================================================
# 9. DETERMINISM AND IDEMPOTENCY
# ===========================================================================


def test_redaction_is_deterministic() -> None:
    """13. Redaction produces identical results on identical inputs."""
    payload = {
        "token": "tok_123",
        "email": "user@example.com",
        "account_id": "acc_456",
        "public": "info",
        "nested": [{"code": "oauth_code"}],
    }
    res1 = redact(payload)
    res2 = redact(payload)
    assert res1 == res2


def test_redaction_is_idempotent() -> None:
    """14. Running redaction multiple times produces the exact same output."""
    payload = {
        "auth": {"access_token": "secret_abc"},
        "contacts": ["alice@domain.org", "bob@domain.org"],
        "calendar_id": "cal_main",
        "log": "Token Bearer ya29.test at https://cb.app?code=secret_code",
    }
    redacted_once = redact(payload)
    redacted_twice = redact(redacted_once)
    redacted_thrice = redact(redacted_twice)
    assert redacted_once == redacted_twice
    assert redacted_twice == redacted_thrice


# ===========================================================================
# 10. NO SENSITIVE PLAINTEXT IN OUTPUT OR METADATA
# ===========================================================================


def test_redacted_output_contains_no_original_sensitive_plaintext() -> None:
    """15. Redacted output tree contains zero occurrences of sensitive plaintext."""
    secrets = [
        "raw_secret_token_alpha",
        "confidential_client_secret_beta",
        "private.researcher@institution.edu",
        "AKIAIOSFODNN7EXAMPLE",
        "secret_query_code_gamma",
        "sess_sensitive_id_delta",
    ]
    payload = {
        "client_secret": secrets[1],
        "nested": {
            "account_id": secrets[5],
            "token": secrets[0],
            "note": f"Contact {secrets[2]} with key {secrets[3]}",
            "url": f"https://auth.server/cb?code={secrets[4]}&state=state123",
        },
    }
    result = redact(payload)
    result_str = str(result)
    for s in secrets:
        assert s not in result_str, f"Sensitive plaintext leaked: {s}"


def test_redaction_metadata_contains_no_sensitive_plaintext() -> None:
    """16. Redaction metadata contains counts only and zero sensitive plaintext."""
    payload = {
        "token": "secret_1",
        "user_email": "test@example.com",
        "calendar_id": "c_123",
    }
    result, meta = redact_with_metadata(payload)
    assert isinstance(meta, RedactionMetadata)
    assert meta.is_redacted is True
    assert meta.redaction_counts["secret"] == 1
    assert meta.redaction_counts["email"] == 1
    assert meta.redaction_counts["identifier"] == 1

    canonical_meta = meta.to_canonical()
    meta_str = str(canonical_meta)
    assert "secret_1" not in meta_str
    assert "test@example.com" not in meta_str
    assert "c_123" not in meta_str


# ===========================================================================
# 11. P-03 CAPTURE INTEGRATION & DIGEST SEMANTICS
# ===========================================================================


def test_p03_capture_stores_only_redacted_payload() -> None:
    """17. SanitizedProviderCapture stores only the REDACTED representation."""
    raw_provider_data = {
        "status": "success",
        "credentials": {"token": "live_provider_secret_tok"},
        "organizer": "organizer@example.com",
        "calendar_id": "cal_provider_999",
    }
    cap = capture_provider_output(raw_provider_data)

    assert isinstance(cap, SanitizedProviderCapture)
    assert "live_provider_secret_tok" not in str(cap.payload)
    assert "organizer@example.com" not in str(cap.payload)
    assert "cal_provider_999" not in str(cap.payload)

    # Check redacted values in stored payload
    assert cap.payload["credentials"] == REDACTED_SECRET
    assert cap.payload["organizer"] == REDACTED_EMAIL
    assert cap.payload["calendar_id"] == REDACTED_IDENTIFIER
    assert cap.payload["status"] == "success"


def test_p03_capture_digest_changes_according_to_redacted_stored_content_semantics() -> None:
    """18. CaptureDigest describes stored redacted content, not unredacted source.

    Different raw secrets that redact to identical stored representations yield identical digests.
    Changing stored content semantics alters the digest.
    """
    raw1 = {"token": "secret_AAA", "public": "val"}
    raw2 = {"token": "secret_BBB", "public": "val"}
    raw3 = {"token": "secret_AAA", "public": "different_val"}

    cap1 = capture_provider_output(raw1)
    cap2 = capture_provider_output(raw2)
    cap3 = capture_provider_output(raw3)

    # Stored payloads are identical: both are {"token": "[REDACTED_SECRET]", "public": "val"}
    assert cap1.payload == cap2.payload
    assert cap1.digest == cap2.digest

    # Changing stored content alters the digest
    assert cap1.payload != cap3.payload
    assert cap1.digest != cap3.digest


def test_capture_with_secret_string() -> None:
    """SecretString in provider output is cleanly captured in redacted form."""
    secret = SecretString("runtime_secret_456")
    cap = capture_provider_output({"auth": secret, "count": 1})
    assert cap.payload["auth"] == REDACTED_SECRET
    assert cap.payload["count"] == 1


# ===========================================================================
# 12. UNICODE NFC DUPLICATE KEY COLLISIONS
# ===========================================================================


def test_post_nfc_duplicate_dictionary_key_collision_fails_closed() -> None:
    """19. Post-NFC duplicate dictionary key collision fails closed with ValueError."""
    decomposed = "e\u0301"
    precomposed = "\u00e9"
    colliding = {decomposed: "val1", precomposed: "val2"}

    with pytest.raises(ValueError, match="Canonical key collision after Unicode NFC normalization"):
        redact(colliding)


# ===========================================================================
# 13. NORMAL NON-SENSITIVE DATA PRESERVATION
# ===========================================================================


def test_normal_non_sensitive_provider_data_is_preserved() -> None:
    """20. Normal non-sensitive provider data is preserved without alteration."""
    normal = {
        "status": "success",
        "count": 42,
        "ratio": 3.1415,
        "is_active": True,
        "is_deleted": False,
        "empty": None,
        "items": ["meeting_prep", "pack_lunch", "check_bus"],
        "meta": {"version": 1, "region": "us-east-1"},
    }
    result = redact(normal)
    assert result == normal


# ===========================================================================
# 14. ADVERSARIAL MIXED PAYLOAD
# ===========================================================================


def test_adversarial_mixed_payload_deep_nesting() -> None:
    """Adversarial complex payload with multiple categories and deep nesting."""

    class DummyGuarded(SecretString):
        def get_secret_value(self) -> str:
            raise AssertionError("Must not reveal")

    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiJ1c2VyMTIzIiwidXNlciI6ImFkbWluIn0."
        "4Nc7sO34234sdfsdf23423423423423423423423423"
    )

    mixed = {
        "mission_id": "m-2026-09-30-001",
        "action_id": "a-google-calendar-01",
        "evidence_id": (
            "stilldone:evidence:v1:0000000000000000000000000000000000000000000000000000000000000000"
        ),
        "calendar_id": "primary_cal_777",
        "account_id": "987654321012",
        "task_list_id": "tl_family_errands",
        "client_secret": DummyGuarded("secret_key_material"),
        "credentials": {
            "access_token": "ya29.live_google_tok",
            "session_token": DummyGuarded("sess_tok"),
            "apiKey": "api_secret_key_abc",
        },
        "log_entries": [
            f"User alice@example.com logged in with Bearer {jwt}.",
            (
                "OAuth callback received at https://auth.stilldone.app/callback"
                "?code=splat_code&state=splat_state&scope=tasks successfully."
            ),
            "Temporary key ASIAIOSFODNN7EXAMPLE used for S3 read.",
        ],
        "attendees": [
            {"name": "Alice", "email": "alice.smith@domain.co.uk"},
            {"name": "Bob", "email": "bob.builder@domain.org"},
        ],
        "normal_metrics": {
            "execution_duration_ms": 142,
            "success": True,
            "retry_count": 0,
        },
    }

    result, meta = redact_with_metadata(mixed)

    # 1. Non-sensitive StillDone IDs preserved
    assert result["mission_id"] == "m-2026-09-30-001"
    assert result["action_id"] == "a-google-calendar-01"
    assert (
        result["evidence_id"]
        == "stilldone:evidence:v1:0000000000000000000000000000000000000000000000000000000000000000"
    )

    # 2. Sensitive identifiers redacted
    assert result["calendar_id"] == REDACTED_IDENTIFIER
    assert result["account_id"] == REDACTED_IDENTIFIER
    assert result["task_list_id"] == REDACTED_IDENTIFIER

    # 3. Secrets redacted
    assert result["client_secret"] == REDACTED_SECRET
    assert result["credentials"] == REDACTED_SECRET

    # 4. Logs sanitized
    log0 = result["log_entries"][0]
    assert REDACTED_EMAIL in log0
    assert f"Bearer {REDACTED_SECRET}" in log0
    assert "alice@example.com" not in log0
    assert jwt not in log0

    log1 = result["log_entries"][1]
    assert f"code={REDACTED_SECRET}" in log1
    assert f"state={REDACTED_SECRET}" in log1
    assert "splat_code" not in log1
    assert "splat_state" not in log1
    assert "scope=tasks" in log1

    log2 = result["log_entries"][2]
    assert REDACTED_IDENTIFIER in log2
    assert "ASIAIOSFODNN7EXAMPLE" not in log2

    # 5. Attendees sanitized
    assert result["attendees"][0]["email"] == REDACTED_EMAIL
    assert result["attendees"][1]["email"] == REDACTED_EMAIL
    assert result["attendees"][0]["name"] == "Alice"
    assert result["attendees"][1]["name"] == "Bob"

    # 6. Normal metrics preserved
    assert result["normal_metrics"] == {
        "execution_duration_ms": 142,
        "success": True,
        "retry_count": 0,
    }

    # 7. Metadata recorded
    assert meta.is_redacted is True
    assert meta.redaction_counts["secret"] > 0
    assert meta.redaction_counts["email"] > 0
    assert meta.redaction_counts["identifier"] > 0


# ===========================================================================
# 15. LOGGING BOUNDARY API TESTS
# ===========================================================================


def test_redact_log_message_boundary() -> None:
    """redact_log_message provides safe pre-emission log sanitization."""
    raw_log = (
        "Provider error on account 123456789012 for user client@external.com: "
        "Bearer ya29.secret_token expired. Callback: "
        "https://api.example.com/oauth?code=bad_code&state=st_val."
    )
    sanitized = redact_log_message(raw_log)

    assert "client@external.com" not in sanitized
    assert "ya29.secret_token" not in sanitized
    assert "bad_code" not in sanitized
    assert "st_val" not in sanitized

    assert REDACTED_EMAIL in sanitized
    assert f"Bearer {REDACTED_SECRET}" in sanitized
    assert f"code={REDACTED_SECRET}" in sanitized
    assert f"state={REDACTED_SECRET}" in sanitized


def test_normalize_key_direct() -> None:
    """normalize_key normalizes casing and separators deterministically."""
    assert normalize_key("clientSecret") == "client_secret"
    assert normalize_key("CLIENT_SECRET") == "client_secret"
    assert normalize_key("x-api-key") == "x_api_key"
    assert normalize_key("task.list.id") == "task_list_id"
    assert normalize_key("OAuthToken") == "o_auth_token"


def test_redact_text_direct() -> None:
    """redact_text directly sanitizes string input."""
    raw = "Contact admin@example.com for authorization"
    assert redact_text(raw) == f"Contact {REDACTED_EMAIL} for authorization"


def test_redaction_before_structural_truncation() -> None:
    """Redaction occurs before structural truncation, ensuring no secrets cross bounds."""
    long_raw_str = "Prefix: " + "alice.secret.user@corporate-subdomain.example.com " * 10
    bounds = CaptureBounds(max_string_length=30)
    cap = capture_provider_output({"data": long_raw_str}, bounds=bounds, fail_closed=False)

    assert cap.is_truncated is True
    assert "max_string_length_exceeded" in cap.truncation_reasons
    assert "alice.secret.user" not in str(cap.payload)
    assert "corporate-subdomain" not in str(cap.payload)
    assert REDACTED_EMAIL in cap.payload["data"]
    assert len(cap.payload["data"]) == 30
