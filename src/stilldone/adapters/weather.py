"""Open-Meteo weather observation adapter for StillDone.

Provides bounded, fail-closed integration with Open-Meteo forecast API:
- Conforms to canonical P-04 WEATHER_READ action policy and READ_ONLY authority.
- Authority strictly requires approval=None; unexpected ApprovalGrant fails closed.
- Target semantics: resource_id must match configured location_id; parent_id must be None.
- Privacy minimization: coordinates are masked in repr/str and excluded from durable observations.
- Pluggable transport boundary (WeatherTransport protocol):
  * FakeOpenMeteoTransport for deterministic testing and CI (provenance=FIXTURE).
  * OpenMeteoHttpTransport for live calls (provenance=LIVE_EXTERNAL).
- Transport provenance is preserved and enforced; synthetic fakes cannot claim LIVE_EXTERNAL.
- Mandatory CC BY 4.0 provider attribution (ProviderAttribution).
- Zero personal spend ($0.00): free non-commercial Open-Meteo tier.
- Bounded HTTP timeout and strict error sanitization preventing coordinate or URL leakage.
- Observation success does NOT verify or promote state to READY.
"""

from __future__ import annotations

import json
import logging
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from stilldone.action_policy import (
    ValidatedActionContract,
    validate_action_contract,
)
from stilldone.authority_policy import (
    AuthorityDecisionStatus,
    evaluate_authority,
)
from stilldone.demo_isolation import (
    DemoIsolationError,
    DemoResourceScope,
    verify_demo_resource_isolation,
)
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
)
from stilldone.domain.authority import ApprovalGrant
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.redaction import redact_text

logger = logging.getLogger(__name__)

# ===========================================================================
# Canonical Constants
# ===========================================================================

CANONICAL_WEATHER_SYSTEM = "open_meteo"
CANONICAL_WEATHER_RESOURCE_KIND = ResourceKind.WEATHER_LOCATION

CANONICAL_OPEN_METEO_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
DEFAULT_OPEN_METEO_BASE_URL = CANONICAL_OPEN_METEO_ENDPOINT
DEFAULT_OPEN_METEO_CURRENT_VARS = "temperature_2m,precipitation,weather_code,wind_speed_10m"
DEFAULT_OPEN_METEO_USER_AGENT = "StillDone/1.0 (https://github.com/zyganali-glitch/StillDone)"
DEFAULT_HTTP_TIMEOUT_SECONDS = 5.0

ATTRIBUTION_PROVIDER = "Open-Meteo"
ATTRIBUTION_LICENSE = "CC BY 4.0"
ATTRIBUTION_TEXT = "Weather data by Open-Meteo.com"
ATTRIBUTION_URL = "https://open-meteo.com/"

# Coordinate validation bounds
MIN_LATITUDE = -90.0
MAX_LATITUDE = 90.0
MIN_LONGITUDE = -180.0
MAX_LONGITUDE = 180.0


# ===========================================================================
# Adapter Exception Hierarchy
# ===========================================================================


class WeatherAdapterError(Exception):
    """Base exception for all Weather adapter operations."""


class WeatherConfigError(WeatherAdapterError, ValueError):
    """Raised when weather location configuration is invalid or malformed."""


class WeatherTargetError(WeatherAdapterError, ValueError):
    """Raised when an action target identity or parameters violate weather requirements."""


