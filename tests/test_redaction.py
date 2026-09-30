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
import urllib.parse
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
    CANONICAL_REDACTION_CATEGORIES,
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
    # The scope parameter's decoded value must be semantically preserved
    # (percent-encoding of reserved chars like :// is expected with canonical URL encoding)
    parsed_result = urllib.parse.urlsplit(result)
    result_params = dict(urllib.parse.parse_qsl(parsed_result.query, keep_blank_values=True))
    assert result_params["scope"] == "https://www.googleapis.com/auth/calendar"
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


# ===========================================================================
# 16. BLOCKER 1 — NON-STRING redact_log_message REJECTION
# ===========================================================================


def test_redact_log_message_rejects_non_string_without_invoking_dunder_str() -> None:
    """Non-str input to redact_log_message fails closed without calling __str__ or __repr__.

    An arbitrary object whose __str__/__repr__ expose sentinel secret material must
    never have those methods invoked. The exception must report only the safe type name.
    """

    class TrapObject:
        """Object that explodes or leaks if __str__/__repr__ are called."""

        def __str__(self) -> str:
            raise AssertionError("__str__ MUST NEVER be called by redact_log_message")

        def __repr__(self) -> str:
            raise AssertionError("__repr__ MUST NEVER be called by redact_log_message")

    trap = TrapObject()
    with pytest.raises(TypeError, match="redact_log_message requires a str") as exc_info:
        redact_log_message(trap)  # type: ignore[arg-type]

    err_msg = str(exc_info.value)
    assert "TrapObject" in err_msg
    # Sentinel secret material never appears
    assert "MUST NEVER" not in err_msg


def test_redact_log_message_rejects_non_string_with_secret_payload() -> None:
    """Object whose __str__ returns sensitive plaintext that bypasses redaction patterns.

    This verifies that even if __str__ would produce something that looks harmless to
    the bounded patterns, the function never calls it.
    """

    class SecretLeaker:
        def __str__(self) -> str:
            return "SECRET_API_KEY_UNREDACTABLE_PATTERN_xyz789"

        def __repr__(self) -> str:
            return "<SecretLeaker: SECRET_API_KEY_UNREDACTABLE_PATTERN_xyz789>"

    leaker = SecretLeaker()
    with pytest.raises(TypeError) as exc_info:
        redact_log_message(leaker)  # type: ignore[arg-type]

    err_msg = str(exc_info.value)
    assert "SECRET_API_KEY_UNREDACTABLE_PATTERN_xyz789" not in err_msg
    assert "SecretLeaker" in err_msg


def test_redact_log_message_rejects_int_bool_none_list_dict() -> None:
    """Common non-str types are all rejected with TypeError."""
    for non_str in [42, True, None, ["msg"], {"key": "val"}, 3.14]:
        with pytest.raises(TypeError, match="redact_log_message requires a str"):
            redact_log_message(non_str)  # type: ignore[arg-type]


# ===========================================================================
# 17. BLOCKER 2 — OAUTH URL ENCODING SAFETY
# ===========================================================================


def test_encoded_ampersand_in_non_sensitive_value_stays_in_value() -> None:
    """A. Encoded ampersand/equal signs inside a non-sensitive value remain part of
    that value after sanitization and do not become new parameters."""
    url = "https://example.test/callback?scope=a%26b%3Dc&code=SECRET_CODE"
    result = redact_text(url)

    # The secret code is redacted
    assert "SECRET_CODE" not in result
    assert f"code={REDACTED_SECRET}" in result

    # The scope value must remain semantically "a&b=c" (one parameter, not split)
    parsed = urllib.parse.urlsplit(result)
    result_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    scope_values = [v for k, v in result_params if k == "scope"]
    assert len(scope_values) == 1
    assert scope_values[0] == "a&b=c"

    # No unredacted access_token or stray parameter from value splitting
    param_keys = [k for k, _ in result_params]
    assert "access_token" not in param_keys


def test_encoded_access_token_inside_non_sensitive_value_cannot_escape() -> None:
    """B. An encoded string resembling access_token=SECRET inside a non-sensitive
    parameter cannot emerge as a new unredacted access_token parameter."""
    url = "https://example.test/callback?scope=a%26access_token%3DSECRET"
    result = redact_text(url)

    # Parse the result and ensure access_token never appears as a separate param
    parsed = urllib.parse.urlsplit(result)
    result_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    param_keys = [k for k, _ in result_params]
    assert "access_token" not in param_keys

    # The scope value's decoded semantic form is preserved
    scope_values = [v for k, v in result_params if k == "scope"]
    assert len(scope_values) == 1
    assert scope_values[0] == "a&access_token=SECRET"


