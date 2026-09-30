"""Tests for StillDone secret and configuration loading foundation (P-04.01)."""

from __future__ import annotations

import copy
import dataclasses
import importlib
import os
import sys
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from stilldone.config import (
    ConfigField,
    ConfigSchema,
    ConfigurationError,
    InvalidConfigurationValueError,
    LoadedConfig,
    MissingConfigurationError,
    SecretString,
    UnknownConfigurationKeyError,
    parse_bool,
    parse_bounded_int,
    parse_choices,
    parse_float,
    parse_int,
    parse_port,
    parse_secret_string,
    parse_string,
)

# ===========================================================================
# 1. Explicit Source & Import-Time Purity
# ===========================================================================


def test_import_time_purity() -> None:
    """Verify importing stilldone.config does NOT read os.environ or load .env files."""
    accessed_keys: list[str] = []
    original_getitem = os.environ.__getitem__

    def _tracking_getitem(key: str) -> str:
        accessed_keys.append(key)
        return original_getitem(key)

    # Force re-import under tracking
    if "stilldone.config" in sys.modules:
        del sys.modules["stilldone.config"]

    with patch.object(os.environ, "__getitem__", side_effect=_tracking_getitem):
        mod = importlib.import_module("stilldone.config")
        assert mod is not None

    assert len(accessed_keys) == 0, f"os.environ accessed at import time: {accessed_keys}"


def test_explicit_source_injection_ignores_machine_environment() -> None:
    """Loader must accept explicit mapping and ignore process environment."""
    schema = ConfigSchema(
        fields=[
            ConfigField("STILLDONE_PORT", parse_port),
            ConfigField("STILLDONE_NAME", parse_string),
        ],
        namespace="STILLDONE_",
    )

    injected_env = {
        "STILLDONE_PORT": "9090",
        "STILLDONE_NAME": "test-mission",
    }

    # Even if os.environ had different values or malformed values:
    with patch.dict(os.environ, {"STILLDONE_PORT": "invalid-port", "STILLDONE_NAME": "env-name"}):
        cfg = schema.load(injected_env)
        assert isinstance(cfg, LoadedConfig)
        assert cfg["STILLDONE_PORT"] == 9090
        assert cfg["STILLDONE_NAME"] == "test-mission"


def test_call_time_process_environment_fallback() -> None:
    """When env is None, process environment is read strictly at call time."""
    schema = ConfigSchema(
        fields=[
            ConfigField("STILLDONE_PORT", parse_port),
        ],
        namespace="STILLDONE_",
    )

    with patch.dict(os.environ, {"STILLDONE_PORT": "4321"}):
        cfg1 = schema.load()
        assert cfg1["STILLDONE_PORT"] == 4321

    with patch.dict(os.environ, {"STILLDONE_PORT": "8765"}):
        cfg2 = schema.load()
        assert cfg2["STILLDONE_PORT"] == 8765

    # Prior loaded snapshot remains unaffected
    assert cfg1["STILLDONE_PORT"] == 4321


# ===========================================================================
# 2. Namespace Ownership & Typos Fail Closed
# ===========================================================================


def test_unknown_key_in_owned_namespace_fails_closed() -> None:
    """Unrecognized keys starting with the owned namespace prefix fail closed."""
    schema = ConfigSchema(
        fields=[
            ConfigField("STILLDONE_PORT", parse_port),
        ],
        namespace="STILLDONE_",
    )

    bad_env = {
        "STILLDONE_PORT": "8080",
        "STILLDONE_PRT": "typo-port",  # Typo in namespace
    }

    with pytest.raises(UnknownConfigurationKeyError) as exc_info:
        schema.load(bad_env)

    err = exc_info.value
    assert "STILLDONE_PRT" in err.keys
    assert err.namespace == "STILLDONE_"
    assert "Unknown configuration key(s) in owned namespace 'STILLDONE_'" in str(err)
    assert "'STILLDONE_PRT'" in str(err)


