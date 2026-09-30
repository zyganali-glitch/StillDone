"""Deterministic provider-neutral redaction boundary for StillDone.

Enforces:
- Removal of sensitive material BEFORE it becomes durable or public evidence.
- Deterministic, idempotent, detached tree transformation (caller input is never mutated).
- Fail-closed handling for unsupported types without repr() or memory address leakage.
- Explicit semantic markers: [REDACTED_SECRET], [REDACTED_EMAIL], [REDACTED_IDENTIFIER].
- Normalized sensitive mapping key matching (robust to snake_case, kebab-case, camelCase).
- SecretString handling without ever calling get_secret_value() or reveal().
- Bounded regex matching for email addresses (standalone or embedded).
- Sanitization of OAuth callback URLs (redacting query/fragment code/state/tokens while
  preserving non-sensitive URL structure).
- High-confidence text-level pattern matching for Bearer/Basic headers, JWTs, Google tokens,
  and AWS access key IDs.
- Preservation of StillDone domain identity graphs (MissionId, ActionId, EvidenceId are never
  blindly redacted merely because they are IDs).
- Complete error message safety (sensitive values are never echoed in exceptions).
"""

from __future__ import annotations

import dataclasses
import math
import re
import unicodedata
import urllib.parse
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from stilldone.config import SecretString
from stilldone.serialization import normalize_datetime

# ===========================================================================
# Semantic Redaction Markers
# ===========================================================================

REDACTED_SECRET: str = "[REDACTED_SECRET]"
REDACTED_EMAIL: str = "[REDACTED_EMAIL]"
REDACTED_IDENTIFIER: str = "[REDACTED_IDENTIFIER]"

# ===========================================================================
# Sensitive Mapping Key Policies
# ===========================================================================

SENSITIVE_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "auth_token",
        "bearer_token",
        "oauth_token",
        "o_auth_token",
        "authorization",
        "client_secret",
        "client_assertion",
        "api_key",
        "apikey",
        "x_api_key",
        "password",
        "passwd",
        "secret",
        "secret_key",
        "private_key",
        "credential",
        "credentials",
        "session_token",
        "secret_access_key",
        "aws_secret_access_key",
        "aws_session_token",
        "aws_security_token",
        "security_token",
    }
)

SENSITIVE_IDENTIFIER_KEYS: frozenset[str] = frozenset(
    {
        "account_id",
        "aws_account_id",
        "calendar_id",
        "google_calendar_id",
        "external_calendar_id",
        "task_list_id",
        "tasklist_id",
        "google_task_list_id",
        "external_task_list_id",
        "session_id",
        "external_session_id",
        "runtime_session_id",
        "external_resource_id",
        "external_id",
        "access_key_id",
        "aws_access_key_id",
    }
)

SENSITIVE_OAUTH_PARAMS: frozenset[str] = frozenset(
    {
        "code",
        "state",
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "client_secret",
        "client_assertion",
    }
)

# ===========================================================================
# Text-Level Regex Patterns
# ===========================================================================

# Bounded email address regex: local-part @ domain.tld (requires standard TLD)
EMAIL_REGEX: re.Pattern[str] = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")

# JWT token regex: 3 base64url segments separated by dots; header starts with 'eyJ'
JWT_REGEX: re.Pattern[str] = re.compile(
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)

# Bearer token regex: standard Authorization: Bearer <token>
BEARER_REGEX: re.Pattern[str] = re.compile(r"(?i)\b(Bearer\s+)([A-Za-z0-9\-._~+/]{4,}=*)")

# Basic authentication regex: Basic <base64>
BASIC_AUTH_REGEX: re.Pattern[str] = re.compile(r"(?i)\b(Basic\s+)([A-Za-z0-9+/=]{8,})")

# Google OAuth access token prefix: ya29.<base64url>
GOOGLE_TOKEN_REGEX: re.Pattern[str] = re.compile(r"\bya29\.[A-Za-z0-9_-]{15,}\b")

# AWS Access Key ID formats (standard 20-character identifier starting with AKIA/ASIA/ABIA/ACCA)
AWS_ACCESS_KEY_REGEX: re.Pattern[str] = re.compile(r"\b(AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")

