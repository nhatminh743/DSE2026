from typing import Any, Dict, List

import httpx

from app.config import settings


AUTOCOMPLETE_URL = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


async def autocomplete_places(input_text: str) -> List[Dict[str, str]]:
    params = {
        "input": input_text,
        "key": settings.GOOGLE_MAPS_API_KEY,
        "language": "en",
        "region": "vn",
        "components": "country:vn",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(AUTOCOMPLETE_URL, params=params)
        response.raise_for_status()
        data = response.json()

    status = data.get("status")

    if status not in {"OK", "ZERO_RESULTS"}:
        raise ValueError(
            f"Google Places autocomplete failed: "
            f"status={status}, "
            f"message={data.get('error_message', 'No error_message returned')}"
        )

    return [
        {
            "place_id": item.get("place_id", ""),
            "description": item.get("description", ""),
        }
        for item in data.get("predictions", [])
        if item.get("place_id")
    ]


async def place_coordinates(place_id: str) -> Dict[str, Any]:
    params = {
        "place_id": place_id,
        "fields": "name,formatted_address,geometry",
        "key": settings.GOOGLE_MAPS_API_KEY,
        "language": "en",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(DETAILS_URL, params=params)
        data = response.json()

    status = data.get("status")

    if status not in {"OK", "ZERO_RESULTS"}:
        raise ValueError(
            f"Google Places error: "
            f"status={status}, "
            f"message={data.get('error_message')}"
        )

    result = data.get("result", {})
    location = result.get("geometry", {}).get("location", {})

    lat = location.get("lat")
    lng = location.get("lng")
    if lat is None or lng is None:
        raise ValueError("No coordinates found for selected place")

    return {
        "name": result.get("name"),
        "address": result.get("formatted_address"),
        "lat": lat,
        "lng": lng,
    }