class WeatherTransportError(WeatherAdapterError):
    """Base exception for transport/network failures fetching weather data."""

    def __init__(
        self,
        message: str = "Weather transport error",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


class WeatherRateLimitError(WeatherTransportError):
    """Raised when Open-Meteo rate limit (HTTP 429) is encountered."""

    def __init__(
        self,
        message: str = "Open-Meteo rate limit exceeded",
        status_code: int | None = 429,
    ) -> None:
        super().__init__(message, status_code=status_code)


class WeatherTimeoutError(WeatherTransportError):
    """Raised when an Open-Meteo network request times out."""

    def __init__(
        self,
        message: str = "Open-Meteo request timed out",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)


class WeatherApiError(WeatherTransportError):
    """Raised when Open-Meteo provider API returns an unhandled error response."""

    def __init__(
        self,
        message: str = "Open-Meteo API error",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)


def _sanitize_weather_transport_error(exc: Exception) -> str:
    """Map transport/network exceptions to bounded sanitized error messages.

    Guarantees that raw provider URLs, query parameters, coordinates,
    IP addresses, and internal network traces are never exposed in error messages.
    """
    status_code: int | None = getattr(exc, "status_code", None)
    if status_code is None:
        code_attr = getattr(exc, "code", None)
        if isinstance(code_attr, int):
            status_code = code_attr

    code_suffix = f" (status {status_code})" if status_code is not None else ""

    if isinstance(exc, WeatherRateLimitError):
        msg = f"Open-Meteo rate limit exceeded{code_suffix}"
    elif isinstance(exc, WeatherTimeoutError):
        msg = "Open-Meteo request timed out"
    elif isinstance(exc, WeatherApiError):
        msg = f"Open-Meteo provider API error{code_suffix}"
    elif isinstance(exc, WeatherTransportError):
        msg = f"Open-Meteo transport error{code_suffix}"
    else:
        msg = f"Unexpected weather transport failure: {type(exc).__name__}"

    return redact_text(msg)


def validate_open_meteo_endpoint(url: str) -> str:
    """Validate that the URL is strictly the canonical Open-Meteo forecast endpoint.

    Fails closed against SSRF, protocol downgrade, credentials, alternate ports,
    subdomain/lookalike domains, and query/fragment injection.
    """
    if not isinstance(url, str) or not url.strip():
        raise WeatherTransportError("Open-Meteo endpoint URL must be a non-empty string")

    parsed = urllib.parse.urlsplit(url)

    if parsed.scheme != "https":
        raise WeatherTransportError(
            f"Open-Meteo endpoint must use HTTPS scheme, got '{parsed.scheme}'"
        )

    if parsed.username or parsed.password:
        raise WeatherTransportError("Open-Meteo endpoint must not include user credentials")

    if parsed.hostname != "api.open-meteo.com":
        raise WeatherTransportError(
            f"Open-Meteo endpoint host must be 'api.open-meteo.com', got '{parsed.hostname}'"
        )

    if parsed.port is not None:
        raise WeatherTransportError(
            f"Open-Meteo endpoint must not specify alternate port, got port {parsed.port}"
        )

    if parsed.path != "/v1/forecast":
        raise WeatherTransportError(
            f"Open-Meteo endpoint path must be '/v1/forecast', got '{parsed.path}'"
        )

    if parsed.query or parsed.fragment:
        raise WeatherTransportError(
            "Open-Meteo endpoint URL must not contain query parameters or fragments"
        )

    return url


# ===========================================================================
# Configuration & Location Models
# ===========================================================================


@dataclass(frozen=True, slots=True)
class WeatherLocationConfig:
    """Configuration for a monitored geographic weather location.

    Coordinates are masked in repr and str to avoid leaking sensitive or
    personal location data into logs or console outputs.
    """

    location_id: str
    latitude: float
    longitude: float
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        if not isinstance(self.location_id, str) or not self.location_id.strip():
            raise WeatherConfigError("location_id must be a non-empty string")
        if not isinstance(self.latitude, (int, float)) or not (
            MIN_LATITUDE <= self.latitude <= MAX_LATITUDE
        ):
            raise WeatherConfigError(
                f"latitude must be a numeric value between {MIN_LATITUDE} and {MAX_LATITUDE}"
            )
        if not isinstance(self.longitude, (int, float)) or not (
            MIN_LONGITUDE <= self.longitude <= MAX_LONGITUDE
        ):
            raise WeatherConfigError(
                f"longitude must be a numeric value between {MIN_LONGITUDE} and {MAX_LONGITUDE}"
            )
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise WeatherConfigError("timezone must be a non-empty string")

    def __repr__(self) -> str:
        return (
            f"WeatherLocationConfig(location_id='***', "
            f"latitude=***, longitude=***, timezone='{self.timezone}')"
        )

    def __str__(self) -> str:
        return self.__repr__()


# ===========================================================================
# Provider Attribution & Normalized Observation Models
# ===========================================================================


@dataclass(frozen=True, slots=True)
class ProviderAttribution:
    """Mandatory attribution metadata required by Open-Meteo CC BY 4.0 license."""

    provider: str = ATTRIBUTION_PROVIDER
    license: str = ATTRIBUTION_LICENSE
    text: str = ATTRIBUTION_TEXT
    url: str = ATTRIBUTION_URL


@dataclass(frozen=True, slots=True)
class WeatherObservation:
    """Normalized, sanitized weather observation from Open-Meteo.

    Persists only bounded meteorological variables needed by StillDone.
    Coordinates and location_id are masked in repr/str to enforce privacy.
    Does NOT assert or imply VERIFIED or READY.
    """

    location_id: str
    temperature_2m: float
    precipitation: float
    weather_code: int
    wind_speed_10m: float
    units: dict[str, str]
    observed_at: datetime
    attribution: ProviderAttribution
    provenance: EvidenceProvenance
    provider_valid_time: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, EvidenceProvenance):
            raise TypeError(
                f"provenance must be an EvidenceProvenance instance, "
                f"got {type(self.provenance).__name__}"
            )
        if not isinstance(self.attribution, ProviderAttribution):
            raise TypeError(
                f"attribution must be a ProviderAttribution instance, "
                f"got {type(self.attribution).__name__}"
            )

    def __repr__(self) -> str:
        return (
            f"WeatherObservation(location_id='***', "
            f"temperature_2m={self.temperature_2m}, precipitation={self.precipitation}, "
            f"weather_code={self.weather_code}, wind_speed_10m={self.wind_speed_10m}, "
            f"provider_valid_time='{self.provider_valid_time}', "
            f"provenance='{self.provenance.value}')"
        )

    def __str__(self) -> str:
        return self.__repr__()


class WeatherReadStatus(StrEnum):
    """Result status of a weather observation read operation."""

    MATCH = "MATCH"
    PROVIDER_ERROR = "PROVIDER_ERROR"


@dataclass(frozen=True, slots=True)
class WeatherReadResult:
    """Outcome of a weather read adapter operation."""

    status: WeatherReadStatus
    observation: WeatherObservation | None = None
    error_message: str | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"WeatherReadResult(status='{self.status.value}', "
            f"observation={self.observation is not None}, "
            f"error_message={redact_text(self.error_message) if self.error_message else None})"
        )

    def __str__(self) -> str:
        return self.__repr__()


# ===========================================================================
# Transport Protocol & Implementations
# ===========================================================================


@runtime_checkable
class WeatherTransport(Protocol):
    """Protocol for fetching weather observations from external or fake sources."""

    @property
    def provenance(self) -> EvidenceProvenance:
        """The immutable evidence provenance guaranteed by this transport."""
        ...

    def fetch_current_weather(
        self,
        latitude: float,
        longitude: float,
        timezone: str = "UTC",
    ) -> dict[str, Any]:
        """Fetch current weather data for the specified coordinates.

        Returns raw parsed JSON dictionary response.
        """
        ...


class FakeOpenMeteoTransport:
    """In-memory fake transport for deterministic testing and CI.

    Guarantees EvidenceProvenance.FIXTURE. Never reports LIVE_EXTERNAL.
    Tracks read calls and allows simulating errors or custom responses.
    """

    def __init__(self, canned_response: dict[str, Any] | None = None) -> None:
        self.reads_count: int = 0
        self.last_coordinates: tuple[float, float] | None = None
        self.last_timezone: str | None = None
        self.simulate_error: Exception | None = None
        self.canned_response: dict[str, Any] = canned_response or {
            "latitude": 52.52,
            "longitude": 13.41,
            "current_units": {
                "time": "iso8601",
                "interval": "seconds",
                "temperature_2m": "°C",
                "precipitation": "mm",
                "weather_code": "wmo code",
                "wind_speed_10m": "km/h",
            },
            "current": {
                "time": "2026-10-03T10:00:00Z",
                "interval": 900,
                "temperature_2m": 15.5,
                "precipitation": 0.0,
                "weather_code": 1,
                "wind_speed_10m": 12.0,
            },
        }

    @property
    def provenance(self) -> EvidenceProvenance:
        """Synthetic transport strictly returns FIXTURE provenance."""
        return EvidenceProvenance.FIXTURE

    def fetch_current_weather(
        self,
        latitude: float,
        longitude: float,
        timezone: str = "UTC",
    ) -> dict[str, Any]:
        """Return canned weather data or raise simulated error."""
        self.reads_count += 1
        self.last_coordinates = (latitude, longitude)
        self.last_timezone = timezone
        if self.simulate_error is not None:
            raise self.simulate_error
        return self.canned_response


