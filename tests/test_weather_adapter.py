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
import json
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
    CANONICAL_OPEN_METEO_ENDPOINT,
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
    WeatherTransportError,
    _sanitize_weather_transport_error,
    validate_open_meteo_endpoint,
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
    assert "loc-secret-99" not in repr_str
    assert "location_id='***'" in repr_str

    assert "48.8566" not in str_val
    assert "2.3522" not in str_val
    assert "loc-secret-99" not in str_val
    assert "location_id='***'" in str_val


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
    assert TEST_LOCATION_ID not in s
    assert "location_id='***'" in s
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
    with pytest.raises(
        WeatherTargetError, match="Target resource_id does not match configured location scope"
    ):
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


# ===========================================================================
# 9. Endpoint Lock & SSRF / Downgrade Rejection (P-06.06 Repair Defect A)
# ===========================================================================


class TestCanonicalEndpointValidation:
    def test_canonical_endpoint_accepted(self) -> None:
        assert (
            validate_open_meteo_endpoint(CANONICAL_OPEN_METEO_ENDPOINT)
            == CANONICAL_OPEN_METEO_ENDPOINT
        )
        transport = OpenMeteoHttpTransport()
        assert transport.endpoint == CANONICAL_OPEN_METEO_ENDPOINT

    @pytest.mark.parametrize(
        "bad_url,match_text",
        [
            ("http://api.open-meteo.com/v1/forecast", "HTTPS scheme"),
            ("https://attacker.com/v1/forecast", "api.open-meteo.com"),
            ("https://api.open-meteo.com.attacker.com/v1/forecast", "api.open-meteo.com"),
            ("https://sub.api.open-meteo.com/v1/forecast", "api.open-meteo.com"),
            ("https://user:pass@api.open-meteo.com/v1/forecast", "credentials"),
            ("https://api.open-meteo.com:8443/v1/forecast", "alternate port"),
            ("https://api.open-meteo.com/v2/forecast", "/v1/forecast"),
            ("https://api.open-meteo.com/v1/forecast?injected=true", "query parameters"),
            ("https://api.open-meteo.com/v1/forecast#frag", "fragments"),
            ("", "non-empty string"),
        ],
    )
    def test_invalid_endpoints_fail_closed(self, bad_url: str, match_text: str) -> None:
        with pytest.raises(WeatherTransportError, match=match_text):
            validate_open_meteo_endpoint(bad_url)

        with pytest.raises(WeatherTransportError, match=match_text):
            OpenMeteoHttpTransport(endpoint=bad_url)


# ===========================================================================
# 10. Location Privacy & Hostile Sentinels (P-06.06 Repair Defect B)
# ===========================================================================


class TestLocationPrivacyAndSentinels:
    SENTINEL_LOCATION_ID = "SENTINEL_CLASSIFIED_LOCATION_ALPHA_42"

    def test_sentinel_location_id_never_leaks_in_repr_or_str(self) -> None:
        config = WeatherLocationConfig(
            location_id=self.SENTINEL_LOCATION_ID,
            latitude=52.52,
            longitude=13.41,
        )
        assert self.SENTINEL_LOCATION_ID not in repr(config)
        assert self.SENTINEL_LOCATION_ID not in str(config)
        assert "location_id='***'" in repr(config)

        obs = WeatherObservation(
            location_id=self.SENTINEL_LOCATION_ID,
            temperature_2m=20.0,
            precipitation=0.0,
            weather_code=0,
            wind_speed_10m=5.0,
            units={"temperature_2m": "°C"},
            observed_at=datetime.now(UTC),
            attribution=ProviderAttribution(),
            provenance=EvidenceProvenance.FIXTURE,
            provider_valid_time="2026-10-03T10:00:00Z",
        )
        assert self.SENTINEL_LOCATION_ID not in repr(obs)
        assert self.SENTINEL_LOCATION_ID not in str(obs)
        assert "location_id='***'" in repr(obs)

    def test_target_mismatch_error_message_is_generic_without_leakage(self) -> None:
        config = WeatherLocationConfig(
            location_id=self.SENTINEL_LOCATION_ID,
            latitude=52.52,
            longitude=13.41,
        )
        transport = FakeOpenMeteoTransport()
        adapter = OpenMeteoReadAdapter(config, transport)

        hostile_supplied_id = "HOSTILE_SUPPLIED_TARGET_LOCATION_ID_99"
        action = _make_weather_action(location_id=hostile_supplied_id)

        with pytest.raises(WeatherTargetError) as exc_info:
            adapter.read_weather(action)

        err_msg = str(exc_info.value)
        assert err_msg == "Target resource_id does not match configured location scope"
        assert self.SENTINEL_LOCATION_ID not in err_msg
        assert hostile_supplied_id not in err_msg


