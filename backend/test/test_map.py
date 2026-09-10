import pytest
from unittest.mock import patch, MagicMock
import httpx

# Adjust the import based on your actual project structure
from services.maps import fetch_transit_details

# --- MOCK DATA ---

MOCK_GOOGLE_MAPS_SUCCESS = {
    "status": "OK",
    "routes": [{
        "fare": {"value": 15000, "currency": "VND"},
        "overview_polyline": {"points": "mocked_encoded_polyline_string"},
        "legs": [{
            "duration": {"value": 1800},  # 30 mins (in seconds)
            "distance": {"value": 5500},  # 5.5 km (in meters)
            "steps": [
                {
                    "travel_mode": "WALKING",
                    "duration": {"value": 300}, # 5 mins
                    "distance": {"value": 400},
                    "html_instructions": "Walk to station"
                },
                {
                    "travel_mode": "TRANSIT",
                    "duration": {"value": 1500}, # 25 mins
                    "transit_details": {
                        "line": {"short_name": "152", "vehicle": {"type": "BUS"}},
                        "departure_stop": {"name": "Ben Thanh"},
                        "arrival_stop": {"name": "Airport"},
                        "num_stops": 8
                    }
                }
            ]
        }]
    }]
}

MOCK_GOOGLE_MAPS_FAIL = {
    "status": "ZERO_RESULTS",
    "routes": []
}

# --- TESTS ---

@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_fetch_transit_details_success(mock_get):
    """Test successful extraction of distance, duration, fare, and steps."""
    # Setup mock response
    mock_response = MagicMock()
    mock_response.json.return_value = MOCK_GOOGLE_MAPS_SUCCESS
    mock_get.return_value = mock_response

    # Execute
    result = await fetch_transit_details("Ben Thanh, HCMC", "Tan Son Nhat, HCMC")

    # Assertions
    assert result["success"] is True
    assert result["distance_km"] == 5.5
    assert result["duration_mins"] == 30.0
    assert result["fare_vnd"] == 15000
    assert result["currency"] == "VND"
    assert result["polyline"] == "mocked_encoded_polyline_string"
    
    # Check steps parsing
    assert len(result["steps"]) == 2
    
    # Validate Walking Step
    assert result["steps"][0]["type"] == "WALKING"
    assert result["steps"][0]["duration_mins"] == 5.0
    assert result["steps"][0]["distance_m"] == 400
    
    # Validate Transit Step
    assert result["steps"][1]["type"] == "TRANSIT"
    assert result["steps"][1]["line"] == "152"
    assert result["steps"][1]["vehicle"] == "BUS"
    assert result["steps"][1]["from_stop"] == "Ben Thanh"
    assert result["steps"][1]["duration_mins"] == 25.0

@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_fetch_transit_details_api_error(mock_get):
    """Test fallback when Google Maps returns a non-OK status."""
    mock_response = MagicMock()
    mock_response.json.return_value = MOCK_GOOGLE_MAPS_FAIL
    mock_get.return_value = mock_response

    result = await fetch_transit_details("Ocean", "Moon")

    assert result["success"] is False
    assert "Google Maps status: ZERO_RESULTS" in result["error_reason"]
    # Verify fallback defaults
    assert result["distance_km"] == 6.0
    assert result["duration_mins"] == 35.0

@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_fetch_transit_details_exception(mock_get):
    """Test fallback when httpx throws a network exception."""
    mock_get.side_effect = httpx.RequestError("Mocked network timeout")

    result = await fetch_transit_details("Point A", "Point B")

    assert result["success"] is False
    assert "Mocked network timeout" in result["error_reason"]
    assert result["steps"] == []