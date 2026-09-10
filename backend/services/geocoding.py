from typing import Any, Dict, Optional

import httpx

from app.config import settings


GEOCODING_URL = (
    "https://maps.googleapis.com/maps/api/geocode/json"
)


def extract_component(
    components: list[dict[str, Any]],
    component_type: str,
) -> Optional[str]:
    """
    Extract a Google address component by type.

    Example types:
    - administrative_area_level_1
    - administrative_area_level_2
    - locality
    - sublocality_level_1
    """
    for component in components:
        types = component.get("types", [])

        if component_type in types:
            return component.get("long_name")

    return None


def extract_district(
    components: list[dict[str, Any]],
) -> Optional[str]:
    """
    Extract a district-like administrative name.

    Google may return Hanoi districts under different
    administrative component types, so we check several.
    """

    possible_types = [
        "administrative_area_level_2",
        "administrative_area_level_3",
        "sublocality_level_1",
        "locality",
    ]

    for component_type in possible_types:
        value = extract_component(
            components,
            component_type,
        )

        if value:
            return value

    return None


async def reverse_geocode(
    latitude: float,
    longitude: float,
    language: str = "vi",
) -> Dict[str, Any]:
    params = {
        "latlng": f"{latitude},{longitude}",
        "key": settings.GOOGLE_MAPS_API_KEY,
        "language": language,
        "region": "vn",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            GEOCODING_URL,
            params=params,
        )

        response.raise_for_status()
        data = response.json()

    status = data.get("status")

    if status != "OK":
        return {
            "success": False,
            "status": status,
            "district": None,
            "formatted_address": None,
            "raw": data,
        }

    result = data["results"][0]
    components = result.get("address_components", [])

    return {
        "success": True,
        "status": status,
        "district": extract_district(components),
        "province": extract_component(
            components,
            "administrative_area_level_1",
        ),
        "city": extract_component(
            components,
            "locality",
        ),
        "formatted_address": result.get(
            "formatted_address"
        ),
        "place_id": result.get("place_id"),
        "raw": result,
    }