# ===========================================================================
# 11. Strict Provider Schema Validation (P-06.06 Repair Defect C)
# ===========================================================================


class TestStrictProviderSchemaValidation:
    @pytest.fixture
    def base_valid_canned(self) -> dict[str, Any]:
        return {
            "current_units": {
                "temperature_2m": "°C",
                "precipitation": "mm",
                "weather_code": "wmo code",
                "wind_speed_10m": "km/h",
            },
            "current": {
                "time": "2026-10-03T10:00:00Z",
                "temperature_2m": 16.5,
                "precipitation": 0.2,
                "weather_code": 2,
                "wind_speed_10m": 11.0,
            },
        }

    def test_missing_temperature_produces_provider_error(
        self, base_valid_canned: dict[str, Any]
    ) -> None:
        canned = json.loads(json.dumps(base_valid_canned))
        del canned["current"]["temperature_2m"]
        adapter = OpenMeteoReadAdapter(
            WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE),
            FakeOpenMeteoTransport(canned),
        )
        res = adapter.read_weather(_make_weather_action())
        assert res.status == WeatherReadStatus.PROVIDER_ERROR
        assert res.observation is None
        assert "temperature_2m" in str(res.error_message)

    def test_missing_unit_produces_provider_error(self, base_valid_canned: dict[str, Any]) -> None:
        canned = json.loads(json.dumps(base_valid_canned))
        del canned["current_units"]["wind_speed_10m"]
        adapter = OpenMeteoReadAdapter(
            WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE),
            FakeOpenMeteoTransport(canned),
        )
        res = adapter.read_weather(_make_weather_action())
        assert res.status == WeatherReadStatus.PROVIDER_ERROR
        assert res.observation is None
        assert "wind_speed_10m" in str(res.error_message)

    def test_nan_or_inf_produces_provider_error(self, base_valid_canned: dict[str, Any]) -> None:
        for bad_val in (float("nan"), float("inf"), float("-inf")):
            canned = json.loads(json.dumps(base_valid_canned))
            canned["current"]["temperature_2m"] = bad_val
            adapter = OpenMeteoReadAdapter(
                WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE),
                FakeOpenMeteoTransport(canned),
            )
            res = adapter.read_weather(_make_weather_action())
            assert res.status == WeatherReadStatus.PROVIDER_ERROR
            assert res.observation is None

    def test_null_field_produces_provider_error(self, base_valid_canned: dict[str, Any]) -> None:
        canned = json.loads(json.dumps(base_valid_canned))
        canned["current"]["precipitation"] = None
        adapter = OpenMeteoReadAdapter(
            WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE),
            FakeOpenMeteoTransport(canned),
        )
        res = adapter.read_weather(_make_weather_action())
        assert res.status == WeatherReadStatus.PROVIDER_ERROR
        assert res.observation is None

    def test_missing_current_units_produces_provider_error(
        self, base_valid_canned: dict[str, Any]
    ) -> None:
        canned = json.loads(json.dumps(base_valid_canned))
        del canned["current_units"]
        adapter = OpenMeteoReadAdapter(
            WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE),
            FakeOpenMeteoTransport(canned),
        )
        res = adapter.read_weather(_make_weather_action())
        assert res.status == WeatherReadStatus.PROVIDER_ERROR
        assert res.observation is None

    def test_invalid_time_format_produces_provider_error(
        self, base_valid_canned: dict[str, Any]
    ) -> None:
        canned = json.loads(json.dumps(base_valid_canned))
        canned["current"]["time"] = "not-a-valid-iso-timestamp"
        adapter = OpenMeteoReadAdapter(
            WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE),
            FakeOpenMeteoTransport(canned),
        )
        res = adapter.read_weather(_make_weather_action())
        assert res.status == WeatherReadStatus.PROVIDER_ERROR
        assert res.observation is None

    def test_valid_payload_preserves_provider_valid_time(
        self, base_valid_canned: dict[str, Any]
    ) -> None:
        adapter = OpenMeteoReadAdapter(
            WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE),
            FakeOpenMeteoTransport(base_valid_canned),
        )
        res = adapter.read_weather(_make_weather_action())
        assert res.status == WeatherReadStatus.MATCH
        assert res.observation is not None
        assert res.observation.provider_valid_time == "2026-10-03T10:00:00Z"


