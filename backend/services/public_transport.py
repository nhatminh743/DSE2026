import httpx
from typing import Optional, Dict, Any, List
from app.config import settings

MODE_MAP = {
    "public_transport": "transit",
    "transit": "transit",
    "motorbike": "two_wheeler",
    "two_wheeler": "two_wheeler",
    "car": "driving",
    "driving": "driving",
}

FUEL_API_URL = "https://vietfuel-api.tranqui.workers.dev/api/fuel-prices/province/ha-noi"
MOTORBIKE_L_PER_100KM = 3.01
CAR_L_PER_100KM = 8.5


def normalize_transport_mode(transport_mode: str) -> Optional[str]:
    if not transport_mode:
        return None
    return MODE_MAP.get(transport_mode.lower())


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        cleaned = value.strip().replace(" ", "")
        for token in ["VND", "vnd", "₫", "đ", "d"]:
            cleaned = cleaned.replace(token, "")

        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            parts = cleaned.split(",")
            if len(parts[-1]) == 3:
                cleaned = "".join(parts)
            else:
                cleaned = ".".join(parts)
        elif "." in cleaned:
            parts = cleaned.split(".")
            if len(parts[-1]) == 3:
                cleaned = "".join(parts)

        try:
            return float(cleaned)
        except ValueError:
            return None

    return None


def _extract_fuel_price_candidates(payload: Any, path: str = "") -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    if isinstance(payload, dict):
        for key, value in payload.items():
            next_path = f"{path}.{key}" if path else key
            lower_key = key.lower()

            if any(token in lower_key for token in ["price", "gia", "ron95", "gasoline", "petrol"]):
                numeric = _to_float(value)
                if numeric is not None:
                    candidates.append({"path": next_path.lower(), "value": numeric})

            candidates.extend(_extract_fuel_price_candidates(value, next_path))

    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            candidates.extend(_extract_fuel_price_candidates(item, f"{path}[{idx}]"))

    return candidates


def _pick_hanoi_fuel_price(payload: Dict[str, Any]) -> Optional[float]:
    candidates = _extract_fuel_price_candidates(payload)
    if not candidates:
        return None

    preferred_tokens = ["ron95", "xang", "gasoline", "petrol"]

    filtered = [
        c for c in candidates
        if 5000 <= c["value"] <= 50000
    ]
    if not filtered:
        return None

    for token in preferred_tokens:
        preferred = [c for c in filtered if token in c["path"]]
        if preferred:
            return preferred[0]["value"]

    return filtered[0]["value"]


async def _get_hanoi_fuel_price(client: httpx.AsyncClient) -> Dict[str, Any]:
    try:
        response = await client.get(FUEL_API_URL)
        response.raise_for_status()
        payload = response.json()
        extracted = _pick_hanoi_fuel_price(payload)
        if extracted is None:
            return {
                "fuel_price_vnd_per_liter": settings.GAS_PRICE_PER_LITER,
                "fuel_price_source": "fallback_default",
                "fuel_price_reason": "Could not parse fuel price from API payload",
            }

        return {
            "fuel_price_vnd_per_liter": extracted,
            "fuel_price_source": FUEL_API_URL,
            "fuel_price_reason": None,
        }
    except Exception as exc:
        return {
            "fuel_price_vnd_per_liter": settings.GAS_PRICE_PER_LITER,
            "fuel_price_source": "fallback_default",
            "fuel_price_reason": f"Fuel API error: {exc}",
        }


async def fetch_transport_details(origin_str: str, dest_str: str, transport_mode: str) -> Dict[str, Any]:
    google_mode = normalize_transport_mode(transport_mode)
    if not google_mode:
        return _get_transport_fallback(f"Unsupported transport mode: {transport_mode}", transport_mode)

    return await _fetch_google_directions(origin_str, dest_str, google_mode, transport_mode)


async def fetch_transit_details(origin_str: str, dest_str: str) -> Dict[str, Any]:
    # Backward-compatible wrapper for old callers.
    return await fetch_transport_details(origin_str, dest_str, "transit")