class OpenMeteoHttpTransport:
    """Production HTTP transport communicating with official Open-Meteo API.

    Guarantees EvidenceProvenance.LIVE_EXTERNAL.
    Locked to canonical Open-Meteo forecast API: https://api.open-meteo.com/v1/forecast
    Strictly validates against SSRF, protocol downgrade, and alternate endpoints.
    Uses standard library urllib over HTTPS with bounded timeout and zero personal spend.
    Sanitizes all exceptions to prevent leaking coordinates or network details.
    """

    def __init__(
        self,
        endpoint: str = CANONICAL_OPEN_METEO_ENDPOINT,
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        user_agent: str = DEFAULT_OPEN_METEO_USER_AGENT,
    ) -> None:
        self._endpoint = validate_open_meteo_endpoint(endpoint)
        self._timeout_seconds = timeout_seconds
        self._user_agent = user_agent
        self.reads_count: int = 0

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def provenance(self) -> EvidenceProvenance:
        """Real external HTTP transport strictly returns LIVE_EXTERNAL provenance."""
        return EvidenceProvenance.LIVE_EXTERNAL

    def fetch_current_weather(
        self,
        latitude: float,
        longitude: float,
        timezone: str = "UTC",
    ) -> dict[str, Any]:
        """Perform a single bounded HTTPS GET request to Open-Meteo forecast API."""
        self.reads_count += 1

        params = {
            "latitude": f"{latitude:.6f}",
            "longitude": f"{longitude:.6f}",
            "current": DEFAULT_OPEN_METEO_CURRENT_VARS,
            "timezone": timezone,
        }
        query_string = urllib.parse.urlencode(params)
        url = f"{self._endpoint}?{query_string}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout_seconds) as resp:
                status_code = resp.status
                if status_code != 200:
                    raise WeatherApiError(
                        f"Open-Meteo unexpected HTTP status (status {status_code})",
                        status_code=status_code,
                    )
                raw_bytes = resp.read()
                try:
                    payload = json.loads(raw_bytes.decode("utf-8"))
                except Exception as decode_err:
                    raise WeatherApiError("Malformed JSON response from Open-Meteo") from decode_err

                if not isinstance(payload, dict):
                    raise WeatherApiError("Open-Meteo returned unexpected non-dictionary payload")

                return payload

        except urllib.error.HTTPError as http_err:
            code = http_err.code
            if code == 429:
                raise WeatherRateLimitError(
                    "Open-Meteo rate limit exceeded (status 429)",
                    status_code=429,
                ) from http_err
            raise WeatherApiError(
                f"Open-Meteo provider API error (status {code})",
                status_code=code,
            ) from http_err

        except urllib.error.URLError as url_err:
            # Check for socket/request timeout
            reason = getattr(url_err, "reason", None)
            if isinstance(reason, TimeoutError) or "timed out" in str(url_err).lower():
                raise WeatherTimeoutError("Open-Meteo request timed out") from url_err
            raise WeatherTransportError("Open-Meteo connection failure") from url_err

        except TimeoutError as timeout_err:
            raise WeatherTimeoutError("Open-Meteo request timed out") from timeout_err

        except (WeatherTransportError, WeatherAdapterError):
            raise

        except Exception as exc:
            raise WeatherTransportError("Open-Meteo transport error") from exc


