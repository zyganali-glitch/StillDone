"""Tests for Open-Meteo weather observation adapter.

Verifies:
- Weather location configuration validation and coordinate masking in repr/str.
- Canonical P-04 action contract validation (system, resource_kind, parent_id, empty params).
- Target matching against configured location_id.
- READ_ONLY authority policy enforcement (unexpected approval grant rejected).
- Attribution preservation (ProviderAttribution with CC BY 4.0).
- Transport boundary: FakeOpenMeteoTransport (FIXTURE) vs OpenMeteoHttpTransport (LIVE_EXTERNAL).
- Synthetic fake cannot claim or produce LIVE_EXTERNAL provenance.
- HTTP contract: URL parameters, User-Agent header, JSON parsing.
- Bounded timeout, rate limiting, and error sanitization (no coordinate or URL leakage).
- Zero promotion: observation success does NOT verify or promote state to READY.
"""

from __future__ import annotations

import io
import urllib.error
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stilldone.action_policy import ActionPolicyError
from stilldone.adapters.weather import (
    ATTRIBUTION_LICENSE,
    ATTRIBUTION_PROVIDER,
    ATTRIBUTION_TEXT,
    ATTRIBUTION_URL,
    CANONICAL_WEATHER_RESOURCE_KIND,
    CANONICAL_WEATHER_SYSTEM,
    FakeOpenMeteoTransport,
    OpenMeteoHttpTransport,
    OpenMeteoObservationAdapter,
    OpenMeteoReadAdapter,
    ProviderAttribution,
    WeatherConfigError,
    WeatherLocationConfig,
    WeatherObservation,
    WeatherRateLimitError,
    WeatherReadResult,
    WeatherReadStatus,
    WeatherTargetError,
    WeatherTimeoutError,
    WeatherTransport,
    _sanitize_weather_transport_error,
)
from stilldone.authority_policy import UnexpectedApprovalGrantError
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import ApprovalGrant, AuthorityClass
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance

TEST_LOCATION_ID = "loc-berlin-demo"
TEST_LATITUDE = 52.5200
TEST_LONGITUDE = 13.4050
TEST_TIMEZONE = "UTC"


def _make_weather_action(
    location_id: str = TEST_LOCATION_ID,
    parent_id: str | None = None,
    system: str = CANONICAL_WEATHER_SYSTEM,
    resource_kind: ResourceKind = CANONICAL_WEATHER_RESOURCE_KIND,
    action_type: ActionType = ActionType.WEATHER_READ,
    parameters: dict[str, Any] | None = None,
) -> ActionContract:
    return ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=action_type,
        target=TargetIdentity(
            system=system,
            resource_kind=resource_kind,
            resource_id=location_id,
            parent_id=parent_id,
        ),
        parameters=parameters or {},
    )


# ===========================================================================
# 1. Configuration Validation & Coordinate Masking
# ===========================================================================


def test_weather_location_config_valid() -> None:
    config = WeatherLocationConfig(
        location_id=TEST_LOCATION_ID,
        latitude=TEST_LATITUDE,
        longitude=TEST_LONGITUDE,
        timezone="Europe/Berlin",
    )
    assert config.location_id == TEST_LOCATION_ID
    assert config.latitude == TEST_LATITUDE
    assert config.longitude == TEST_LONGITUDE
    assert config.timezone == "Europe/Berlin"


@pytest.mark.parametrize(
    "loc_id,lat,lon,tz",
    [
        ("", 52.52, 13.40, "UTC"),  # empty location_id
        ("   ", 52.52, 13.40, "UTC"),  # whitespace location_id
        ("loc-1", 90.001, 13.40, "UTC"),  # latitude > 90
        ("loc-1", -90.001, 13.40, "UTC"),  # latitude < -90
        ("loc-1", 52.52, 180.001, "UTC"),  # longitude > 180
        ("loc-1", 52.52, -180.001, "UTC"),  # longitude < -180
        ("loc-1", 52.52, 13.40, ""),  # empty timezone
    ],
)
def test_weather_location_config_invalid(loc_id: str, lat: float, lon: float, tz: str) -> None:
    with pytest.raises(WeatherConfigError):
        WeatherLocationConfig(
            location_id=loc_id,
            latitude=lat,
            longitude=lon,
            timezone=tz,
        )


def test_weather_location_config_masks_coordinates_in_repr_and_str() -> None:
    config = WeatherLocationConfig(
        location_id="loc-secret-99",
        latitude=48.8566,
        longitude=2.3522,
        timezone="UTC",
    )
    repr_str = repr(config)
    str_val = str(config)

    assert "48.8566" not in repr_str
    assert "2.3522" not in repr_str
    assert "latitude=***" in repr_str
    assert "longitude=***" in repr_str
    assert "loc-secret-99" in repr_str

    assert "48.8566" not in str_val
    assert "2.3522" not in str_val


def test_weather_observation_masks_details_in_repr_and_str() -> None:
    obs = WeatherObservation(
        location_id=TEST_LOCATION_ID,
        temperature_2m=18.5,
        precipitation=0.0,
        weather_code=0,
        wind_speed_10m=5.2,
        units={"temperature_2m": "°C"},
        observed_at=datetime.now(UTC),
        attribution=ProviderAttribution(),
        provenance=EvidenceProvenance.FIXTURE,
    )
    s = str(obs)
    assert TEST_LOCATION_ID in s
    assert "18.5" in s
    assert "FIXTURE" in s
    # Coordinates must NOT exist in the observation model
    assert not hasattr(obs, "latitude")
    assert not hasattr(obs, "longitude")


# ===========================================================================
# 2. Canonical Action Contract & Target Validation
# ===========================================================================


def test_target_resource_id_mismatch_raises_target_error() -> None:
    config = WeatherLocationConfig(
        location_id="loc-berlin",
        latitude=52.52,
        longitude=13.41,
    )
    transport = FakeOpenMeteoTransport()
    adapter = OpenMeteoReadAdapter(config, transport)

    action = _make_weather_action(location_id="loc-paris")
    with pytest.raises(WeatherTargetError, match="does not match configured location_id"):
        adapter.read_weather(action)


def test_target_parent_id_must_be_none() -> None:
    config = WeatherLocationConfig(
        location_id=TEST_LOCATION_ID,
        latitude=TEST_LATITUDE,
        longitude=TEST_LONGITUDE,
    )
    transport = FakeOpenMeteoTransport()
    adapter = OpenMeteoReadAdapter(config, transport)

    action = _make_weather_action(parent_id="some-parent")
    with pytest.raises(
        WeatherTargetError, match="Target parent_id must be None for weather location observations"
    ):
        adapter.read_weather(action)


def test_wrong_system_rejected() -> None:
    config = WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE)
    adapter = OpenMeteoReadAdapter(config, FakeOpenMeteoTransport())
    action = _make_weather_action(system="google_weather")
    with pytest.raises(ActionPolicyError, match="requires target system 'open_meteo'"):
        adapter.read_weather(action)


def test_wrong_resource_kind_rejected() -> None:
    config = WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE)
    adapter = OpenMeteoReadAdapter(config, FakeOpenMeteoTransport())
    action = _make_weather_action(resource_kind=ResourceKind.TASK)
    with pytest.raises(ActionPolicyError, match="requires target resource kind 'weather_location'"):
        adapter.read_weather(action)


def test_unrequested_parameters_rejected() -> None:
    config = WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE)
    adapter = OpenMeteoReadAdapter(config, FakeOpenMeteoTransport())
    action = _make_weather_action(parameters={"units": "fahrenheit"})
    with pytest.raises(
        ActionPolicyError, match="does not accept parameters, but parameter 'units' was provided"
    ):
        adapter.read_weather(action)


def test_wrong_action_type_rejected_by_adapter() -> None:
    config = WeatherLocationConfig(
        location_id=TEST_LOCATION_ID,
        latitude=TEST_LATITUDE,
        longitude=TEST_LONGITUDE,
    )
    transport = FakeOpenMeteoTransport()
    adapter = OpenMeteoReadAdapter(config, transport)

    action = ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=ActionType.TASK_READ,
        target=TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id="task-123",
            parent_id="list-456",
        ),
        parameters={},
    )
    with pytest.raises(WeatherTargetError, match="OpenMeteoReadAdapter handles 'weather.read'"):
        adapter.read_weather(action)


# ===========================================================================
# 3. Authority Policy Enforcement (READ_ONLY, Approval = None)
# ===========================================================================


def test_unexpected_approval_grant_fails_closed() -> None:
    config = WeatherLocationConfig(
        location_id=TEST_LOCATION_ID,
        latitude=TEST_LATITUDE,
        longitude=TEST_LONGITUDE,
    )
    transport = FakeOpenMeteoTransport()
    adapter = OpenMeteoReadAdapter(config, transport)

    action = _make_weather_action()
    bogus_grant = ApprovalGrant.create(
        action=action,
        authority_class=AuthorityClass.READ_ONLY,
        issued_at=datetime.now(UTC),
        expires_at=datetime(2027, 1, 1, tzinfo=UTC),
    )

    with pytest.raises(UnexpectedApprovalGrantError):
        adapter.read_weather(action, approval=bogus_grant)

    # Transport must NOT have been called
    assert transport.reads_count == 0


def test_read_weather_authorized_without_approval() -> None:
    config = WeatherLocationConfig(
        location_id=TEST_LOCATION_ID,
        latitude=TEST_LATITUDE,
        longitude=TEST_LONGITUDE,
    )
    transport = FakeOpenMeteoTransport()
    adapter = OpenMeteoReadAdapter(config, transport)

    action = _make_weather_action()
    result = adapter.read_weather(action, approval=None)

    assert result.status == WeatherReadStatus.MATCH
    assert result.observation is not None
    assert transport.reads_count == 1


# ===========================================================================
# 4. Attribution Preservation & Normalized Observation
# ===========================================================================


def test_attribution_preservation() -> None:
    config = WeatherLocationConfig(
        location_id=TEST_LOCATION_ID,
        latitude=TEST_LATITUDE,
        longitude=TEST_LONGITUDE,
    )
    transport = FakeOpenMeteoTransport()
    adapter = OpenMeteoReadAdapter(config, transport)

    result = adapter.read_weather(_make_weather_action())
    assert result.observation is not None
    attr = result.observation.attribution

    assert attr.provider == ATTRIBUTION_PROVIDER
    assert attr.license == ATTRIBUTION_LICENSE
    assert attr.text == ATTRIBUTION_TEXT
    assert attr.url == ATTRIBUTION_URL


def test_observation_variables_normalized() -> None:
    config = WeatherLocationConfig(
        location_id=TEST_LOCATION_ID,
        latitude=TEST_LATITUDE,
        longitude=TEST_LONGITUDE,
    )
    transport = FakeOpenMeteoTransport(
        {
            "current_units": {
                "temperature_2m": "°C",
                "precipitation": "mm",
                "weather_code": "wmo code",
                "wind_speed_10m": "km/h",
            },
            "current": {
                "time": "2026-10-03T10:00",
                "temperature_2m": 14.2,
                "precipitation": 0.5,
                "weather_code": 61,
                "wind_speed_10m": 15.0,
            },
        }
    )
    adapter = OpenMeteoReadAdapter(config, transport)

    result = adapter.read_weather(_make_weather_action())
    assert result.status == WeatherReadStatus.MATCH
    assert result.observation is not None

    obs = result.observation
    assert obs.location_id == TEST_LOCATION_ID
    assert obs.temperature_2m == 14.2
    assert obs.precipitation == 0.5
    assert obs.weather_code == 61
    assert obs.wind_speed_10m == 15.0
    assert obs.units["temperature_2m"] == "°C"


# ===========================================================================
# 5. Provenance Separation: Fake (FIXTURE) vs Live (LIVE_EXTERNAL)
# ===========================================================================


def test_fake_transport_strictly_has_fixture_provenance() -> None:
    fake: WeatherTransport = FakeOpenMeteoTransport()
    assert fake.provenance == EvidenceProvenance.FIXTURE
    assert not fake.provenance.is_external_live

    config = WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE)
    adapter = OpenMeteoReadAdapter(config, fake)
    result = adapter.read_weather(_make_weather_action())

    assert result.observation is not None
    assert result.observation.provenance == EvidenceProvenance.FIXTURE
    assert not result.observation.provenance.is_external_live


def test_http_transport_has_live_external_provenance() -> None:
    http_transport = OpenMeteoHttpTransport()
    assert http_transport.provenance == EvidenceProvenance.LIVE_EXTERNAL
    assert http_transport.provenance.is_external_live


def test_observation_rejects_non_evidence_provenance() -> None:
    with pytest.raises(TypeError, match="provenance must be an EvidenceProvenance instance"):
        WeatherObservation(
            location_id=TEST_LOCATION_ID,
            temperature_2m=15.0,
            precipitation=0.0,
            weather_code=0,
            wind_speed_10m=5.0,
            units={},
            observed_at=datetime.now(UTC),
            attribution=ProviderAttribution(),
            provenance="LIVE_EXTERNAL",  # type: ignore[arg-type]
        )


# ===========================================================================
# 6. HTTP Transport Contract, Parsing, & Headers
# ===========================================================================