def test_unicode_and_reserved_chars_in_non_sensitive_query_values() -> None:
    """C. Unicode and reserved characters in non-sensitive query values preserve
    semantic round-trip behavior."""
    url = "https://example.test/callback?name=%C3%BCser%40test&code=OAUTH_CODE_XYZ"
    result = redact_text(url)

    assert "OAUTH_CODE_XYZ" not in result
    parsed = urllib.parse.urlsplit(result)
    result_params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    # "üser@test" must be semantically preserved
    assert result_params["name"] == "üser@test"


def test_duplicate_query_parameters_remain_deterministic_and_ordered() -> None:
    """D. Duplicate query parameters remain deterministic and ordered."""
    url = "https://example.test/callback?scope=read&scope=write&code=SECRET1&state=STATE1"
    result = redact_text(url)

    assert "SECRET1" not in result
    assert "STATE1" not in result

    parsed = urllib.parse.urlsplit(result)
    result_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    scope_values = [v for k, v in result_params if k == "scope"]
    assert scope_values == ["read", "write"]  # order preserved


def test_fragment_parameters_receive_safe_encoding_treatment() -> None:
    """E. Fragment parameters receive the same safe treatment."""
    url = (
        "https://example.test/auth"
        "#access_token=FRAG_SECRET&token_type=Bearer&scope=val%26extra%3Dmore"
    )
    result = redact_text(url)

    assert "FRAG_SECRET" not in result
    parsed = urllib.parse.urlsplit(result)
    frag_params = dict(urllib.parse.parse_qsl(parsed.fragment, keep_blank_values=True))
    assert frag_params["token_type"] == "Bearer"
    assert frag_params["scope"] == "val&extra=more"


def test_existing_oauth_code_state_token_redaction_still_works() -> None:
    """F. Existing OAuth code/state/token redaction tests remain green."""
    url = "https://app.example.com/cb?code=AUTH_CODE&state=STATE_VAL&scope=email"
    result = redact_text(url)
    assert "AUTH_CODE" not in result
    assert "STATE_VAL" not in result
    assert f"code={REDACTED_SECRET}" in result
    assert f"state={REDACTED_SECRET}" in result
    parsed = urllib.parse.urlsplit(result)
    result_params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    assert result_params["scope"] == "email"


def test_oauth_url_redaction_is_idempotent() -> None:
    """G. redact(redact(url)) remains identical."""
    url = "https://example.test/callback?code=SECRET_CODE&scope=a%26b%3Dc&state=STATE_VAL"
    once = redact_text(url)
    twice = redact_text(once)
    assert once == twice


# ===========================================================================
# 18. BLOCKER 3 — RedactionMetadata IMMUTABILITY
# ===========================================================================


def test_metadata_caller_alias_mutation_cannot_change_metadata() -> None:
    """A. Constructor caller-alias mutation after construction cannot affect metadata."""
    caller_dict: dict[str, int] = {"secret": 3, "email": 1, "identifier": 2}
    meta = RedactionMetadata(is_redacted=True, redaction_counts=caller_dict)

    # Mutate the caller's original dict
    caller_dict["secret"] = 999
    caller_dict["new_category"] = 42

    # Metadata is unaffected
    assert meta.redaction_counts["secret"] == 3
    assert "new_category" not in meta.redaction_counts
    assert meta.to_canonical()["redaction_counts"]["secret"] == 3


def test_metadata_redaction_counts_assignment_fails() -> None:
    """B. meta.redaction_counts[...] assignment fails."""
    meta = RedactionMetadata(
        is_redacted=True,
        redaction_counts={"secret": 1, "email": 0, "identifier": 0},
    )
    with pytest.raises(TypeError):
        meta.redaction_counts["secret"] = 999  # type: ignore[index]


