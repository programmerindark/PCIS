"""Ecowitt sensor ingestion.

Reads live temperature/humidity from an Ecowitt gateway (e.g. a WittBoy
array on a GW1100/GW2000/GW3000) so PCIS can use MEASURED house
conditions instead of typed estimates.

Two routes are supported:

* **Cloud** (`api.ecowitt.net/api/v3/device/real_time`) -- needs an
  Application Key, an API Key and the device MAC, all obtainable from
  the user's ecowitt.net account. Works from anywhere, which matters
  because PCIS is cloud-hosted and the farm is not.
* **Local** (`http://<gateway-ip>/get_livedata_info`) -- no keys, but
  only reachable on the farm LAN, and the endpoint is undocumented so a
  firmware update could change it. Offered as a fallback for on-site use.

Honesty note: PCIS treats these as MEASUREMENTS and never silently
substitutes them for a model output. Where a measurement and a model
prediction disagree (e.g. predicted vs measured indoor RH), both are
reported -- the gap is diagnostic information, not an error to hide.

Placement note -- read this before trusting any reading
------------------------------------------------------
Ecowitt names its data blocks after the SENSOR TYPE, not where you hung
the hardware:

* the "outdoor" block is the WS90 / WittBoy array
* the "indoor" block is the probe in the gateway console

A two-module install can be mounted either way round, and on this farm it
IS reversed: the WS90 array hangs INSIDE the house and the gateway console
sits OUTSIDE. So Ecowitt's "outdoor" block is the house, and its "indoor"
block is ambient.

PCIS therefore never infers placement from the block name. The caller
declares which block is physically inside and which is outside, and this
module speaks only in terms of `inside_*` / `outside_*`. Getting this
backwards silently inverts the entire moisture balance -- the model would
believe it can dehumidify by ventilating when in fact the outside air is
wetter -- so it is stated explicitly rather than defaulted quietly.
"""

from __future__ import annotations

from typing import Any

import httpx

CLOUD_URL = "https://api.ecowitt.net/api/v3/device/real_time"
DEVICE_LIST_URL = "https://api.ecowitt.net/api/v3/device/list"
_TIMEOUT = 12.0


def _num(v: Any) -> float | None:
    """Ecowitt returns values as strings; be forgiving about shape."""
    if v is None:
        return None
    if isinstance(v, dict):          # {"time":..,"unit":..,"value":".."}
        v = v.get("value")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _extract_block(block: dict | None) -> dict:
    """Pull temperature/humidity out of one Ecowitt sensor block."""
    if not isinstance(block, dict):
        return {}
    out: dict[str, float] = {}
    t = _num(block.get("temperature"))
    h = _num(block.get("humidity"))
    if t is not None:
        out["temperature_c"] = round(t, 1)
    if h is not None:
        out["humidity_pct"] = round(h, 0)
    return out


def parse_pressure_hpa(payload: dict) -> float | None:
    """Barometric pressure in hPa, if the gateway reports it.

    Worth extracting: PCIS psychrometrics default to sea-level pressure,
    but humidity ratio and moist-air density both scale with total
    pressure. A house well above sea level holds noticeably more water
    per kg of dry air than the sea-level tables suggest, and its thinner
    air carries less heat per cubic metre a fan moves.
    """
    data = payload.get("data") or {}
    press = data.get("pressure") or {}
    if not isinstance(press, dict):
        return None
    # "relative" is corrected to sea level; "absolute" is what the house
    # actually sits at, which is the one psychrometrics needs.
    for key in ("absolute", "relative"):
        v = _num(press.get(key))
        if v is not None:
            return round(v, 1)
    return None


def parse_cross_checks(payload: dict) -> dict:
    """Values Ecowitt computes itself, kept as INDEPENDENT checks.

    The gateway publishes its own dew point and vapour-pressure deficit.
    PCIS never uses these in place of its own psychrometrics -- they are
    reported alongside so a disagreement is visible rather than hidden.
    """
    data = payload.get("data") or {}
    out: dict[str, float] = {}
    for block in ("outdoor", "indoor"):
        b = data.get(block)
        if not isinstance(b, dict):
            continue
        dp = _num(b.get("dew_point"))
        if dp is not None:
            out[f"{block}_dew_point_c"] = round(dp, 1)
    wind = data.get("wind") or {}
    if isinstance(wind, dict):
        ws = _num(wind.get("wind_speed"))
        if ws is not None:
            # Ecowitt returns mph on this account's unit settings.
            out["wind_speed_mps"] = round(ws * 0.44704, 2)
            # The anemometer lives on the WS90. With that array mounted
            # inside the house there is no wind for it to read except the
            # air the fans are moving -- i.e. tunnel velocity. Reported
            # separately so the engine's computed air speed can be checked
            # against a measurement instead of trusted on faith.
            out["measured_air_speed_mps"] = round(ws * 0.44704, 2)
    return out


def parse_cloud_response(payload: dict) -> dict:
    """Normalise the cloud response into plain blocks we understand."""
    data = payload.get("data") or {}
    blocks: dict[str, dict] = {}
    for name in ("indoor", "outdoor"):
        b = _extract_block(data.get(name))
        if b:
            blocks[name] = b
    # Some gateways expose extra channels (WH31 etc.) as temp_and_humidity_chN
    for key, val in data.items():
        if key.startswith("temp_and_humidity_ch"):
            b = _extract_block(val)
            if b:
                blocks[key] = b
    return blocks