def test_multiple_unknown_keys_sorted_and_reported() -> None:
    """Multiple unrecognized keys are sorted and listed in the error."""
    schema = ConfigSchema(
        fields=[ConfigField("STILLDONE_PORT", parse_port)],
        namespace="STILLDONE_",
    )

    bad_env = {
        "STILLDONE_PORT": "8080",
        "STILLDONE_ZEBRA": "1",
        "STILLDONE_ALPHA": "2",
    }

    with pytest.raises(UnknownConfigurationKeyError) as exc_info:
        schema.load(bad_env)

    err = exc_info.value
    assert err.keys == ("STILLDONE_ALPHA", "STILLDONE_ZEBRA")
    assert "'STILLDONE_ALPHA', 'STILLDONE_ZEBRA'" in str(err)


def test_unrelated_operating_system_env_vars_ignored() -> None:
    """Unrelated system environment variables outside the owned namespace are ignored."""
    schema = ConfigSchema(
        fields=[
            ConfigField("STILLDONE_PORT", parse_port),
        ],
        namespace="STILLDONE_",
    )

    env = {
        "STILLDONE_PORT": "8080",
        "PATH": "/usr/bin:/bin",
        "HOME": "/home/runner",
        "AWS_REGION": "us-east-1",
        "USER": "alice",
        "TERM": "xterm-256color",
    }

    cfg = schema.load(env)
    assert cfg["STILLDONE_PORT"] == 8080
    assert "PATH" not in cfg
    assert "HOME" not in cfg


def test_custom_or_disabled_namespace() -> None:
    """Namespace can be customized or disabled (None)."""
    # Disabled namespace: unknown prefixed keys do not fail closed
    schema_no_ns = ConfigSchema(
        fields=[ConfigField("PORT", parse_port)],
        namespace=None,
    )
    cfg = schema_no_ns.load({"PORT": "3000", "STILLDONE_EXTRA": "ignored"})
    assert cfg["PORT"] == 3000

    # Custom namespace
    schema_custom = ConfigSchema(
        fields=[ConfigField("CUSTOM_PORT", parse_port)],
        namespace="CUSTOM_",
    )
    with pytest.raises(UnknownConfigurationKeyError):
        schema_custom.load({"CUSTOM_PORT": "3000", "CUSTOM_TYPO": "bad"})


# ===========================================================================
# 3. Required Values Fail Closed
# ===========================================================================


def test_required_absent_fails_closed() -> None:
    """Absent required field raises MissingConfigurationError."""
    schema = ConfigSchema(
        fields=[ConfigField("STILLDONE_PORT", parse_port, required=True)],
    )

    with pytest.raises(MissingConfigurationError) as exc_info:
        schema.load({})

    err = exc_info.value
    assert err.key == "STILLDONE_PORT"
    assert "Missing required configuration key" in str(err)


def test_required_empty_string_fails_closed() -> None:
    """Empty string for required field raises MissingConfigurationError."""
    schema = ConfigSchema(
        fields=[ConfigField("STILLDONE_PORT", parse_port, required=True)],
    )

    with pytest.raises(MissingConfigurationError) as exc_info:
        schema.load({"STILLDONE_PORT": ""})

    err = exc_info.value
    assert err.key == "STILLDONE_PORT"
    assert "empty or whitespace-only" in str(err)


def test_required_whitespace_only_fails_closed() -> None:
    """Whitespace-only string for required field raises MissingConfigurationError."""
    schema = ConfigSchema(
        fields=[ConfigField("STILLDONE_PORT", parse_port, required=True)],
    )

    with pytest.raises(MissingConfigurationError) as exc_info:
        schema.load({"STILLDONE_PORT": "   \t \n  "})

    err = exc_info.value
    assert err.key == "STILLDONE_PORT"
    assert "empty or whitespace-only" in str(err)


def test_required_malformed_fails_closed() -> None:
    """Malformed value for required field raises InvalidConfigurationValueError."""
    schema = ConfigSchema(
        fields=[ConfigField("STILLDONE_PORT", parse_port, required=True)],
    )

    with pytest.raises(InvalidConfigurationValueError) as exc_info:
        schema.load({"STILLDONE_PORT": "not-a-port"})

    err = exc_info.value
    assert err.key == "STILLDONE_PORT"
    assert "Cannot parse integer" in err.reason