# ===========================================================================
# 12. Truthful Observation Timing (P-06.06 Repair Defect D)
# ===========================================================================


class TestTruthfulObservationTiming:
    PAST_AT = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)
    FUTURE_AT = datetime(2099, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_observed_at_runtime_owned_not_forged_by_caller_at(self) -> None:
        config = WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE)
        transport = FakeOpenMeteoTransport()
        adapter = OpenMeteoReadAdapter(config, transport)

        res_past = adapter.read_weather(_make_weather_action(), at=self.PAST_AT)
        assert res_past.status == WeatherReadStatus.MATCH
        assert res_past.observed_at != self.PAST_AT
        assert res_past.observed_at.year >= 2026
        assert res_past.observation is not None
        assert res_past.observation.observed_at != self.PAST_AT
        assert res_past.observation.observed_at.year >= 2026

        res_future = adapter.read_weather(_make_weather_action(), at=self.FUTURE_AT)
        assert res_future.status == WeatherReadStatus.MATCH
        assert res_future.observed_at != self.FUTURE_AT
        assert res_future.observed_at.year >= 2026

    def test_provider_error_observed_at_runtime_owned(self) -> None:
        config = WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE)
        transport = FakeOpenMeteoTransport()
        transport.simulate_error = RuntimeError("network outage")
        adapter = OpenMeteoReadAdapter(config, transport)

        res = adapter.read_weather(_make_weather_action(), at=self.PAST_AT)
        assert res.status == WeatherReadStatus.PROVIDER_ERROR
        assert res.observed_at != self.PAST_AT
        assert res.observed_at.year >= 2026


# ===========================================================================
# 13. Closed-World Live Provenance (P-06.06 Repair Defect E)
# ===========================================================================


class TestClosedWorldProvenance:
    def test_fake_transport_produces_fixture(self) -> None:
        transport = FakeOpenMeteoTransport()
        assert transport.provenance == EvidenceProvenance.FIXTURE

    def test_http_transport_produces_live_external(self) -> None:
        transport = OpenMeteoHttpTransport()
        assert transport.provenance == EvidenceProvenance.LIVE_EXTERNAL

    def test_custom_transport_claiming_live_external_fails_closed(self) -> None:
        class RogueTransport:
            @property
            def provenance(self) -> EvidenceProvenance:
                return EvidenceProvenance.LIVE_EXTERNAL

            def fetch_current_weather(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                return {}

        rogue = RogueTransport()
        config = WeatherLocationConfig(TEST_LOCATION_ID, TEST_LATITUDE, TEST_LONGITUDE)

        with pytest.raises(
            WeatherConfigError,
            match="Only verified OpenMeteoHttpTransport may assert LIVE_EXTERNAL provenance",
        ):
            OpenMeteoReadAdapter(config, rogue)


# ===========================================================================
# 14. Live Weather Repair Evidence File Check
# ===========================================================================


def test_live_weather_repair_evidence_document_exists_and_valid() -> None:
    from pathlib import Path

    evidence_path = Path("docs/P06_06_LIVE_WEATHER_REPAIR_EVIDENCE.md")
    assert evidence_path.is_file(), "Live weather repair evidence doc must exist"
    content = evidence_path.read_text(encoding="utf-8")
    assert "RECORDED_LIVE" in content
    assert "Open-Meteo" in content
    assert "CC BY 4.0" in content
    assert "$0.00" in content
    assert "provider_valid_time" in content
    assert "temperature_2m" in content
    assert "wind_speed_10m" in content