def _shape_only(obj, depth: int = 0):
    """Describe a payload's STRUCTURE and values without echoing secrets.

    Used for the debug view so an operator can share what their gateway
    returned (which blocks exist, what the readings are) without pasting
    Application/API keys anywhere.
    """
    if depth > 4:
        return "..."
    if isinstance(obj, dict):
        return {k: _shape_only(v, depth + 1) for k, v in obj.items()
                if k not in ("application_key", "api_key")}
    if isinstance(obj, list):
        return [_shape_only(v, depth + 1) for v in obj[:3]]
    return obj


async def fetch_cloud(
    application_key: str,
    api_key: str,
    mac: str,
    include_raw: bool = False,
) -> dict:
    """Fetch current readings from the Ecowitt cloud API.

    Returns {"blocks": {...}, "raw_code": int, "message": str}.
    Raises httpx.HTTPError on transport failure.
    """
    params = {
        "application_key": "".join(application_key.split()),
        "api_key": "".join(api_key.split()),
        "mac": "".join(mac.split()),
        "call_back": "all",
        "temp_unitid": 1,      # Celsius
        "pressure_unitid": 3,  # hPa
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(CLOUD_URL, params=params)
        r.raise_for_status()
        payload = r.json()

    code = payload.get("code")
    if code not in (0, "0"):
        return {
            "blocks": {},
            "raw_code": code,
            "message": payload.get("msg") or "Ecowitt rejected the request "
                                             "(check Application Key, API Key and MAC).",
        }
    out = {
        "blocks": parse_cloud_response(payload),
        "pressure_hpa": parse_pressure_hpa(payload),
        "cross_checks": parse_cross_checks(payload),
        "raw_code": 0,
        "message": "ok",
    }
    if include_raw:
        out["raw"] = _shape_only(payload.get("data") or {})
    return out


async def fetch_local(gateway_ip: str) -> dict:
    """Fetch from the gateway's undocumented local endpoint.

    Only works on the same LAN as the gateway. The response shape differs
    from the cloud API (a list of sensor rows), so it is parsed separately.
    """
    url = f"http://{gateway_ip}/get_livedata_info"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(url)
        r.raise_for_status()
        payload = r.json()

    blocks: dict[str, dict] = {}
    # Common shape: {"common_list":[{"id":"0x02","val":"24.5"},...],
    #                "wh25":[{"intemp":"25.1","inhumi":"60"}]}
    for row in payload.get("wh25", []) or []:
        b: dict[str, float] = {}
        t = _num(row.get("intemp"))
        h = _num(str(row.get("inhumi", "")).replace("%", ""))
        if t is not None:
            b["temperature_c"] = round(t, 1)
        if h is not None:
            b["humidity_pct"] = round(h, 0)
        if b:
            blocks["indoor"] = b

    outdoor: dict[str, float] = {}
    for item in payload.get("common_list", []) or []:
        ident = str(item.get("id", ""))
        val = _num(item.get("val"))
        if val is None:
            continue
        if ident in ("0x02", "outtemp"):       # outdoor temperature
            outdoor["temperature_c"] = round(val, 1)
        elif ident in ("0x07", "outhumi"):     # outdoor humidity
            outdoor["humidity_pct"] = round(val, 0)
    if outdoor:
        blocks["outdoor"] = outdoor
    return {"blocks": blocks, "raw_code": 0, "message": "ok"}


def select_house_conditions(
    blocks: dict,
    indoor_block: str = "outdoor",
    outdoor_block: str | None = None,
) -> dict:
    """Map Ecowitt's sensor-type block names onto PHYSICAL placement.

    `indoor_block` names the block whose hardware is inside the house;
    `outdoor_block` names the one outside. Defaults reflect this farm's
    reversed two-module install (see module docstring), but both are
    explicit parameters because the consequence of getting them backwards
    is an inverted moisture balance, not a cosmetic label error.

    When both blocks resolve, PCIS has MEASURED supply-air conditions and
    no longer needs a weather forecast for the current moment.
    """
    if outdoor_block is None:
        # The other block, whichever it is -- with two modules the one
        # that is not inside is by definition the one outside.
        others = [b for b in blocks if b != indoor_block]
        outdoor_block = others[0] if len(others) == 1 else None

    inside = blocks.get(indoor_block) or {}
    outside = blocks.get(outdoor_block) if outdoor_block else None
    outside = outside or {}

    return {
        "indoor_t_c": inside.get("temperature_c"),
        "indoor_rh_pct": inside.get("humidity_pct"),
        "outdoor_t_c": outside.get("temperature_c"),
        "outdoor_rh_pct": outside.get("humidity_pct"),
        "source_block": indoor_block if inside else None,
        "outdoor_source_block": outdoor_block if outside else None,
        "outdoor_measured": bool(outside),
        "available_blocks": sorted(blocks),
    }


async def list_devices(application_key: str, api_key: str) -> dict:
    """List the devices on this Ecowitt account.

    Saves the operator hunting for a MAC address: with just the two keys
    we can show every gateway on the account and let them pick one.
    """
    params = {"application_key": "".join(application_key.split()),
              "api_key": "".join(api_key.split())}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(DEVICE_LIST_URL, params=params)
        r.raise_for_status()
        payload = r.json()

    if payload.get("code") not in (0, "0"):
        return {"devices": [], "message": payload.get("msg") or "Ecowitt rejected the keys."}

    data = payload.get("data") or {}
    rows = data.get("list") if isinstance(data, dict) else data
    devices = []
    for d in rows or []:
        if not isinstance(d, dict):
            continue
        devices.append({
            "name": d.get("name") or d.get("stationtype") or "Ecowitt device",
            "mac": d.get("mac") or d.get("imei"),
            "type": d.get("stationtype") or d.get("type"),
            "last_update": d.get("createtime") or d.get("last_update"),
        })
    return {"devices": [d for d in devices if d["mac"]], "message": "ok"}