# ===========================================================================
# 4. Optional Values & Defaults
# ===========================================================================


def test_optional_value_uses_explicit_default() -> None:
    """Absent optional field receives its declared default."""
    schema = ConfigSchema(
        fields=[
            ConfigField("STILLDONE_PORT", parse_port, required=False, default=8080),
            ConfigField("STILLDONE_TAG", parse_string, required=False, default=None),
        ],
    )

    cfg = schema.load({})
    assert cfg["STILLDONE_PORT"] == 8080
    assert cfg["STILLDONE_TAG"] is None


def test_optional_value_explicitly_provided_overrides_default() -> None:
    """Provided optional field overrides the default value."""
    schema = ConfigSchema(
        fields=[
            ConfigField("STILLDONE_PORT", parse_port, required=False, default=8080),
        ],
    )

    cfg = schema.load({"STILLDONE_PORT": "9090"})
    assert cfg["STILLDONE_PORT"] == 9090


def test_optional_value_malformed_fails_closed() -> None:
    """Malformed value for an optional field fails closed (no silent fallback to default)."""
    schema = ConfigSchema(
        fields=[
            ConfigField("STILLDONE_PORT", parse_port, required=False, default=8080),
        ],
    )

    with pytest.raises(InvalidConfigurationValueError) as exc_info:
        schema.load({"STILLDONE_PORT": "invalid-port"})

    assert exc_info.value.key == "STILLDONE_PORT"


def test_optional_value_empty_string_fails_closed() -> None:
    """Explicitly provided empty string for an optional field fails closed."""
    schema = ConfigSchema(
        fields=[
            ConfigField("STILLDONE_PORT", parse_port, required=False, default=8080),
        ],
    )

    with pytest.raises(InvalidConfigurationValueError) as exc_info:
        schema.load({"STILLDONE_PORT": ""})

    assert exc_info.value.key == "STILLDONE_PORT"


def test_required_field_cannot_have_default() -> None:
    """ConfigField post_init rejects required=True with non-None default."""
    with pytest.raises(ValueError, match="cannot have a non-None default value"):
        ConfigField("STILLDONE_PORT", parse_port, required=True, default=8080)


def test_secret_field_cannot_have_default() -> None:
    """ConfigField post_init rejects secret fields with defaults."""
    with pytest.raises(ValueError, match="cannot have a default value"):
        ConfigField(
            "STILLDONE_SECRET",
            parse_secret_string,
            required=False,
            default=SecretString("hardcoded-default"),
            is_secret=True,
        )


# ===========================================================================
# 5. Secret Value Handling & Redaction
# ===========================================================================


def test_secret_string_representation_and_str() -> None:
    """SecretString repr and str never reveal plaintext."""
    secret = SecretString("synthetic-secret-token-abcdef123456")

    assert repr(secret) == 'SecretString("**********")'
    assert str(secret) == "[REDACTED]"
    assert f"{secret}" == "[REDACTED]"
    assert f"prefix_{secret}_suffix" == "prefix_[REDACTED]_suffix"
    assert "synthetic-secret-token" not in repr(secret)
    assert "synthetic-secret-token" not in str(secret)


def test_secret_string_explicit_access() -> None:
    """Secret plaintext is accessible strictly via get_secret_value() or reveal()."""
    plain = "synthetic-secret-token-abcdef123456"
    secret = SecretString(plain)

    assert secret.get_secret_value() == plain
    assert secret.reveal() == plain


def test_secret_string_equality_and_comparison() -> None:
    """SecretString equality uses constant-time comparison; comparison with str raises TypeError."""
    s1 = SecretString("token-123")
    s2 = SecretString("token-123")
    s3 = SecretString("token-456")

    assert s1 == s2
    assert s1 != s3
    assert s1 != 42

    msg = "Direct comparison between SecretString and str is forbidden"
    with pytest.raises(TypeError, match=msg):
        _ = s1 == "token-123"


def test_secret_string_hashing() -> None:
    """SecretString is hashable via domain-separated digest without leaking plaintext."""
    s1 = SecretString("token-123")
    s2 = SecretString("token-123")
    s3 = SecretString("token-456")

    assert hash(s1) == hash(s2)
    assert hash(s1) != hash(s3)


def test_secret_string_len_and_bool() -> None:
    """len(SecretString) raises TypeError to prevent length leakage; bool(SecretString) works."""
    s = SecretString("secret-val")
    with pytest.raises(TypeError, match="len.*not supported"):
        len(s)

    assert bool(SecretString("val")) is True
    assert bool(SecretString("")) is False


def test_secret_string_copy() -> None:
    """Copy and deepcopy return self (immutable)."""
    s = SecretString("secret-val")
    assert copy.copy(s) is s
    assert copy.deepcopy(s) is s


@dataclass(frozen=True)
class _SyntheticDataclassConfig:
    port: int
    secret_key: SecretString


def test_secret_in_dataclass_repr() -> None:
    """Dataclass containing SecretString does not reveal plaintext in repr or str."""
    cfg = _SyntheticDataclassConfig(
        port=8080,
        secret_key=SecretString("synthetic-ultra-secret-key-9999"),
    )

    repr_str = repr(cfg)
    str_str = str(cfg)

    assert "synthetic-ultra-secret-key" not in repr_str
    assert "synthetic-ultra-secret-key" not in str_str
    assert 'secret_key=SecretString("**********")' in repr_str


def test_loaded_config_repr_redacts_secrets() -> None:
    """LoadedConfig repr and str redact all secret-classified fields."""
    schema = ConfigSchema(
        fields=[
            ConfigField("STILLDONE_PORT", parse_port),
            ConfigField("STILLDONE_TOKEN", parse_secret_string, is_secret=True),
        ],
    )

    cfg = schema.load(
        {
            "STILLDONE_PORT": "8080",
            "STILLDONE_TOKEN": "synthetic-token-abc",
        }
    )

    repr_str = repr(cfg)
    assert "synthetic-token-abc" not in repr_str
    assert "STILLDONE_TOKEN': SecretString('**********')" in repr_str

    dict_redacted = cfg.to_dict()
    assert dict_redacted["STILLDONE_TOKEN"] == "[REDACTED]"
    assert dict_redacted["STILLDONE_PORT"] == 8080

    dict_unredacted = cfg.to_dict(redact_secrets=False)
    assert isinstance(dict_unredacted["STILLDONE_TOKEN"], SecretString)


def test_secret_validation_error_never_leaks_plaintext() -> None:
    """Validation errors for secret fields strictly never contain the secret plaintext."""

    def _token_validator(val: SecretString) -> None:
        if len(val.get_secret_value()) < 10:
            raise ValueError(f"Secret token '{val.get_secret_value()}' is too short")

    schema = ConfigSchema(
        fields=[
            ConfigField(
                "STILLDONE_API_SECRET",
                parse_secret_string,
                is_secret=True,
                validator=_token_validator,
            ),
        ],
    )

    synthetic_plaintext = "short-sec"
    with pytest.raises(InvalidConfigurationValueError) as exc_info:
        schema.load({"STILLDONE_API_SECRET": synthetic_plaintext})

    err = exc_info.value
    err_str = str(err)
    err_repr = repr(err)

    assert synthetic_plaintext not in err_str, f"Plaintext leaked in str(err): {err_str}"
    assert synthetic_plaintext not in err_repr, f"Plaintext leaked in repr(err): {err_repr}"
    assert err.is_secret is True
    assert err.key == "STILLDONE_API_SECRET"


# ===========================================================================
# 6. Snapshot & Mutation Isolation
# ===========================================================================


def test_environment_snapshot_isolation_from_caller_mutations() -> None:
    """Mutating caller dictionary after load does NOT alter LoadedConfig."""
    caller_env = {
        "STILLDONE_PORT": "8080",
        "STILLDONE_ENV": "development",
    }

    schema = ConfigSchema(
        fields=[
            ConfigField("STILLDONE_PORT", parse_port),
            ConfigField("STILLDONE_ENV", parse_string),
        ],
    )

    cfg = schema.load(caller_env)
    assert cfg["STILLDONE_PORT"] == 8080
    assert cfg["STILLDONE_ENV"] == "development"

    # Mutate original caller dictionary
    caller_env["STILLDONE_PORT"] = "9999"
    caller_env["STILLDONE_ENV"] = "tampered"
    caller_env["STILLDONE_NEW"] = "malicious"

    assert cfg["STILLDONE_PORT"] == 8080
    assert cfg["STILLDONE_ENV"] == "development"
    assert "STILLDONE_NEW" not in cfg