# Candidate URL regex for OAuth query/fragment scanning
URL_CANDIDATE_REGEX: re.Pattern[str] = re.compile(r"https?://[^\s\"'<>]+")


# ===========================================================================
# Exceptions
# ===========================================================================


class RedactionError(Exception):
    """Base exception for all StillDone redaction errors."""


class UnsupportedRedactionTypeError(RedactionError):
    """Raised when an unsupported object type is encountered during redaction.

    Guarantees that raw object repr() or memory addresses are never leaked.
    """


# ===========================================================================
# Metadata
# ===========================================================================


@dataclass(frozen=True)
class RedactionMetadata:
    """Deterministic metadata describing redactions performed.

    Guarantees:
    - Never contains sensitive plaintext, keys, or hashes of secrets.
    - Tracks categories and counts deterministically.
    - to_canonical() returns a lexicographically sorted dictionary.
    """

    is_redacted: bool
    redaction_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        if not isinstance(self.is_redacted, bool):
            raise TypeError(f"is_redacted must be a bool, got {type(self.is_redacted).__name__}")
        if not isinstance(self.redaction_counts, Mapping):
            raise TypeError(
                f"redaction_counts must be a Mapping, got {type(self.redaction_counts).__name__}"
            )
        for cat, count in self.redaction_counts.items():
            if not isinstance(cat, str):
                raise TypeError(f"Category key must be str, got {type(cat).__name__}")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError(f"Category count must be a non-negative integer, got {count!r}")

    def to_canonical(self) -> dict[str, Any]:
        """Return canonical JSON-compatible projection of the metadata."""
        return {
            "is_redacted": self.is_redacted,
            "redaction_counts": {
                k: self.redaction_counts[k] for k in sorted(self.redaction_counts.keys())
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_canonical()


# ===========================================================================
# Normalization Helpers
# ===========================================================================


def normalize_key(key: str) -> str:
    """Normalize a mapping key for deterministic sensitivity checking.

    Handles snake_case, kebab-case, camelCase, PascalCase, dot-separated,
    and arbitrary casing.
    Example:
    'clientSecret' -> 'client_secret'
    'CLIENT_SECRET' -> 'client_secret'
    'x-api-key' -> 'x_api_key'
    'CalendarId' -> 'calendar_id'
    'taskListId' -> 'task_list_id'
    """
    if not isinstance(key, str):
        return ""
    norm = unicodedata.normalize("NFC", key)
    # Split camelCase / PascalCase boundaries
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", norm)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    # Replace non-alphanumeric characters with underscore
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s)
    return s.strip("_").lower()


# ===========================================================================
# URL Sanitization Helper
# ===========================================================================


def _sanitize_oauth_url(url: str, counts: dict[str, int]) -> str:
    """Sanitize sensitive query and fragment parameters in an OAuth candidate URL.

    Preserves scheme, host, path, and non-sensitive parameters while replacing
    sensitive parameters (code, state, access_token, etc.) with [REDACTED_SECRET].
    """
    # Detach trailing punctuation often attached to URLs in prose
    trailing_punct = ""
    clean_url = url
    while clean_url and clean_url[-1] in ".,);:!?'\"":
        trailing_punct = clean_url[-1] + trailing_punct
        clean_url = clean_url[:-1]

    if "?" not in clean_url and "#" not in clean_url:
        return clean_url + trailing_punct

    try:
        parsed = urllib.parse.urlsplit(clean_url)
    except ValueError as err:
        raise RedactionError("Malformed URL encountered during OAuth URL redaction") from err

    modified = False

    # Process query string
    new_query_str = parsed.query
    if parsed.query:
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        new_query_pairs: list[tuple[str, str]] = []
        for k, v in query_pairs:
            norm_k = normalize_key(k)
            if norm_k in SENSITIVE_OAUTH_PARAMS:
                new_query_pairs.append((k, REDACTED_SECRET))
                if v != REDACTED_SECRET:
                    counts["secret"] += 1
                    modified = True
            else:
                new_query_pairs.append((k, v))
        new_query_str = "&".join(f"{k}={v}" for k, v in new_query_pairs)

    # Process fragment
    new_frag_str = parsed.fragment
    if parsed.fragment and "=" in parsed.fragment:
        frag_pairs = urllib.parse.parse_qsl(parsed.fragment, keep_blank_values=True)
        new_frag_pairs: list[tuple[str, str]] = []
        for k, v in frag_pairs:
            norm_k = normalize_key(k)
            if norm_k in SENSITIVE_OAUTH_PARAMS:
                new_frag_pairs.append((k, REDACTED_SECRET))
                if v != REDACTED_SECRET:
                    counts["secret"] += 1
                    modified = True
            else:
                new_frag_pairs.append((k, v))
        new_frag_str = "&".join(f"{k}={v}" for k, v in new_frag_pairs)

    if modified:
        reconstructed = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, new_query_str, new_frag_str)
        )
        return reconstructed + trailing_punct

    return clean_url + trailing_punct