def test_metadata_to_dict_to_canonical_returned_dict_mutation_does_not_affect_metadata() -> None:
    """C. to_dict()/to_canonical() returned nested dict mutation does not affect metadata."""
    meta = RedactionMetadata(
        is_redacted=True,
        redaction_counts={"secret": 5, "email": 2, "identifier": 1},
    )

    # Mutate to_dict result
    d1 = meta.to_dict()
    d1["redaction_counts"]["secret"] = 0
    d1["is_redacted"] = False

    # Mutate to_canonical result
    d2 = meta.to_canonical()
    d2["redaction_counts"]["email"] = 999

    # Metadata is unaffected by either mutation
    assert meta.is_redacted is True
    assert meta.redaction_counts["secret"] == 5
    assert meta.redaction_counts["email"] == 2

    # Fresh projection is correct
    fresh = meta.to_canonical()
    assert fresh["redaction_counts"]["secret"] == 5
    assert fresh["redaction_counts"]["email"] == 2


def test_redact_with_metadata_result_remains_deterministic() -> None:
    """D. redact_with_metadata result remains deterministic regardless of metadata mutation."""
    payload = {"token": "sec1", "email_field": "a@b.com", "calendar_id": "cal1"}
    _, meta1 = redact_with_metadata(payload)
    _, meta2 = redact_with_metadata(payload)

    assert meta1.to_canonical() == meta2.to_canonical()
    assert meta1.redaction_counts["secret"] == meta2.redaction_counts["secret"]


def test_redaction_output_unchanged_by_metadata_mutation_attempts() -> None:
    """E. Redaction output itself remains unchanged by metadata mutation attempts."""
    payload = {"token": "sec_val", "public": "safe"}
    result1, meta = redact_with_metadata(payload)

    # Attempt mutations on metadata (all should fail or be isolated)
    try:
        meta.redaction_counts["secret"] = 0  # type: ignore[index]
    except TypeError:
        pass

    d = meta.to_dict()
    d["redaction_counts"]["secret"] = 999

    # Run again — output unchanged
    result2, meta2 = redact_with_metadata(payload)
    assert result1 == result2
    assert meta2.to_canonical() == meta.to_canonical()


# ===========================================================================
# 19. URL VALUE REDACTION TESTS (BLOCKER 1 REPAIR)
# ===========================================================================


def test_url_email_in_non_sensitive_query_with_oauth_sibling_is_redacted() -> None:
    """1. Email inside non-sensitive query value + OAuth-sensitive sibling is redacted."""
    url = "https://x.test/cb?code=AUTHCODE&contact=user@example.com"
    result = redact_text(url)

    assert "AUTHCODE" not in result
    assert "user@example.com" not in result
    assert f"code={REDACTED_SECRET}" in result
    assert f"contact={REDACTED_EMAIL}" in result

    parsed = urllib.parse.urlsplit(result)
    params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    assert params["code"] == REDACTED_SECRET
    assert params["contact"] == REDACTED_EMAIL


def test_url_percent_encoded_email_decoded_redacted_safely_reencoded() -> None:
    """2. Percent-encoded email is decoded, redacted, then safely re-encoded."""
    url = "https://x.test/cb?contact=user%40example.com"
    result = redact_text(url)

    assert "user@example.com" not in result
    assert "user%40example.com" not in result
    assert "user%40EXAMPLE.COM" not in result
    assert f"contact={REDACTED_EMAIL}" in result

    parsed = urllib.parse.urlsplit(result)
    params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    assert params["contact"] == REDACTED_EMAIL


def test_url_bearer_token_in_non_sensitive_query_is_redacted() -> None:
    """3. Bearer token inside non-sensitive query value is redacted."""
    url = "https://x.test/cb?auth_hdr=Bearer%20secret-token-xyz-12345"
    result = redact_text(url)

    assert "secret-token-xyz-12345" not in result
    assert f"auth_hdr=Bearer%20{REDACTED_SECRET}" in result

    parsed = urllib.parse.urlsplit(result)
    params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    assert params["auth_hdr"] == f"Bearer {REDACTED_SECRET}"


def test_url_jwt_in_non_sensitive_query_is_redacted() -> None:
    """4. JWT inside non-sensitive query value is redacted."""
    jwt_token = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
        "dozGzN_cevyvWmsTYvA_example_signature_data"
    )
    url = f"https://x.test/cb?custom_jwt={jwt_token}"
    result = redact_text(url)

    assert jwt_token not in result
    assert f"custom_jwt={REDACTED_SECRET}" in result

    parsed = urllib.parse.urlsplit(result)
    params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    assert params["custom_jwt"] == REDACTED_SECRET