@patch("urllib.request.urlopen")
def test_http_transport_sends_correct_params_and_headers(mock_urlopen: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = (
        b'{"current_units": {"temperature_2m": "\xc2\xb0C"}, '
        b'"current": {"temperature_2m": 12.5, "precipitation": 0.0, '
        b'"weather_code": 1, "wind_speed_10m": 8.0}}'
    )
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    transport = OpenMeteoHttpTransport()
    res = transport.fetch_current_weather(52.52, 13.41, timezone="UTC")

    assert mock_urlopen.call_count == 1
    req = mock_urlopen.call_args[0][0]
    assert req.method == "GET"
    assert "latitude=52.520000" in req.full_url
    assert "longitude=13.410000" in req.full_url
    assert "timezone=UTC" in req.full_url
    assert "current=" in req.full_url
    assert "StillDone" in req.headers.get("User-agent", "")
    assert res["current"]["temperature_2m"] == 12.5


# ===========================================================================
# 7. Bounded Timeout, Rate Limiting, & Error Sanitization
# ===========================================================================


@patch("urllib.request.urlopen")
def test_http_transport_timeout_raises_weather_timeout_error(mock_urlopen: MagicMock) -> None:
    mock_urlopen.side_effect = TimeoutError("Connection timed out")

    transport = OpenMeteoHttpTransport()
    with pytest.raises(WeatherTimeoutError, match="Open-Meteo request timed out"):
        transport.fetch_current_weather(52.52, 13.41)


@patch("urllib.request.urlopen")
def test_http_transport_429_rate_limit(mock_urlopen: MagicMock) -> None:
    err = urllib.error.HTTPError(
        url="https://api.open-meteo.com/v1/forecast?secret=123",
        code=429,
        msg="Too Many Requests",
        hdrs=MagicMock(),
        fp=io.BytesIO(b"Rate limit exceeded"),
    )
    mock_urlopen.side_effect = err

    transport = OpenMeteoHttpTransport()
    with pytest.raises(WeatherRateLimitError, match="rate limit exceeded") as exc_info:
        transport.fetch_current_weather(52.52, 13.41)

    assert exc_info.value.status_code == 429
    # Sanitized message must not leak full URL
    sanitized = _sanitize_weather_transport_error(exc_info.value)
    assert "secret=123" not in sanitized


def test_sanitized_error_masks_coordinates_and_urls() -> None:
    raw_exc = Exception("Failed at https://api.open-meteo.com/?lat=52.52&lon=13.41: socket error")
    sanitized = _sanitize_weather_transport_error(raw_exc)
    assert "lat=52.52" not in sanitized
    assert "lon=13.41" not in sanitized
    assert "Unexpected weather transport failure" in sanitized


def test_adapter_handles_transport_error_gracefully() -> None:
    config = WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE)
    transport = FakeOpenMeteoTransport()
    transport.simulate_error = WeatherTimeoutError("Request timed out")
    adapter = OpenMeteoReadAdapter(config, transport)

    result = adapter.read_weather(_make_weather_action())
    assert result.status == WeatherReadStatus.PROVIDER_ERROR
    assert result.observation is None
    assert result.error_message == "Open-Meteo request timed out"


# ===========================================================================
# 8. Zero Promotion: Observation Only (Does NOT Verify or Mark READY)
# ===========================================================================


def test_zero_promotion_invariant() -> None:
    config = WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE)
    transport = FakeOpenMeteoTransport()
    adapter = OpenMeteoReadAdapter(config, transport)

    result = adapter.read_weather(_make_weather_action())

    # Result is a WeatherReadResult, NOT a VerificationResult, NOT a Receipt, NOT READY
    assert isinstance(result, WeatherReadResult)
    assert result.status == WeatherReadStatus.MATCH
    assert not hasattr(result, "is_verified")
    assert not hasattr(result, "is_ready")
    assert not hasattr(result, "mission_status")
    assert not hasattr(result.observation, "is_verified")


def test_observe_weather_alias_and_adapter_alias() -> None:
    config = WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE)
    transport = FakeOpenMeteoTransport()
    adapter = OpenMeteoObservationAdapter(config, transport)

    action = _make_weather_action()
    res1 = adapter.read_weather(action)
    res2 = adapter.observe_weather(action)

    assert res1.status == WeatherReadStatus.MATCH
    assert res2.status == WeatherReadStatus.MATCH
    assert res1.observation is not None
    assert res2.observation is not None