# ===========================================================================
# Text Redaction Engine
# ===========================================================================


def redact_text(text: str, counts: dict[str, int] | None = None) -> str:
    """Sanitize sensitive patterns from a text string.

    Detects and replaces:
    - OAuth callback URLs with sensitive query/fragment values -> [REDACTED_SECRET]
    - JWT token strings -> [REDACTED_SECRET]
    - Bearer authorization headers -> Bearer [REDACTED_SECRET]
    - Basic authorization headers -> Basic [REDACTED_SECRET]
    - Google access tokens (ya29...) -> [REDACTED_SECRET]
    - AWS access key IDs (AKIA..., ASIA...) -> [REDACTED_IDENTIFIER]
    - Email addresses -> [REDACTED_EMAIL]

    Guarantees:
    - Deterministic and idempotent: redact_text(redact_text(s)) == redact_text(s).
    - Preserves surrounding non-sensitive text and structure.
    """
    if not isinstance(text, str):
        raise TypeError(f"redact_text requires a str, got {type(text).__name__}")

    effective_counts = counts if counts is not None else {"secret": 0, "email": 0, "identifier": 0}

    # 1. NFC normalization
    result = unicodedata.normalize("NFC", text)

    # 2. OAuth URLs with sensitive query/fragment parameters
    def _url_replacer(match: re.Match[str]) -> str:
        return _sanitize_oauth_url(match.group(0), effective_counts)

    result = URL_CANDIDATE_REGEX.sub(_url_replacer, result)

    # 3. JWT token strings
    def _jwt_replacer(match: re.Match[str]) -> str:
        effective_counts["secret"] += 1
        return REDACTED_SECRET

    result = JWT_REGEX.sub(_jwt_replacer, result)

    # 4. Bearer tokens
    def _bearer_replacer(match: re.Match[str]) -> str:
        prefix = match.group(1)
        effective_counts["secret"] += 1
        return f"{prefix}{REDACTED_SECRET}"

    result = BEARER_REGEX.sub(_bearer_replacer, result)

    # 5. Basic auth tokens
    def _basic_replacer(match: re.Match[str]) -> str:
        prefix = match.group(1)
        effective_counts["secret"] += 1
        return f"{prefix}{REDACTED_SECRET}"

    result = BASIC_AUTH_REGEX.sub(_basic_replacer, result)

    # 6. Google tokens
    def _google_token_replacer(match: re.Match[str]) -> str:
        effective_counts["secret"] += 1
        return REDACTED_SECRET

    result = GOOGLE_TOKEN_REGEX.sub(_google_token_replacer, result)

    # 7. AWS access key IDs
    def _aws_key_replacer(match: re.Match[str]) -> str:
        effective_counts["identifier"] += 1
        return REDACTED_IDENTIFIER

    result = AWS_ACCESS_KEY_REGEX.sub(_aws_key_replacer, result)

    # 8. Email addresses
    def _email_replacer(match: re.Match[str]) -> str:
        effective_counts["email"] += 1
        return REDACTED_EMAIL

    result = EMAIL_REGEX.sub(_email_replacer, result)

    return result