def test_url_google_token_in_non_sensitive_query_is_redacted() -> None:
    """5. Google ya29 token inside non-sensitive query value is redacted."""
    url = "https://x.test/cb?google_tok=ya29.a0AfH6SMBabc1234567890"
    result = redact_text(url)

    assert "ya29.a0AfH6SMBabc1234567890" not in result
    assert f"google_tok={REDACTED_SECRET}" in result

    parsed = urllib.parse.urlsplit(result)
    params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    assert params["google_tok"] == REDACTED_SECRET


def test_url_aws_access_key_in_non_sensitive_query_is_redacted() -> None:
    """6. AWS access-key identifier inside non-sensitive query value is redacted."""
    url = "https://x.test/cb?aws_key=AKIAIOSFODNN7EXAMPLE"
    result = redact_text(url)

    assert "AKIAIOSFODNN7EXAMPLE" not in result
    assert f"aws_key={REDACTED_IDENTIFIER}" in result

    parsed = urllib.parse.urlsplit(result)
    params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    assert params["aws_key"] == REDACTED_IDENTIFIER


def test_url_fragment_values_receive_bounded_redaction() -> None:
    """7. Same cases for fragment values where practical."""
    jwt_token = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
        "dozGzN_cevyvWmsTYvA_example_signature_data"
    )
    url = (
        f"https://x.test/auth#access_token=SECRET_TOK"
        f"&contact=user%40example.com"
        f"&auth=Bearer%20tok12345"
        f"&key=AKIAIOSFODNN7EXAMPLE"
        f"&jwt_val={jwt_token}"
    )
    result = redact_text(url)

    assert "SECRET_TOK" not in result
    assert "user@example.com" not in result
    assert "user%40example.com" not in result
    assert "tok12345" not in result
    assert "AKIAIOSFODNN7EXAMPLE" not in result
    assert jwt_token not in result

    parsed = urllib.parse.urlsplit(result)
    frag_params = dict(urllib.parse.parse_qsl(parsed.fragment, keep_blank_values=True))
    assert frag_params["access_token"] == REDACTED_SECRET
    assert frag_params["contact"] == REDACTED_EMAIL
    assert frag_params["auth"] == f"Bearer {REDACTED_SECRET}"
    assert frag_params["key"] == REDACTED_IDENTIFIER
    assert frag_params["jwt_val"] == REDACTED_SECRET


def test_url_no_sensitive_plaintext_survives_raw_or_percent_encoded() -> None:
    """8. No original plaintext survives in raw or reversible percent-encoded form."""
    targets = [
        ("user@example.com", "user%40example.com"),
        ("admin@corp.org", "admin%40corp.org"),
        ("test+label@domain.co.uk", "test%2Blabel%40domain.co.uk"),
    ]
    for raw_email, encoded_email in targets:
        url = f"https://x.test/cb?code=AUTH&recipient={encoded_email}"
        result = redact_text(url)

        # Plaintext cannot survive
        assert raw_email not in result
        assert encoded_email not in result
        assert raw_email.upper() not in result
        assert encoded_email.upper() not in result

        parsed = urllib.parse.urlsplit(result)
        params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        assert params["recipient"] == REDACTED_EMAIL


def test_url_ordinary_non_sensitive_values_preserve_round_trip() -> None:
    """9. Ordinary non-sensitive values preserve semantic round trip."""
    url = "https://x.test/cb?page=1&sort=desc&filter=active&lang=en"
    result = redact_text(url)

    assert result == url
    parsed = urllib.parse.urlsplit(result)
    params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    assert params == {"page": "1", "sort": "desc", "filter": "active", "lang": "en"}


def test_url_duplicate_parameter_order_remains_stable_under_value_redaction() -> None:
    """10. Duplicate parameter order remains stable under value redaction."""
    url = "https://x.test/cb?tag=first&tag=second&contact=user@example.com&tag=third"
    result = redact_text(url)

    parsed = urllib.parse.urlsplit(result)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    assert pairs == [
        ("tag", "first"),
        ("tag", "second"),
        ("contact", REDACTED_EMAIL),
        ("tag", "third"),
    ]


def test_url_redaction_remains_deterministic_and_idempotent() -> None:
    """11. URL redaction remains deterministic and idempotent."""
    url = (
        "https://x.test/cb?code=SECRET&contact=user%40example.com"
        "&auth=Bearer%20tok12345&key=AKIAIOSFODNN7EXAMPLE"
    )
    once = redact_text(url)
    twice = redact_text(once)
    assert once == twice

    _, meta1 = redact_with_metadata({"url": url})
    assert meta1.is_redacted is True
    assert meta1.redaction_counts["secret"] == 2  # code + Bearer
    assert meta1.redaction_counts["email"] == 1  # contact
    assert meta1.redaction_counts["identifier"] == 1  # key

    # Redacting already-redacted output increments nothing and marks is_redacted False
    _, meta2 = redact_with_metadata({"url": once})
    assert meta2.is_redacted is False
    assert meta2.redaction_counts["secret"] == 0
    assert meta2.redaction_counts["email"] == 0
    assert meta2.redaction_counts["identifier"] == 0


# ===========================================================================
# 20. REDACTION METADATA CANONICAL CATEGORIES & INVARIANTS (BLOCKER 2 REPAIR)
# ===========================================================================


def test_metadata_unknown_category_fails_closed() -> None:
    """12. Unknown category fails closed."""
    with pytest.raises(ValueError, match="Unknown redaction category 'made_up_category'"):
        RedactionMetadata(
            is_redacted=True,
            redaction_counts={"secret": 1, "made_up_category": 999},
        )
    with pytest.raises(ValueError, match="Unknown redaction category 'invalid'"):
        RedactionMetadata(
            is_redacted=True,
            redaction_counts={"invalid": 1},
        )


def test_metadata_invalid_count_types_fail_closed() -> None:
    """13. Negative/bool/non-int counts remain rejected."""
    # Negative count
    with pytest.raises(ValueError, match="non-negative integer"):
        RedactionMetadata(is_redacted=True, redaction_counts={"secret": -1})

    # Boolean count (bool is a subclass of int in Python)
    with pytest.raises(ValueError, match="non-negative integer"):
        RedactionMetadata(is_redacted=True, redaction_counts={"secret": True})
    with pytest.raises(ValueError, match="non-negative integer"):
        RedactionMetadata(is_redacted=False, redaction_counts={"secret": False})

    # Float count
    with pytest.raises(ValueError, match="non-negative integer"):
        RedactionMetadata(is_redacted=True, redaction_counts={"secret": 1.5})  # type: ignore[dict-item]

    # Non-int string count
    with pytest.raises(ValueError, match="non-negative integer"):
        RedactionMetadata(is_redacted=True, redaction_counts={"secret": "one"})  # type: ignore[dict-item]

    # Non-string category key
    with pytest.raises(TypeError, match="Category key must be str"):
        RedactionMetadata(is_redacted=True, redaction_counts={123: 1})  # type: ignore[dict-item]


def test_metadata_canonical_shape_deterministically_populates_all_three_categories() -> None:
    """14. Canonical category shape is deterministic (all 3 categories populated)."""
    # Only "secret" provided; "email" and "identifier" populated with 0
    meta = RedactionMetadata(is_redacted=True, redaction_counts={"secret": 2})

    assert set(meta.redaction_counts.keys()) == CANONICAL_REDACTION_CATEGORIES
    assert meta.redaction_counts["secret"] == 2
    assert meta.redaction_counts["email"] == 0
    assert meta.redaction_counts["identifier"] == 0

    # to_canonical() orders keys lexicographically
    canonical = meta.to_canonical()
    assert list(canonical["redaction_counts"].keys()) == ["email", "identifier", "secret"]
    assert canonical["redaction_counts"] == {"email": 0, "identifier": 0, "secret": 2}


def test_metadata_contradictory_is_redacted_state_fails_closed() -> None:
    """15. Contradictory is_redacted/count state fails closed."""
    # is_redacted=False but positive count
    with pytest.raises(
        ValueError, match=r"is_redacted must be True when total redaction count is 1"
    ):
        RedactionMetadata(is_redacted=False, redaction_counts={"secret": 1})

    # is_redacted=True but all counts are zero
    with pytest.raises(
        ValueError, match=r"is_redacted must be False when total redaction count is 0"
    ):
        RedactionMetadata(
            is_redacted=True,
            redaction_counts={"secret": 0, "email": 0, "identifier": 0},
        )

    # is_redacted=True with empty dict (all defaulted to 0)
    with pytest.raises(
        ValueError, match=r"is_redacted must be False when total redaction count is 0"
    ):
        RedactionMetadata(is_redacted=True, redaction_counts={})


def test_metadata_zero_counts_strictly_requires_is_redacted_false() -> None:
    """16. Zero counts <-> is_redacted False."""
    meta = RedactionMetadata(
        is_redacted=False,
        redaction_counts={"secret": 0, "email": 0, "identifier": 0},
    )
    assert meta.is_redacted is False
    assert sum(meta.redaction_counts.values()) == 0

    # Omitted categories also default to 0 and allow is_redacted=False
    meta_empty = RedactionMetadata(is_redacted=False, redaction_counts={})
    assert meta_empty.is_redacted is False
    assert sum(meta_empty.redaction_counts.values()) == 0


def test_metadata_positive_counts_strictly_requires_is_redacted_true() -> None:
    """17. Positive total <-> is_redacted True."""
    for cat in CANONICAL_REDACTION_CATEGORIES:
        meta = RedactionMetadata(is_redacted=True, redaction_counts={cat: 1})
        assert meta.is_redacted is True
        assert meta.redaction_counts[cat] == 1
        assert sum(meta.redaction_counts.values()) == 1


def test_canonical_redaction_categories_is_frozen_and_exported() -> None:
    """18. Canonical category set is immutable, exact, and exported."""
    assert CANONICAL_REDACTION_CATEGORIES == frozenset({"secret", "email", "identifier"})
    assert isinstance(CANONICAL_REDACTION_CATEGORIES, frozenset)


# ===========================================================================
# 21. URL PARAMETER KEY REDACTION TESTS (BLOCKER REPAIR)
# ===========================================================================


def test_url_raw_email_in_parameter_name_with_oauth_sibling_is_redacted() -> None:
    """A. Raw email in a query parameter name with an OAuth sibling is redacted."""
    url = "https://x.test/cb?code=AUTH&user@example.com=x"
    result = redact_text(url)

    # Email cannot survive in raw, lowercase percent-encoded, or uppercase percent-encoded form
    assert "AUTH" not in result
    assert "user@example.com" not in result
    assert "user%40example.com" not in result
    assert "user%40EXAMPLE.COM" not in result
    assert f"code={REDACTED_SECRET}" in result
    assert f"{REDACTED_EMAIL}=x" in result

    parsed = urllib.parse.urlsplit(result)
    params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    assert params["code"] == REDACTED_SECRET
    assert params[REDACTED_EMAIL] == "x"


def test_url_percent_encoded_email_in_parameter_name_is_decoded_and_redacted() -> None:
    """B. Percent-encoded email in query parameter name is decoded, redacted, and reconstructed."""
    # Lowercase percent-encoded
    url1 = "https://x.test/cb?user%40example.com=x"
    result1 = redact_text(url1)
    assert "user@example.com" not in result1
    assert "user%40example.com" not in result1
    assert result1 == f"https://x.test/cb?{REDACTED_EMAIL}=x"
    params1 = dict(
        urllib.parse.parse_qsl(urllib.parse.urlsplit(result1).query, keep_blank_values=True)
    )
    assert params1[REDACTED_EMAIL] == "x"

    # Uppercase percent-encoded
    url2 = "https://x.test/cb?user%40EXAMPLE.COM=x"
    result2 = redact_text(url2)
    assert "user@example.com" not in result2
    assert "user%40example.com" not in result2
    assert "EXAMPLE.COM" not in result2
    assert result2 == f"https://x.test/cb?{REDACTED_EMAIL}=x"


def test_url_fragment_parameter_names_receive_bounded_key_redaction() -> None:
    """C. Same behavior for fragment parameter names."""
    url = "https://x.test/auth#code=AUTH&user%40example.com=x&AKIAIOSFODNN7EXAMPLE=key_val"
    result = redact_text(url)

    assert "AUTH" not in result
    assert "user@example.com" not in result
    assert "user%40example.com" not in result
    assert "AKIAIOSFODNN7EXAMPLE" not in result

    parsed = urllib.parse.urlsplit(result)
    frag_params = dict(urllib.parse.parse_qsl(parsed.fragment, keep_blank_values=True))
    assert frag_params["code"] == REDACTED_SECRET
    assert frag_params[REDACTED_EMAIL] == "x"
    assert frag_params[REDACTED_IDENTIFIER] == "key_val"


def test_url_bounded_token_patterns_in_parameter_names_are_redacted() -> None:
    """D. Bounded token-patterns in parameter names are redacted before URL encoding."""
    # AWS access key in key name
    url1 = "https://x.test/cb?code=AUTH&AKIAIOSFODNN7EXAMPLE=val"
    result1 = redact_text(url1)
    assert "AKIAIOSFODNN7EXAMPLE" not in result1
    parsed1 = urllib.parse.parse_qsl(urllib.parse.urlsplit(result1).query, keep_blank_values=True)
    assert parsed1 == [("code", REDACTED_SECRET), (REDACTED_IDENTIFIER, "val")]

    # JWT in key name
    jwt_token = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
        "dozGzN_cevyvWmsTYvA_example_signature_data"
    )
    url2 = f"https://x.test/cb?{jwt_token}=val"
    result2 = redact_text(url2)
    assert jwt_token not in result2
    parsed2 = urllib.parse.parse_qsl(urllib.parse.urlsplit(result2).query, keep_blank_values=True)
    assert parsed2 == [(REDACTED_SECRET, "val")]

    # Google token in key name
    url3 = "https://x.test/cb?ya29.a0AfH6SMBabc1234567890=val"
    result3 = redact_text(url3)
    assert "ya29.a0AfH6SMBabc1234567890" not in result3
    parsed3 = urllib.parse.parse_qsl(urllib.parse.urlsplit(result3).query, keep_blank_values=True)
    assert parsed3 == [(REDACTED_SECRET, "val")]

    # Bearer in key name
    url4 = "https://x.test/cb?Bearer%20secrettoken123=val"
    result4 = redact_text(url4)
    assert "secrettoken123" not in result4
    parsed4 = urllib.parse.parse_qsl(urllib.parse.urlsplit(result4).query, keep_blank_values=True)
    assert parsed4 == [(f"Bearer {REDACTED_SECRET}", "val")]


def test_url_ordinary_non_sensitive_parameter_names_remain_unchanged() -> None:
    """E. Ordinary non-sensitive parameter names remain semantically unchanged."""
    url = "https://x.test/cb?page=1&sort=desc&filter=active&category=books"
    result = redact_text(url)
    assert result == url
    parsed = dict(
        urllib.parse.parse_qsl(urllib.parse.urlsplit(result).query, keep_blank_values=True)
    )
    assert parsed == {"page": "1", "sort": "desc", "filter": "active", "category": "books"}


def test_url_sensitive_oauth_parameter_names_retain_structural_keys_with_redacted_value() -> None:
    """F. Sensitive OAuth parameter names retain structural key name while value is replaced."""
    url = (
        "https://x.test/cb?code=AUTH_CODE&state=STATE_VAL"
        "&access_token=ACC_TOK&refresh_token=REF_TOK"
    )
    result = redact_text(url)
    assert "AUTH_CODE" not in result
    assert "STATE_VAL" not in result
    assert "ACC_TOK" not in result
    assert "REF_TOK" not in result
    parsed = urllib.parse.parse_qsl(urllib.parse.urlsplit(result).query, keep_blank_values=True)
    assert parsed == [
        ("code", REDACTED_SECRET),
        ("state", REDACTED_SECRET),
        ("access_token", REDACTED_SECRET),
        ("refresh_token", REDACTED_SECRET),
    ]


def test_url_duplicate_parameter_order_remains_stable_with_key_redaction() -> None:
    """G. Duplicate parameter ordering remains stable when parameter keys are redacted."""
    url = "https://x.test/cb?tag=a&user@example.com=val1&tag=b&user@example.com=val2&tag=c"
    result = redact_text(url)
    parsed = urllib.parse.parse_qsl(urllib.parse.urlsplit(result).query, keep_blank_values=True)
    assert parsed == [
        ("tag", "a"),
        (REDACTED_EMAIL, "val1"),
        ("tag", "b"),
        (REDACTED_EMAIL, "val2"),
        ("tag", "c"),
    ]


def test_url_key_redaction_remains_strictly_idempotent() -> None:
    """H. redact(redact(url)) remains exactly idempotent with key redaction."""
    url = "https://x.test/cb?code=AUTH&user@example.com=x&AKIAIOSFODNN7EXAMPLE=val"
    once = redact_text(url)
    twice = redact_text(once)
    assert once == twice

    _, meta1 = redact_with_metadata({"url": url})
    assert meta1.is_redacted is True
    assert meta1.redaction_counts["secret"] == 1  # code
    assert meta1.redaction_counts["email"] == 1  # user@example.com
    assert meta1.redaction_counts["identifier"] == 1  # AKIA...

    _, meta2 = redact_with_metadata({"url": once})
    assert meta2.is_redacted is False
    assert meta2.redaction_counts == {"email": 0, "identifier": 0, "secret": 0}