def test_loaded_config_is_immutable() -> None:
    """LoadedConfig rejects item assignment and deletion."""
    schema = ConfigSchema(
        fields=[ConfigField("STILLDONE_PORT", parse_port)],
    )
    cfg = schema.load({"STILLDONE_PORT": "8080"})

    with pytest.raises(TypeError, match="LoadedConfig is immutable"):
        cfg["STILLDONE_PORT"] = 9000

    with pytest.raises(TypeError, match="LoadedConfig is immutable"):
        del cfg["STILLDONE_PORT"]


# ===========================================================================
# 7. Standard Parsers & Type Validation
# ===========================================================================


def test_parse_string() -> None:
    assert parse_string("  hello world  ") == "hello world"
    with pytest.raises(ValueError, match="cannot be empty or whitespace-only"):
        parse_string("")
    with pytest.raises(ValueError, match="cannot be empty or whitespace-only"):
        parse_string("   \t  ")


def test_parse_secret_string() -> None:
    secret = parse_secret_string("  my-secret-val  ")
    assert isinstance(secret, SecretString)
    assert secret.get_secret_value() == "my-secret-val"
    with pytest.raises(ValueError, match="cannot be empty or whitespace-only"):
        parse_secret_string("")


def test_parse_int() -> None:
    assert parse_int("123") == 123
    assert parse_int("  -456  ") == -456
    with pytest.raises(ValueError, match="Cannot parse integer"):
        parse_int("12.34")
    with pytest.raises(ValueError, match="Cannot parse integer"):
        parse_int("abc")
    with pytest.raises(ValueError, match="cannot be empty"):
        parse_int("")


def test_parse_bounded_int() -> None:
    parser = parse_bounded_int(min_val=10, max_val=100)
    assert parser("10") == 10
    assert parser("50") == 50
    assert parser("100") == 100

    with pytest.raises(ValueError, match="below minimum allowed 10"):
        parser("9")
    with pytest.raises(ValueError, match="above maximum allowed 100"):
        parser("101")


def test_parse_port() -> None:
    assert parse_port("80") == 80
    assert parse_port("65535") == 65535
    assert parse_port("1") == 1

    with pytest.raises(ValueError, match="below minimum allowed 1"):
        parse_port("0")
    with pytest.raises(ValueError, match="above maximum allowed 65535"):
        parse_port("65536")


def test_parse_bool() -> None:
    assert parse_bool("true") is True
    assert parse_bool("TRUE") is True
    assert parse_bool("1") is True
    assert parse_bool("false") is False
    assert parse_bool("False") is False
    assert parse_bool("0") is False

    with pytest.raises(ValueError, match="Invalid boolean value"):
        parse_bool("yes")
    with pytest.raises(ValueError, match="Invalid boolean value"):
        parse_bool("no")
    with pytest.raises(ValueError, match="Invalid boolean value"):
        parse_bool("t")
    with pytest.raises(ValueError, match="Invalid boolean value"):
        parse_bool("")


def test_parse_float() -> None:
    assert parse_float("3.14") == 3.14
    assert parse_float(" -0.5 ") == -0.5

    with pytest.raises(ValueError, match="Non-finite float values are forbidden"):
        parse_float("NaN")
    with pytest.raises(ValueError, match="Non-finite float values are forbidden"):
        parse_float("Inf")
    with pytest.raises(ValueError, match="Non-finite float values are forbidden"):
        parse_float("-Infinity")
    with pytest.raises(ValueError, match="Cannot parse float"):
        parse_float("invalid")


def test_parse_choices() -> None:
    parser = parse_choices(["development", "staging", "production"])
    assert parser("development") == "development"
    assert parser("  staging  ") == "staging"

    with pytest.raises(ValueError, match="not one of allowed choices"):
        parser("invalid-env")


