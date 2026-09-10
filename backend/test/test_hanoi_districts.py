from unittest.mock import MagicMock, patch

import pytest

from services.hanoi_districts import fetch_hanoi_districts, geocode_district_name


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_fetch_hanoi_districts_parses_vnappmob_response(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"district_id": "001", "district_name": "Ba Đình"},
            {"district_id": "002", "district_name": "Hoàn Kiếm"},
        ]
    }
    mock_get.return_value = mock_response

    districts = await fetch_hanoi_districts()

    assert districts[0]["district_name"] == "Ba Đình"
    assert districts[1]["district_id"] == "002"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_geocode_district_name_extracts_geodata(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "status": "OK",
        "results": [
            {
                "formatted_address": "Hoàn Kiếm, Hà Nội, Việt Nam",
                "geometry": {
                    "location": {"lat": 21.0287, "lng": 105.8524},
                    "viewport": {
                        "northeast": {"lat": 21.0423, "lng": 105.8719},
                        "southwest": {"lat": 21.0152, "lng": 105.8407},
                    },
                },
            }
        ],
    }
    mock_get.return_value = mock_response

    result = await geocode_district_name("Hoàn Kiếm")

    assert result["success"] is True
    assert result["district_name"] == "Hoàn Kiếm"
    assert result["latitude"] == 21.0287
    assert result["bounds"]["northeast"]["lng"] == 105.8719
