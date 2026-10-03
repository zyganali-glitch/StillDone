# P-06.06 Live Weather Observation Evidence

## 1. Summary

- **Task**: P-06.06 — Implement Open-Meteo live observation adapter with attribution
- **System**: `open_meteo`
- **Action Type**: `ActionType.WEATHER_READ` (`weather.read`)
- **Resource Kind**: `ResourceKind.WEATHER_LOCATION` (`weather_location`)
- **Authority**: `AuthorityClass.READ_ONLY` (`approval=None`)
- **Execution Timestamp**: `2026-10-03T07:17:34.245258+00:00`
- **Personal Spend Delta**: `$0.00` (Open-Meteo free non-commercial tier; zero billing risk)
- **Call Bounding**: Exactly 1 HTTPS GET request executed
- **Provenance**: `LIVE_EXTERNAL`

---

## 2. Configuration & Sanitized Parameters

Public non-personal demo location used:
- **Location ID**: `loc-demo-berlin-public`
- **Coordinates**: Public reference coordinates (Berlin public reference)
- **Timezone**: `UTC`
- **Requested Variables**: `temperature_2m,precipitation,weather_code,wind_speed_10m`

---

## 3. Observed Payload & Normalization

```json
{
  "status": "MATCH",
  "observation": {
    "location_id": "loc-demo-berlin-public",
    "temperature_2m": 14.1,
    "precipitation": 0.0,
    "weather_code": 3,
    "wind_speed_10m": 2.7,
    "units": {
      "temperature_2m": "°C",
      "precipitation": "mm",
      "weather_code": "wmo code",
      "wind_speed_10m": "km/h"
    },
    "observed_at": "2026-10-03T07:17:34.245258+00:00",
    "provenance": "LIVE_EXTERNAL",
    "attribution": {
      "provider": "Open-Meteo",
      "license": "CC BY 4.0",
      "text": "Weather data by Open-Meteo.com",
      "url": "https://open-meteo.com/"
    }
  }
}
```

---

## 4. Attribution Compliance

In compliance with Open-Meteo terms of service and CC BY 4.0 license requirements:
- **Attribution Provider**: `Open-Meteo`
- **License**: `CC BY 4.0`
- **Attribution Notice**: `Weather data by Open-Meteo.com`
- **Website**: `https://open-meteo.com/`

---

## 5. Architectural & Security Invariants

1. **Zero Promotion**:
   - The live observation is recorded as a `WeatherObservation` with `status=MATCH`.
   - It is an observation ONLY.
   - It does NOT assert or imply `VERIFIED` or `READY`.
2. **Privacy Minimization**:
   - Durable observation stores `location_id`, variables, units, and timestamps.
   - Exact coordinates are omitted from the durable observation record.
   - `WeatherLocationConfig` coordinates are masked in `__repr__` and `__str__`.
3. **Fail-Closed Authority**:
   - `WEATHER_READ` is `READ_ONLY`.
   - Any unexpected `ApprovalGrant` fails closed with `UnexpectedApprovalGrantError`.
4. **Transport Provenance Integrity**:
   - Synthetic fake transports report `FIXTURE`.
   - Real HTTP transports report `LIVE_EXTERNAL`.
   - Fakes cannot falsely produce or claim `LIVE_EXTERNAL` evidence.
5. **Zero Personal Spend**:
   - Under free non-commercial Open-Meteo terms (up to 10,000 calls/day).
   - Total personal spend: `$0.00`.