def redact_log_message(msg: str) -> str:
    """Convenience function to sanitize a log message string before emission.

    Guarantees no sensitive tokens, OAuth material, AWS keys, or emails enter logs.
    """
    if not isinstance(msg, str):
        msg = str(msg)
    return redact_text(msg)


# ===========================================================================
# Structural Node Redaction Engine
# ===========================================================================


def _redact_mapping(
    mapping: Mapping[Any, Any],
    *,
    path: str,
    counts: dict[str, int],
) -> dict[str, Any]:
    """Sanitize and redact mapping entries with post-NFC collision guards."""
    seen_keys: dict[str, str] = {}
    normalized_items: list[tuple[str, Any]] = []

    for k, v in mapping.items():
        if not isinstance(k, str):
            raise UnsupportedRedactionTypeError(
                f"Mapping keys must be strings for redaction at '{path}', got {type(k).__name__}"
            )
        norm_k = unicodedata.normalize("NFC", k)
        if norm_k in seen_keys:
            orig_k = seen_keys[norm_k]
            raise ValueError(
                f"Canonical key collision after Unicode NFC normalization: {k!r} "
                f"collides with {orig_k!r}"
            )
        seen_keys[norm_k] = k
        normalized_items.append((norm_k, v))

    # Deterministic lexicographical sorting
    sorted_items = sorted(normalized_items, key=lambda item: item[0])
    result: dict[str, Any] = {}

    for k, v in sorted_items:
        key_norm = normalize_key(k)
        item_path = f"{path}.{k}" if path else k

        if key_norm in SENSITIVE_SECRET_KEYS:
            counts["secret"] += 1
            result[k] = REDACTED_SECRET
        elif key_norm in SENSITIVE_IDENTIFIER_KEYS:
            counts["identifier"] += 1
            result[k] = REDACTED_IDENTIFIER
        else:
            result[k] = _redact_node(v, path=item_path, counts=counts)

    return result


def _redact_sequence(
    seq: Sequence[Any],
    *,
    path: str,
    counts: dict[str, int],
) -> list[Any]:
    """Sanitize and redact sequence items."""
    result: list[Any] = []
    for idx, item in enumerate(seq):
        item_path = f"{path}[{idx}]"
        result.append(_redact_node(item, path=item_path, counts=counts))
    return result


def _redact_node(
    val: Any,
    *,
    path: str,
    counts: dict[str, int],
) -> Any:
    """Recursively redact a node while guaranteeing zero secret plaintext leakage."""
    # 1. SecretString: Never reveal or call get_secret_value()
    if isinstance(val, SecretString):
        counts["secret"] += 1
        return REDACTED_SECRET

    # 2. Explicitly forbidden/unsupported types fail closed immediately
    if isinstance(val, type):
        raise UnsupportedRedactionTypeError(
            f"Type objects cannot be processed for redaction at '{path}'"
        )
    if isinstance(val, BaseException):
        raise UnsupportedRedactionTypeError(
            f"Exception objects ({type(val).__name__}) cannot be "
            f"processed for redaction at '{path}'"
        )
    if callable(val):
        raise UnsupportedRedactionTypeError(
            f"Callables ({type(val).__name__}) cannot be processed for redaction at '{path}'"
        )
    if isinstance(val, (bytes, bytearray, memoryview)):
        raise UnsupportedRedactionTypeError(
            f"Binary data ({type(val).__name__}) is not supported in "
            f"canonical redaction at '{path}'"
        )
    if isinstance(val, (set, frozenset)):
        raise UnsupportedRedactionTypeError(
            f"Unordered sets ({type(val).__name__}) are not supported in "
            f"canonical redaction at '{path}'"
        )
    if hasattr(val, "__next__") and not isinstance(val, (str, list, tuple, dict)):
        raise UnsupportedRedactionTypeError(
            f"Iterators ({type(val).__name__}) cannot be processed for redaction at '{path}'"
        )

    # 3. Scalar primitives
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if not math.isfinite(val):
            raise UnsupportedRedactionTypeError(f"Non-finite float is not permitted at '{path}'")
        return 0.0 if val == 0.0 else val

    # 4. Strings: text pattern redaction
    if isinstance(val, str):
        return redact_text(val, counts=counts)

    # 5. Temporal and domain primitives
    if isinstance(val, datetime):
        return normalize_datetime(val)
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, Enum):
        return _redact_node(val.value, path=f"{path}.value", counts=counts)

    # 6. Dataclasses
    if dataclasses.is_dataclass(val) and not isinstance(val, type):
        fields = dataclasses.fields(val)
        if len(fields) == 1 and fields[0].name == "value":
            inner = getattr(val, fields[0].name)
            return _redact_node(inner, path=f"{path}.value", counts=counts)
        dict_rep = {f.name: getattr(val, f.name) for f in sorted(fields, key=lambda f: f.name)}
        return _redact_mapping(dict_rep, path=path, counts=counts)

    # 7. Objects with canonical or dict projection hooks
    if hasattr(val, "to_canonical") and callable(val.to_canonical) and not isinstance(val, type):
        return _redact_node(val.to_canonical(), path=f"{path}.to_canonical()", counts=counts)
    if hasattr(val, "to_dict") and callable(val.to_dict) and not isinstance(val, type):
        return _redact_node(val.to_dict(), path=f"{path}.to_dict()", counts=counts)

    # 8. Mappings
    if isinstance(val, Mapping):
        return _redact_mapping(val, path=path, counts=counts)

    # 9. Sequences
    if isinstance(val, Sequence):
        return _redact_sequence(val, path=path, counts=counts)

    # 10. Any other arbitrary object fails closed without leaking repr()
    raise UnsupportedRedactionTypeError(
        f"Unsupported object type for redaction at '{path}': {type(val).__name__}"
    )