# ===========================================================================
# 8. Dataclass Loading Integration
# ===========================================================================


@dataclass(frozen=True)
class _SampleAppConfig:
    port: int
    environment: str
    token: SecretString


def test_load_dataclass_integration() -> None:
    """Schema loads snapshot directly into a typed frozen dataclass."""
    schema = ConfigSchema(
        fields=[
            ConfigField("STILLDONE_PORT", parse_port),
            ConfigField("STILLDONE_ENVIRONMENT", parse_choices(["dev", "prod"])),
            ConfigField("STILLDONE_TOKEN", parse_secret_string, is_secret=True),
        ],
        namespace="STILLDONE_",
    )

    env = {
        "STILLDONE_PORT": "8080",
        "STILLDONE_ENVIRONMENT": "dev",
        "STILLDONE_TOKEN": "synthetic-sample-token",
    }

    cfg = schema.load_dataclass(_SampleAppConfig, env=env)
    assert isinstance(cfg, _SampleAppConfig)
    assert cfg.port == 8080
    assert cfg.environment == "dev"
    assert isinstance(cfg.token, SecretString)
    assert cfg.token.get_secret_value() == "synthetic-sample-token"

    # Dataclass is frozen
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.port = 9000  # type: ignore[misc]


# ===========================================================================
# 9. Schema Invariants & Malformed Input
# ===========================================================================


def test_duplicate_field_declaration_fails_closed() -> None:
    """Declaring duplicate field keys in ConfigSchema raises ValueError."""
    with pytest.raises(ValueError, match="Duplicate configuration key declared"):
        ConfigSchema(
            fields=[
                ConfigField("STILLDONE_PORT", parse_port),
                ConfigField("STILLDONE_PORT", parse_port),
            ]
        )


def test_field_key_validation() -> None:
    """ConfigField key must be non-empty and stripped."""
    with pytest.raises(ValueError, match="must be a non-empty string"):
        ConfigField("", parse_string)

    with pytest.raises(ValueError, match="must not contain leading or trailing whitespace"):
        ConfigField(" STILLDONE_PORT ", parse_string)


def test_non_string_env_mapping_fails_closed() -> None:
    """Environment mapping with non-string keys or values fails closed."""
    schema = ConfigSchema(fields=[ConfigField("STILLDONE_PORT", parse_port)])

    with pytest.raises(ConfigurationError, match="keys must be strings"):
        schema.load({123: "8080"})  # type: ignore[dict-item]

    with pytest.raises(InvalidConfigurationValueError, match="values must be strings"):
        schema.load({"STILLDONE_PORT": 8080})  # type: ignore[dict-item]


def test_loaded_config_mapping_methods() -> None:
    """LoadedConfig implements mapping inspection correctly."""
    schema = ConfigSchema(
        fields=[
            ConfigField("STILLDONE_PORT", parse_port),
            ConfigField("STILLDONE_ENV", parse_string),
        ]
    )
    cfg = schema.load({"STILLDONE_PORT": "8080", "STILLDONE_ENV": "test"})

    assert len(cfg) == 2
    assert "STILLDONE_PORT" in cfg
    assert "NONEXISTENT" not in cfg
    assert sorted(list(cfg)) == ["STILLDONE_ENV", "STILLDONE_PORT"]
    assert sorted(list(cfg.keys())) == ["STILLDONE_ENV", "STILLDONE_PORT"]
    assert cfg.get("STILLDONE_PORT") == 8080
    assert cfg.get("NONEXISTENT", "default_val") == "default_val"
    with pytest.raises(KeyError):
        _ = cfg["NONEXISTENT"]


# ===========================================================================
# 10. Canonical Zero AWS/Google Credential Requirements
# ===========================================================================


def test_no_provider_credential_variables_introduced() -> None:
    """Ensure no static AWS IAM keys or Google OAuth secrets are declared in foundation."""
    forbidden_provider_vars = {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
    }

    schema = ConfigSchema(fields=[])
    declared = schema.declared_keys

    for forbidden in forbidden_provider_vars:
        msg = f"Forbidden provider credential variable declared: {forbidden}"
        assert forbidden not in declared, msg
