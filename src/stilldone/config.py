"""StillDone runtime configuration and secret loading foundation.

Enforces provider-neutral, fail-closed configuration and secret loading:
- Explicit injection or call-time process environment (zero import-time side effects).
- Fail-closed validation for missing, empty, whitespace-only, or malformed required fields.
- Owned namespace protection (unrecognized keys in owned namespace fail closed).
- Unrelated operating system environment variables are safely ignored.
- Distinguishable SecretString container protecting plaintext from repr(), str(),
  dataclass reprs, and validation error messages.
- Immutable configuration snapshots with complete caller-mutation isolation.
- Strictly zero runtime provider-credential requirements (AWS session/IAM-free,
  Google OAuth deferred).
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import math
import os
from collections.abc import Callable, ItemsView, Iterator, KeysView, Mapping, Sequence, ValuesView
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")


# ===========================================================================
# Exceptions
# ===========================================================================


class ConfigurationError(Exception):
    """Base exception for all StillDone configuration and secret loading errors."""


class MissingConfigurationError(ConfigurationError):
    """Raised when a required configuration field is absent, empty, or whitespace-only."""

    def __init__(self, key: str, message: str | None = None) -> None:
        self.key = key
        self.message = message or f"Missing required configuration key: {key!r}"
        super().__init__(self.message)


class InvalidConfigurationValueError(ConfigurationError):
    """Raised when a configuration value is malformed or fails validation.

    Guarantees that secret plaintext values are never included in the error message.
    """

    def __init__(
        self,
        key: str,
        reason: str,
        *,
        is_secret: bool = False,
    ) -> None:
        self.key = key
        self.reason = reason
        self.is_secret = is_secret
        msg = f"Invalid configuration value for key {key!r}: {reason}"
        super().__init__(msg)


class UnknownConfigurationKeyError(ConfigurationError):
    """Raised when unknown keys are present in an owned configuration namespace."""

    def __init__(self, keys: Sequence[str] | str, *, namespace: str) -> None:
        self.keys: tuple[str, ...]
        if isinstance(keys, str):
            self.keys = (keys,)
        else:
            self.keys = tuple(sorted(keys))
        self.namespace = namespace
        keys_str = ", ".join(repr(k) for k in self.keys)
        msg = f"Unknown configuration key(s) in owned namespace {namespace!r}: {keys_str}"
        super().__init__(msg)


# ===========================================================================
# Secret Value Handling
# ===========================================================================


class SecretString:
    """A protected value container for sensitive string values.

    Guarantees:
    - repr() returns 'SecretString("**********")'.
    - str() returns '[REDACTED]'.
    - format() returns '[REDACTED]'.
    - Direct equality comparison with str raises TypeError to prevent
      accidental plaintext leaks in diffs, assertions, or logs.
    - Equality with another SecretString uses constant-time comparison.
    - Plaintext is accessible strictly via get_secret_value() or reveal().
    - Immutable and hashable via domain-separated digest.
    """

    __slots__ = ("_plaintext",)
    _plaintext: str

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"SecretString value must be a str, got {type(value).__name__}")
        object.__setattr__(self, "_plaintext", value)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(
            f"{self.__class__.__name__} is immutable; attribute assignment is forbidden"
        )

    def __delattr__(self, name: str) -> None:
        raise AttributeError(
            f"{self.__class__.__name__} is immutable; attribute deletion is forbidden"
        )

    def get_secret_value(self) -> str:
        """Explicitly return the underlying secret plaintext."""
        return self._plaintext

    def reveal(self) -> str:
        """Explicitly return the underlying secret plaintext (alias for get_secret_value)."""
        return self._plaintext

    def __repr__(self) -> str:
        return 'SecretString("**********")'

    def __str__(self) -> str:
        return "[REDACTED]"

    def __format__(self, format_spec: str) -> str:
        return "[REDACTED]"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretString):
            return hmac.compare_digest(self._plaintext, other._plaintext)
        if isinstance(other, str):
            raise TypeError(
                "Direct comparison between SecretString and str is forbidden to prevent "
                "accidental plaintext leakage in diffs and logs. "
                "Use secret.get_secret_value() == ... or secret == SecretString(...) "
                "if comparison is intentional."
            )
        return False

    def __hash__(self) -> int:
        digest = hashlib.sha256(
            b"stilldone:secret-string:v1:" + self._plaintext.encode("utf-8")
        ).digest()
        return hash((self.__class__, digest))

    def __len__(self) -> int:
        raise TypeError("len() is not supported on SecretString to prevent length leakage")

    def __bool__(self) -> bool:
        return bool(self._plaintext)

    def __copy__(self) -> SecretString:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> SecretString:
        return self


# ===========================================================================
# Standard Parsers & Validators
# ===========================================================================


def parse_string(val: str) -> str:
    """Parse and validate a non-empty string."""
    stripped = val.strip()
    if not stripped:
        raise ValueError("String value cannot be empty or whitespace-only")
    return stripped


def parse_secret_string(val: str) -> SecretString:
    """Parse and validate a non-empty secret string without mutating whitespace."""
    if not val.strip():
        raise ValueError("Secret value cannot be empty or whitespace-only")
    return SecretString(val)


def parse_int(val: str) -> int:
    """Parse and validate an integer value."""
    stripped = val.strip()
    if not stripped:
        raise ValueError("Integer value cannot be empty or whitespace-only")
    try:
        return int(stripped)
    except ValueError:
        raise ValueError(f"Cannot parse integer from {stripped!r}") from None


def parse_bounded_int(
    min_val: int | None = None,
    max_val: int | None = None,
) -> Callable[[str], int]:
    """Return an integer parser with bounds validation."""

    def _parser(val: str) -> int:
        parsed = parse_int(val)
        if min_val is not None and parsed < min_val:
            raise ValueError(f"Integer value {parsed} is below minimum allowed {min_val}")
        if max_val is not None and parsed > max_val:
            raise ValueError(f"Integer value {parsed} is above maximum allowed {max_val}")
        return parsed

    return _parser


def parse_port(val: str) -> int:
    """Parse and validate a TCP/UDP port number (1-65535)."""
    return parse_bounded_int(1, 65535)(val)


def parse_bool(val: str) -> bool:
    """Parse and validate a boolean value strictly.

    Accepts 'true', 'false', '1', '0' (case-insensitive).
    All other values fail closed.
    """
    stripped = val.strip().lower()
    if stripped in ("true", "1"):
        return True
    if stripped in ("false", "0"):
        return False
    raise ValueError(
        f"Invalid boolean value {val.strip()!r}: expected 'true', 'false', '1', or '0'"
    )


def parse_float(val: str) -> float:
    """Parse and validate a finite floating-point number.

    Rejects non-finite values (NaN, Inf, -Inf) to maintain determinism.
    """
    stripped = val.strip()
    if not stripped:
        raise ValueError("Float value cannot be empty or whitespace-only")
    try:
        res = float(stripped)
    except ValueError:
        raise ValueError(f"Cannot parse float from {stripped!r}") from None
    if not math.isfinite(res):
        raise ValueError(f"Non-finite float values are forbidden: {stripped!r}")
    return res


def parse_choices(choices: Sequence[str]) -> Callable[[str], str]:
    """Return a parser that validates string values against an allowed set of choices."""
    allowed = tuple(choices)
    allowed_set = set(allowed)

    def _parser(val: str) -> str:
        stripped = parse_string(val)
        if stripped not in allowed_set:
            sorted_allowed = ", ".join(repr(c) for c in sorted(allowed_set))
            raise ValueError(
                f"Value {stripped!r} is not one of allowed choices: [{sorted_allowed}]"
            )
        return stripped

    return _parser


# ===========================================================================
# Field Specification
# ===========================================================================


@dataclass(frozen=True)
class ConfigField(Generic[T]):
    """Specification of a declared configuration field.

    Invariants:
    - key must be a non-empty string without leading/trailing whitespace.
    - required fields cannot have defaults.
    - secret fields cannot have non-None defaults (secrets must be explicit).
    """

    key: str
    parser: Callable[[str], T]
    required: bool = True
    default: T | None = None
    is_secret: bool = False
    description: str = ""
    validator: Callable[[T], None] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError("ConfigField key must be a non-empty string")
        if self.key != self.key.strip():
            raise ValueError(
                f"ConfigField key must not contain leading or trailing whitespace: {self.key!r}"
            )
        if self.required and self.default is not None:
            raise ValueError(f"Required field {self.key!r} cannot have a non-None default value")
        if self.is_secret and self.default is not None:
            raise ValueError(
                f"Secret field {self.key!r} cannot have a default value; "
                "secrets must be explicitly provided"
            )


# ===========================================================================
# Loaded Configuration Snapshot
# ===========================================================================


class LoadedConfig:
    """An immutable, validated configuration snapshot.

    Provides dictionary-like read-only access.
    Guarantees:
    - Complete snapshot isolation from caller environment mutation.
    - Immutable values (setting or deleting keys raises TypeError).
    - Secret protection in repr(), str(), and to_dict().
    """

    def __init__(
        self,
        values: Mapping[str, Any],
        secret_keys: frozenset[str],
        schema: ConfigSchema | None = None,
    ) -> None:
        self._values: dict[str, Any] = dict(values)
        self._secret_keys: frozenset[str] = frozenset(secret_keys)
        self._schema = schema

        for sk in self._secret_keys:
            if sk in self._values and not isinstance(self._values[sk], SecretString):
                val_type = type(self._values[sk]).__name__
                raise InvalidConfigurationValueError(
                    sk,
                    f"Secret-classified configuration value must be a SecretString, got {val_type}",
                    is_secret=True,
                )

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def __getitem__(self, key: str) -> Any:
        if key not in self._values:
            raise KeyError(key)
        return self._values[key]

    def __contains__(self, key: object) -> bool:
        return key in self._values

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def keys(self) -> KeysView[str]:
        return self._values.keys()

    def items(self) -> ItemsView[str, Any]:
        return self._values.items()

    def values(self) -> ValuesView[Any]:
        return self._values.values()

    def __setitem__(self, key: str, value: Any) -> None:
        raise TypeError("LoadedConfig is immutable; setting configuration values is forbidden")

    def __delitem__(self, key: str) -> None:
        raise TypeError("LoadedConfig is immutable; deleting configuration values is forbidden")

    def to_dict(self, *, redact_secrets: bool = True) -> dict[str, Any]:
        """Return a detached dictionary of configuration values.

        If redact_secrets is True (default), secret values are returned as '[REDACTED]'.
        """
        result: dict[str, Any] = {}
        for k, v in self._values.items():
            if (k in self._secret_keys or isinstance(v, SecretString)) and redact_secrets:
                result[k] = "[REDACTED]"
            else:
                result[k] = v
        return result

    def __repr__(self) -> str:
        safe_items: list[str] = []
        for k, v in sorted(self._values.items()):
            if k in self._secret_keys or isinstance(v, SecretString):
                safe_items.append(f"{k!r}: SecretString('**********')")
            else:
                safe_items.append(f"{k!r}: {v!r}")
        return f"LoadedConfig({{{', '.join(safe_items)}}})"

    def __str__(self) -> str:
        return repr(self)


# ===========================================================================
# Configuration Schema
# ===========================================================================


class ConfigSchema:
    """Declared schema and namespace definition for configuration loading.

    Guarantees:
    - Explicitly declared keys only.
    - Fail-closed on missing, empty, whitespace-only, or malformed required values.
    - Fail-closed on unknown keys inside owned namespace.
    - Unrelated operating system environment variables are safely ignored.
    - Snapshot isolation from environment mutations.
    """

    def __init__(
        self,
        fields: Sequence[ConfigField[Any]],
        *,
        namespace: str | None = "STILLDONE_",
    ) -> None:
        seen_keys: set[str] = set()
        fields_list: list[ConfigField[Any]] = []
        secret_keys_set: set[str] = set()

        for f in fields:
            if not isinstance(f, ConfigField):
                raise TypeError(f"Expected ConfigField, got {type(f).__name__}")
            if f.key in seen_keys:
                raise ValueError(f"Duplicate configuration key declared in schema: {f.key!r}")
            seen_keys.add(f.key)
            fields_list.append(f)
            if f.is_secret or f.parser is parse_secret_string:
                secret_keys_set.add(f.key)

        self._fields: tuple[ConfigField[Any], ...] = tuple(fields_list)
        self._fields_by_key: dict[str, ConfigField[Any]] = {f.key: f for f in self._fields}
        self._secret_keys: frozenset[str] = frozenset(secret_keys_set)
        self._namespace: str | None = namespace

    @property
    def fields(self) -> tuple[ConfigField[Any], ...]:
        return self._fields

    @property
    def namespace(self) -> str | None:
        return self._namespace

    @property
    def declared_keys(self) -> frozenset[str]:
        return frozenset(self._fields_by_key.keys())

    def load(self, env: Mapping[str, str] | None = None) -> LoadedConfig:
        """Load and validate configuration from an explicit mapping or process environment.

        Args:
            env: Optional explicit mapping of environment variables.
                 If None, os.environ is inspected strictly at call time.

        Returns:
            An immutable LoadedConfig snapshot.
        """
        # 1. Snapshot caller mapping at call time
        source_mapping = os.environ if env is None else env
        env_snapshot: dict[str, str] = {}
        for k, v in source_mapping.items():
            if not isinstance(k, str):
                msg = f"Environment keys must be strings, got {type(k).__name__}"
                raise ConfigurationError(msg)
            if not isinstance(v, str):
                raise InvalidConfigurationValueError(
                    k, f"Environment values must be strings, got {type(v).__name__}"
                )
            env_snapshot[k] = v

        # 2. Namespace fail-closed check
        if self._namespace is not None:
            unknown_keys = [
                k
                for k in env_snapshot
                if k.startswith(self._namespace) and k not in self._fields_by_key
            ]
            if unknown_keys:
                raise UnknownConfigurationKeyError(unknown_keys, namespace=self._namespace)

        # 3. Process each declared field
        loaded_values: dict[str, Any] = {}

        for field in self._fields:
            key = field.key
            is_secret = field.is_secret or (key in self._secret_keys)

            if key in env_snapshot:
                raw_value = env_snapshot[key]
                is_empty_or_whitespace = raw_value.strip() == ""

                if is_empty_or_whitespace:
                    if field.required:
                        raise MissingConfigurationError(
                            key,
                            f"Required configuration key {key!r} is empty or whitespace-only",
                        )
                    raise InvalidConfigurationValueError(
                        key,
                        "value cannot be empty or whitespace-only",
                        is_secret=is_secret,
                    )

                # Parse value
                try:
                    parsed = field.parser(raw_value)
                except Exception as exc:
                    if is_secret:
                        reason = "secret validation failed (plaintext redacted)"
                    else:
                        reason = str(exc)
                    raise InvalidConfigurationValueError(
                        key,
                        reason,
                        is_secret=is_secret,
                    ) from None

                if is_secret and not isinstance(parsed, SecretString):
                    parsed_type = type(parsed).__name__
                    raise InvalidConfigurationValueError(
                        key,
                        f"Secret-classified field must parse to SecretString, got {parsed_type}",
                        is_secret=True,
                    )

                # Validate parsed value
                if field.validator is not None:
                    try:
                        field.validator(parsed)
                    except Exception as exc:
                        if is_secret:
                            reason = "secret validator check failed (plaintext redacted)"
                        else:
                            reason = str(exc)
                        raise InvalidConfigurationValueError(
                            key,
                            reason,
                            is_secret=is_secret,
                        ) from None

                loaded_values[key] = parsed
            else:
                # Key is absent
                if field.required:
                    raise MissingConfigurationError(
                        key,
                        f"Missing required configuration key: {key!r}",
                    )
                loaded_values[key] = field.default

        return LoadedConfig(
            values=loaded_values,
            secret_keys=self._secret_keys,
            schema=self,
        )

    def load_dataclass(
        self,
        dataclass_cls: type[T],
        env: Mapping[str, str] | None = None,
        *,
        field_mapping: Mapping[str, str] | None = None,
    ) -> T:
        """Load configuration snapshot and instantiate a typed frozen dataclass.

        Args:
            dataclass_cls: Target dataclass class.
            env: Optional explicit environment mapping.
            field_mapping: Optional mapping from dataclass field name to config key.
                           If omitted, maps attribute name to config key either by
                           exact match, case-insensitive match, or namespace prefix match.
        """
        if not dataclasses.is_dataclass(dataclass_cls):
            raise TypeError(f"Target class {dataclass_cls.__name__} is not a dataclass")

        loaded = self.load(env)
        mapping_dict = dict(field_mapping) if field_mapping is not None else {}
        kwargs: dict[str, Any] = {}

        dc_fields = dataclasses.fields(dataclass_cls)
        for df in dc_fields:
            if df.name in mapping_dict:
                config_key = mapping_dict[df.name]
            elif df.name in self._fields_by_key:
                config_key = df.name
            else:
                # Search by case-insensitive name or namespace prefix
                ns = self._namespace or ""
                candidates = [
                    k
                    for k in self._fields_by_key
                    if k.lower() == df.name.lower() or k.lower() == f"{ns}{df.name}".lower()
                ]
                if len(candidates) == 1:
                    config_key = candidates[0]
                else:
                    raise ConfigurationError(
                        f"Cannot map dataclass field {df.name!r} to schema configuration keys: "
                        f"ambiguous or missing candidates {candidates!r}"
                    )

            kwargs[df.name] = loaded[config_key]

        return dataclass_cls(**kwargs)


__all__ = [
    "ConfigField",
    "ConfigSchema",
    "ConfigurationError",
    "InvalidConfigurationValueError",
    "LoadedConfig",
    "MissingConfigurationError",
    "SecretString",
    "UnknownConfigurationKeyError",
    "parse_bool",
    "parse_bounded_int",
    "parse_choices",
    "parse_float",
    "parse_int",
    "parse_port",
    "parse_secret_string",
    "parse_string",
]