async def _fetch_google_directions(
    origin_str: str,
    dest_str: str,
    google_mode: str,
    requested_mode: str,
) -> Dict[str, Any]:    
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": origin_str,
        "destination": dest_str,
        "mode": google_mode,
        "key": settings.GOOGLE_MAPS_API_KEY,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, params=params)
            data = response.json()

            if data.get("status") != "OK":
                # two_wheeler may be unsupported in some regions; fallback to driving.
                if google_mode == "two_wheeler":
                    retry_params = dict(params)
                    retry_params["mode"] = "driving"
                    retry_response = await client.get(url, params=retry_params)
                    retry_data = retry_response.json()
                    if retry_data.get("status") != "OK":
                        return _get_transport_fallback(
                            f"Google Maps status: {retry_data.get('status')}",
                            requested_mode,
                        )
                    data = retry_data
                    google_mode = "driving"
                else:
                    return _get_transport_fallback(
                        f"Google Maps status: {data.get('status')}",
                        requested_mode,
                    )

            route = data["routes"][0]
            leg = route["legs"][0]

            duration_mins = leg["duration"]["value"] / 60.0
            distance_km = leg["distance"]["value"] / 1000.0

            fare_info = route.get("fare")
            fare_value = fare_info.get("value") if fare_info else None
            fare_currency = fare_info.get("currency") if fare_info else "VND"

            steps_data: List[Dict[str, Any]] = []
            for step in leg.get("steps", []):
                travel_mode = step.get("travel_mode")

                if travel_mode == "TRANSIT":
                    transit_details = step.get("transit_details", {})
                    line = transit_details.get("line", {})
                    departure_stop = transit_details.get("departure_stop", {}).get("name")
                    arrival_stop = transit_details.get("arrival_stop", {}).get("name")
                    vehicle_type = line.get("vehicle", {}).get("type")
                    line_short_name = line.get("short_name") or line.get("name")
                    num_stops = transit_details.get("num_stops", 1)

                    steps_data.append({
                        "type": "TRANSIT",
                        "vehicle": vehicle_type,
                        "line": line_short_name,
                        "from_stop": departure_stop,
                        "to_stop": arrival_stop,
                        "num_stops": num_stops,
                        "duration_mins": round(step["duration"]["value"] / 60.0, 1)
                    })
                elif travel_mode == "WALKING":
                    steps_data.append({
                        "type": "WALKING",
                        "instructions": step.get("html_instructions"),
                        "distance_m": step.get("distance", {}).get("value"),
                        "duration_mins": round(step["duration"]["value"] / 60.0, 1)
                    })
                else:
                    steps_data.append({
                        "type": travel_mode or "ROUTE",
                        "instructions": step.get("html_instructions"),
                        "distance_m": step.get("distance", {}).get("value"),
                        "duration_mins": round(step["duration"]["value"] / 60.0, 1),
                    })

            polyline = route.get("overview_polyline", {}).get("points")
            has_transit_fare = google_mode == "transit"

            one_way_fare_vnd = (
                fare_value
                if fare_value is not None
                else (settings.DEFAULT_PUBLIC_TRANSIT_FARE if has_transit_fare else None)
            )

            fare_breakdown: Dict[str, Any] = {}

            if requested_mode.lower() in {"motorbike", "two_wheeler", "car", "driving"}:
                fuel_info = await _get_hanoi_fuel_price(client)
                fuel_price = fuel_info["fuel_price_vnd_per_liter"]

                if requested_mode.lower() in {"motorbike", "two_wheeler"}:
                    consumption_l_per_100km = MOTORBIKE_L_PER_100KM
                else:
                    consumption_l_per_100km = CAR_L_PER_100KM

                estimated_liters = distance_km * (consumption_l_per_100km / 100.0)
                one_way_fare_vnd = round(estimated_liters * fuel_price)
                fare_breakdown = {
                    "fuel_price_vnd_per_liter": round(fuel_price, 2),
                    "consumption_l_per_100km": consumption_l_per_100km,
                    "estimated_liters": round(estimated_liters, 3),
                    "formula": "distance_km * (consumption_l_per_100km / 100) * fuel_price_vnd_per_liter",
                    "fuel_price_source": fuel_info["fuel_price_source"],
                    "fuel_price_reason": fuel_info["fuel_price_reason"],
                }
            elif has_transit_fare:
                fare_breakdown = {
                    "fare_source": "google_route_fare_or_default",
                }

            return {
                "success": True,
                "requested_mode": requested_mode,
                "google_mode_used": google_mode,
                "distance_km": round(distance_km, 2),
                "duration_mins": round(duration_mins, 1),
                "fare_vnd": one_way_fare_vnd,
                "currency": fare_currency,
                "fare_breakdown": fare_breakdown,
                "steps": steps_data,
                "polyline": polyline
            }

        except Exception as e:
            return _get_transport_fallback(str(e), requested_mode)


def _get_transport_fallback(reason: str, requested_mode: str) -> Dict[str, Any]:
    google_mode = normalize_transport_mode(requested_mode)
    is_transit = google_mode == "transit"

    return {
        "success": False,
        "requested_mode": requested_mode,
        "google_mode_used": google_mode,
        "error_reason": reason,
        "distance_km": 0.0,
        "duration_mins": 0.0,
        "fare_vnd": settings.DEFAULT_PUBLIC_TRANSIT_FARE if is_transit else None,
        "currency": "VND",
        "fare_breakdown": {},
        "steps": [],
        "polyline": None
    }