import httpx
from app.config import settings

async def fetch_route_details(origin_str: str, dest_str: str, mode: str):
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": origin_str,
        "destination": dest_str,
        "mode": mode,
        "key": settings.GOOGLE_MAPS_API_KEY
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params)
        data = response.json()

        if data.get("status") != "OK":
            return {
                "distance_km": 5.0,
                "duration_mins": 20.0,
                "fare_vnd": None,
                "polyline": None
            }

        route = data["routes"][0]
        leg = route["legs"][0]
        fare_val = route.get("fare", {}).get("value", None)
        polyline = route.get("overview_polyline", {}).get("points", None)

        return {
            "distance_km": leg["distance"]["value"] / 1000.0,
            "duration_mins": leg["duration"]["value"] / 60.0,
            "fare_vnd": fare_val,
            "polyline": polyline
        }