# ===========================================================================
# Weather Observation Adapter
# ===========================================================================


class OpenMeteoReadAdapter:
    """Bounded, fail-closed Open-Meteo weather observation adapter.

    Enforces P-04 WEATHER_READ contracts:
    - action_type must be ActionType.WEATHER_READ.
    - target.system must be 'open_meteo'.
    - target.resource_kind must be ResourceKind.WEATHER_LOCATION.
    - target.parent_id must be None.
    - target.resource_id must match configured location_id.
    - authority must be READ_ONLY; approval must be None (unexpected grant fails closed).
    - Provider observation success does NOT verify or promote state to READY.
    """

    def __init__(
        self,
        config: WeatherLocationConfig,
        transport: WeatherTransport,
        scope: DemoResourceScope | None = None,
    ) -> None:
        if not isinstance(config, WeatherLocationConfig):
            raise WeatherConfigError(
                f"config must be a WeatherLocationConfig instance, got {type(config).__name__}"
            )
        if not isinstance(transport, WeatherTransport):
            raise TypeError(
                f"transport must implement WeatherTransport, got {type(transport).__name__}"
            )
        # Closed-world provenance verification: only OpenMeteoHttpTransport can assert LIVE_EXTERNAL
        if transport.provenance == EvidenceProvenance.LIVE_EXTERNAL and not isinstance(
            transport, OpenMeteoHttpTransport
        ):
            raise WeatherConfigError(
                "Only verified OpenMeteoHttpTransport may assert LIVE_EXTERNAL provenance"
            )
        self._config = config
        self._transport = transport
        self._scope = scope

    @property
    def config(self) -> WeatherLocationConfig:
        """The monitored weather location configuration."""
        return self._config

    @property
    def transport(self) -> WeatherTransport:
        """The underlying weather transport."""
        return self._transport

    def read_weather(
        self,
        action: ValidatedActionContract | ActionContract,
        approval: ApprovalGrant | None = None,
        at: datetime | None = None,
    ) -> WeatherReadResult:
        """Read a weather observation for the configured location.

        Validates the action contract, evaluates authority policy (failing closed if
        an unexpected ApprovalGrant is provided), and delegates to transport.

        Args:
            action: Either a ValidatedActionContract or raw ActionContract.
            approval: Must be None for READ_ONLY action. Unexpected grant fails closed.
            at: Optional evaluation timestamp.

        Returns:
            WeatherReadResult with MATCH or PROVIDER_ERROR status.

        Raises:
            WeatherTargetError / ActionPolicyError: If target or parameters violate requirements.
            UnexpectedApprovalGrantError: If approval grant is provided for READ_ONLY action.
        """
        # Step 1: Ensure ValidatedActionContract
        if isinstance(action, ActionContract):
            validated = validate_action_contract(action)
        elif isinstance(action, ValidatedActionContract):
            validated = action
        else:
            raise TypeError(
                f"action must be ActionContract or ValidatedActionContract, "
                f"got {type(action).__name__}"
            )

        # Step 2: Validate ActionType
        if validated.action_type != ActionType.WEATHER_READ:
            raise WeatherTargetError(
                f"OpenMeteoReadAdapter handles '{ActionType.WEATHER_READ.value}', "
                f"got '{validated.action_type.value}'"
            )

        # Step 3: Validate Target System & ResourceKind
        if validated.target.system != CANONICAL_WEATHER_SYSTEM:
            raise WeatherTargetError(
                f"Target system must be '{CANONICAL_WEATHER_SYSTEM}', "
                f"got '{validated.target.system}'"
            )
        if validated.target.resource_kind != CANONICAL_WEATHER_RESOURCE_KIND:
            raise WeatherTargetError(
                f"Target resource_kind must be '{CANONICAL_WEATHER_RESOURCE_KIND.value}', "
                f"got '{validated.target.resource_kind.value}'"
            )

        # Step 4: Validate Target Identifiers (Defect B: never format location_id)
        if validated.target.parent_id is not None:
            raise WeatherTargetError(
                "Target parent_id must be None for weather location observations"
            )
        if validated.target.resource_id != self._config.location_id:
            raise WeatherTargetError("Target resource_id does not match configured location scope")

        # Step 5: Demo isolation check
        dummy_scope = self._scope or DemoResourceScope(
            calendar_id="demo-cal", task_list_id="demo-tasks"
        )
        try:
            verify_demo_resource_isolation(validated, dummy_scope)
        except DemoIsolationError as exc:
            logger.warning("Weather demo isolation check failed: %s", type(exc).__name__)
            raise

        # Step 6: Authority evaluation
        eval_time = at or datetime.now(UTC)
        decision = evaluate_authority(
            action=validated,
            approval=approval,
            at=eval_time,
            raise_on_rejection=True,
        )
        if decision.status != AuthorityDecisionStatus.AUTHORIZED_NO_APPROVAL_REQUIRED:
            raise WeatherTargetError("WEATHER_READ authority evaluation failed")

        # Step 7: Transport execution with closed-world provenance and runtime timing
        if self._transport.provenance == EvidenceProvenance.LIVE_EXTERNAL and not isinstance(
            self._transport, OpenMeteoHttpTransport
        ):
            obs_time = datetime.now(UTC)
            return WeatherReadResult(
                status=WeatherReadStatus.PROVIDER_ERROR,
                error_message="Unauthorized LIVE_EXTERNAL provenance claim by non-HTTP transport",
                observed_at=obs_time,
            )

        try:
            raw_data = self._transport.fetch_current_weather(
                latitude=self._config.latitude,
                longitude=self._config.longitude,
                timezone=self._config.timezone,
            )
        except Exception as exc:
            obs_time = datetime.now(UTC)
            sanitized_msg = _sanitize_weather_transport_error(exc)
            logger.warning("Weather transport failure: %s", sanitized_msg)
            return WeatherReadResult(
                status=WeatherReadStatus.PROVIDER_ERROR,
                error_message=sanitized_msg,
                observed_at=obs_time,
            )

        obs_time = datetime.now(UTC)

        # Step 8: Strict schema validation (Defect C: fail closed on partial/malformed schema)
        if not isinstance(raw_data, dict):
            return WeatherReadResult(
                status=WeatherReadStatus.PROVIDER_ERROR,
                error_message="Provider response must be a JSON object",
                observed_at=obs_time,
            )

        current = raw_data.get("current")
        if not isinstance(current, dict):
            return WeatherReadResult(
                status=WeatherReadStatus.PROVIDER_ERROR,
                error_message="Missing or invalid 'current' weather block from provider",
                observed_at=obs_time,
            )

        current_units = raw_data.get("current_units")
        if not isinstance(current_units, dict):
            return WeatherReadResult(
                status=WeatherReadStatus.PROVIDER_ERROR,
                error_message="Missing or invalid 'current_units' weather block from provider",
                observed_at=obs_time,
            )

        # Validate time ISO string
        time_raw = current.get("time")
        if not isinstance(time_raw, str) or not time_raw.strip():
            return WeatherReadResult(
                status=WeatherReadStatus.PROVIDER_ERROR,
                error_message="Missing or invalid 'time' in provider current weather",
                observed_at=obs_time,
            )
        try:
            datetime.fromisoformat(time_raw)
        except (ValueError, TypeError):
            return WeatherReadResult(
                status=WeatherReadStatus.PROVIDER_ERROR,
                error_message="Provider current 'time' is not a valid ISO-8601 string",
                observed_at=obs_time,
            )

        # Validate finite numeric variables
        temp_raw = current.get("temperature_2m")
        if (
            temp_raw is None
            or isinstance(temp_raw, bool)
            or not isinstance(temp_raw, (int, float))
            or not math.isfinite(temp_raw)
        ):
            return WeatherReadResult(
                status=WeatherReadStatus.PROVIDER_ERROR,
                error_message="Missing or non-finite 'temperature_2m' in provider current weather",
                observed_at=obs_time,
            )

        precip_raw = current.get("precipitation")
        if (
            precip_raw is None
            or isinstance(precip_raw, bool)
            or not isinstance(precip_raw, (int, float))
            or not math.isfinite(precip_raw)
        ):
            return WeatherReadResult(
                status=WeatherReadStatus.PROVIDER_ERROR,
                error_message="Missing or non-finite 'precipitation' in provider current weather",
                observed_at=obs_time,
            )

        code_raw = current.get("weather_code")
        if (
            code_raw is None
            or isinstance(code_raw, bool)
            or not isinstance(code_raw, int)
            or code_raw < 0
        ):
            return WeatherReadResult(
                status=WeatherReadStatus.PROVIDER_ERROR,
                error_message=(
                    "Missing or invalid non-negative integer 'weather_code' "
                    "in provider current weather"
                ),
                observed_at=obs_time,
            )

        wind_raw = current.get("wind_speed_10m")
        if (
            wind_raw is None
            or isinstance(wind_raw, bool)
            or not isinstance(wind_raw, (int, float))
            or not math.isfinite(wind_raw)
        ):
            return WeatherReadResult(
                status=WeatherReadStatus.PROVIDER_ERROR,
                error_message="Missing or non-finite 'wind_speed_10m' in provider current weather",
                observed_at=obs_time,
            )

        # Validate units for all 4 meteorological variables
        required_unit_keys = ("temperature_2m", "precipitation", "weather_code", "wind_speed_10m")
        for u_key in required_unit_keys:
            u_val = current_units.get(u_key)
            if not isinstance(u_val, str) or not u_val.strip():
                return WeatherReadResult(
                    status=WeatherReadStatus.PROVIDER_ERROR,
                    error_message=f"Missing or invalid unit for '{u_key}' in current_units",
                    observed_at=obs_time,
                )

        observation = WeatherObservation(
            location_id=self._config.location_id,
            temperature_2m=float(temp_raw),
            precipitation=float(precip_raw),
            weather_code=int(code_raw),
            wind_speed_10m=float(wind_raw),
            units={k: str(v) for k, v in current_units.items()},
            observed_at=obs_time,
            attribution=ProviderAttribution(),
            provenance=self._transport.provenance,
            provider_valid_time=time_raw,
        )

        return WeatherReadResult(
            status=WeatherReadStatus.MATCH,
            observation=observation,
            observed_at=obs_time,
        )

    def observe_weather(
        self,
        action: ValidatedActionContract | ActionContract,
        approval: ApprovalGrant | None = None,
        at: datetime | None = None,
    ) -> WeatherReadResult:
        """Alias for read_weather to support observation nomenclature."""
        return self.read_weather(action=action, approval=approval, at=at)


# Canonical alias
OpenMeteoObservationAdapter = OpenMeteoReadAdapter