# ===========================================================================
# Public Redaction API
# ===========================================================================


def redact(value: Any) -> Any:
    """Recursively redact sensitive data from values, mappings, and sequences.

    Enforces:
    - SecretString -> [REDACTED_SECRET] directly without calling reveal() or get_secret_value().
    - Values under sensitive secret keys -> [REDACTED_SECRET].
    - Values under sensitive external identifier keys -> [REDACTED_IDENTIFIER].
    - Standalone or embedded email addresses -> [REDACTED_EMAIL].
    - OAuth callback URLs -> sensitive query/fragment values replaced by [REDACTED_SECRET].
    - Textual Bearer / Basic tokens, JWTs, Google tokens, AWS access key IDs -> redacted.
    - StillDone domain identity wrappers (MissionId, ActionId, EvidenceId) preserved.
    - Idempotent: redact(redact(x)) == redact(x).
    - Detached: caller input is never mutated; result is completely isolated.
    - Fail-closed: unsupported types raise UnsupportedRedactionTypeError without repr() leakage.
    - Safe errors: sensitive plaintext values are never included in exception messages.
    """
    counts: dict[str, int] = {"secret": 0, "email": 0, "identifier": 0}
    return _redact_node(value, path="root", counts=counts)


def redact_with_metadata(value: Any) -> tuple[Any, RedactionMetadata]:
    """Redact sensitive data and return both the redacted structure and deterministic metadata."""
    counts: dict[str, int] = {"secret": 0, "email": 0, "identifier": 0}
    result = _redact_node(value, path="root", counts=counts)
    total_redacted = sum(counts.values())
    meta = RedactionMetadata(
        is_redacted=total_redacted > 0,
        redaction_counts=dict(counts),
    )
    return result, meta


# Alias for callers preferring explicit redact_value naming
redact_value = redact

__all__ = [
    "REDACTED_EMAIL",
    "REDACTED_IDENTIFIER",
    "REDACTED_SECRET",
    "SENSITIVE_IDENTIFIER_KEYS",
    "SENSITIVE_OAUTH_PARAMS",
    "SENSITIVE_SECRET_KEYS",
    "RedactionError",
    "RedactionMetadata",
    "UnsupportedRedactionTypeError",
    "normalize_key",
    "redact",
    "redact_log_message",
    "redact_text",
    "redact_value",
    "redact_with_metadata",
]
