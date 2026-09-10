from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

VNAPPMOB_API_URL = "https://vapi.vnappmob.com/api/province/"
HANOI_PROVINCE_ID = "01"


def _fallback_hanoi_districts() -> List[Dict[str, Any]]:
    return [
        {"district_id": "001", "district_name": "Ba Đình"},
        {"district_id": "002", "district_name": "Hoàn Kiếm"},
        {"district_id": "003", "district_name": "Hai Bà Trưng"},
        {"district_id": "004", "district_name": "Đống Đa"},
        {"district_id": "005", "district_name": "Cầu Giấy"},
        {"district_id": "006", "district_name": "Thanh Xuân"},
        {"district_id": "007", "district_name": "Hoàng Mai"},
        {"district_id": "008", "district_name": "Long Biên"},
        {"district_id": "009", "district_name": "Tây Hồ"},
        {"district_id": "010", "district_name": "Nam Từ Liêm"},
        {"district_id": "011", "district_name": "Bắc Từ Liêm"},
        {"district_id": "012", "district_name": "Hà Đông"},
        {"district_id": "013", "district_name": "Sơn Tây"},
        {"district_id": "014", "district_name": "Ba Vì"},
        {"district_id": "015", "district_name": "Phúc Thọ"},
        {"district_id": "016", "district_name": "Thạch Thất"},
        {"district_id": "017", "district_name": "Quốc Oai"},
        {"district_id": "018", "district_name": "Chương Mỹ"},
        {"district_id": "019", "district_name": "Đan Phượng"},
        {"district_id": "020", "district_name": "Hoài Đức"},
        {"district_id": "021", "district_name": "Thanh Oai"},
        {"district_id": "022", "district_name": "Mỹ Đức"},
        {"district_id": "023", "district_name": "Ứng Hòa"},
        {"district_id": "024", "district_name": "Thường Tín"},
        {"district_id": "025", "district_name": "Phú Xuyên"},
        {"district_id": "026", "district_name": "Mê Linh"},
    ]


async def fetch_hanoi_districts(province_id: str = HANOI_PROVINCE_ID) -> List[Dict[str, Any]]:
    """Fetch the districts of Hanoi from the VNAppMob administrative API."""
    url = f"{VNAPPMOB_API_URL}district/{province_id}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return _fallback_hanoi_districts()

    rows = payload.get("results") or payload.get("data") or payload.get("districts") or []
    if not isinstance(rows, list):
        return _fallback_hanoi_districts()

    districts: List[Dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        district_name = (
            item.get("district_name")
            or item.get("name")
            or item.get("district")
            or item.get("title")
        )
        if not district_name:
            continue

        districts.append(
            {
                "district_id": item.get("district_id") or item.get("id") or item.get("code") or len(districts) + 1,
                "district_name": district_name,
            }
        )

    if not districts:
        return _fallback_hanoi_districts()

    return districts


def _normalize_bounds(raw_bounds: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not raw_bounds:
        return None

    northeast = raw_bounds.get("northeast") or {}
    southwest = raw_bounds.get("southwest") or {}
    if not northeast or not southwest:
        return None

    return {
        "northeast": {
            "lat": northeast.get("lat"),
            "lng": northeast.get("lng"),
        },
        "southwest": {
            "lat": southwest.get("lat"),
            "lng": southwest.get("lng"),
        },
    }


def _bounds_to_polygon(bounds: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not bounds:
        return None

    northeast = bounds.get("northeast") or {}
    southwest = bounds.get("southwest") or {}

    ne_lat = northeast.get("lat")
    ne_lng = northeast.get("lng")
    sw_lat = southwest.get("lat")
    sw_lng = southwest.get("lng")

    if ne_lat is None or ne_lng is None or sw_lat is None or sw_lng is None:
        return None

    return {
        "type": "Polygon",
        "coordinates": [[
            [sw_lng, sw_lat],
            [ne_lng, sw_lat],
            [ne_lng, ne_lat],
            [sw_lng, ne_lat],
            [sw_lng, sw_lat],
        ]],
    }


async def geocode_district_name(
    district_name: str,
    province_name: str = "Hà Nội",
    country: str = "Việt Nam",
) -> Dict[str, Any]:
    """Geocode a district name to lat/lng and bounding box via Google Maps."""
    if not district_name:
        return {
            "success": False,
            "district_name": district_name,
            "latitude": None,
            "longitude": None,
            "bounds": None,
            "formatted_address": None,
            "error": "No district name provided",
        }

    query = f"{district_name}, {province_name}, {country}"
    params = {
        "address": query,
        "key": settings.GOOGLE_MAPS_API_KEY,
        "language": "vi",
        "region": "vn",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # pragma: no cover - network layer failure
        return {
            "success": False,
            "district_name": district_name,
            "latitude": None,
            "longitude": None,
            "bounds": None,
            "formatted_address": None,
            "error": str(exc),
        }

    status = payload.get("status")
    if status != "OK":
        return {
            "success": False,
            "district_name": district_name,
            "latitude": None,
            "longitude": None,
            "bounds": None,
            "formatted_address": None,
            "status": status,
            "error": payload.get("error_message"),
        }

    result = payload["results"][0]
    geometry = result.get("geometry", {}) or {}
    location = geometry.get("location") or {}
    raw_bounds = _normalize_bounds(geometry.get("bounds") or geometry.get("viewport"))
    polygon = _bounds_to_polygon(raw_bounds)

    return {
        "success": True,
        "status": status,
        "district_name": district_name,
        "province_name": province_name,
        "latitude": location.get("lat"),
        "longitude": location.get("lng"),
        "formatted_address": result.get("formatted_address"),
        "bounds": raw_bounds,
        "geometry": polygon,
        "raw": result,
    }


async def build_hanoi_district_geojson() -> Dict[str, Any]:
    """Return a GeoJSON feature collection using Hanoi district names and geocoded bounds."""
    districts = await fetch_hanoi_districts()

    features: List[Dict[str, Any]] = []
    for index, district in enumerate(districts):
        district_name = district.get("district_name")
        geocode = await geocode_district_name(district_name)
        geometry = geocode.get("geometry")
        if geometry is None:
            continue

        features.append(
            {
                "type": "Feature",
                "properties": {
                    "district_id": district.get("district_id") or index + 1,
                    "district_name": district_name,
                    "latitude": geocode.get("latitude"),
                    "longitude": geocode.get("longitude"),
                },
                "geometry": geometry,
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }
