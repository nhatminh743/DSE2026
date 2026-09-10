from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from services.hanoi_districts import fetch_hanoi_districts, geocode_district_name
from services.survey_data import quoted_table_name


def haversine_matrix(people_coordinates: np.ndarray, district_coordinates: np.ndarray) -> np.ndarray:
    people_rad = np.radians(people_coordinates)
    districts_rad = np.radians(district_coordinates)
    person_lat = people_rad[:, 0][:, None]
    person_lon = people_rad[:, 1][:, None]
    district_lat = districts_rad[:, 0][None, :]
    district_lon = districts_rad[:, 1][None, :]
    delta_lat = district_lat - person_lat
    delta_lon = district_lon - person_lon
    a = (
        np.sin(delta_lat / 2) ** 2
        + np.cos(person_lat) * np.cos(district_lat) * np.sin(delta_lon / 2) ** 2
    )
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def fetch_database_district_centers(db: Session) -> list[dict[str, Any]]:
    query = text(f"""
        WITH district_points AS (
            SELECT id, name,
                ST_Transform(
                    CASE WHEN ST_GeometryType(geom) = 'ST_Point'
                         THEN geom ELSE ST_PointOnSurface(geom) END,
                    4326
                ) AS point_geom
            FROM {quoted_table_name(settings.DISTRICT_TABLE)}
            WHERE geom IS NOT NULL
        )
        SELECT id AS district_id, name AS district_name,
               ST_Y(point_geom) AS latitude, ST_X(point_geom) AS longitude
        FROM district_points
        WHERE point_geom IS NOT NULL
        ORDER BY name
    """)
    try:
        rows = db.execute(query).mappings().all()
    except Exception:
        db.rollback()
        return []
    return [
        {
            "district_id": row["district_id"],
            "district_name": row["district_name"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "coordinate_source": "database",
        }
        for row in rows
        if row["district_name"] and row["latitude"] is not None and row["longitude"] is not None
    ]


def read_center_cache() -> list[dict[str, Any]]:
    path = Path(settings.DISTRICT_CENTER_CACHE_FILE)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def write_center_cache(centers: list[dict[str, Any]]) -> None:
    path = Path(settings.DISTRICT_CENTER_CACHE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(centers, file, ensure_ascii=False, indent=2)


async def fetch_internet_district_centers() -> list[dict[str, Any]]:
    districts = await fetch_hanoi_districts()
    semaphore = asyncio.Semaphore(5)

    async def resolve(district: dict[str, Any]):
        async with semaphore:
            result = await geocode_district_name(district.get("district_name"))
        if not result.get("success") or result.get("latitude") is None or result.get("longitude") is None:
            return None
        return {
            "district_id": district.get("district_id"),
            "district_name": district.get("district_name"),
            "latitude": float(result["latitude"]),
            "longitude": float(result["longitude"]),
            "formatted_address": result.get("formatted_address"),
            "coordinate_source": "google_geocoding",
        }

    results = await asyncio.gather(*(resolve(district) for district in districts))
    return [result for result in results if result is not None]


async def resolve_district_centers(db: Session) -> list[dict[str, Any]]:
    database_centers = fetch_database_district_centers(db)
    if database_centers:
        return database_centers
    cached_centers = read_center_cache()
    if cached_centers:
        return cached_centers
    internet_centers = await fetch_internet_district_centers()
    if not internet_centers:
        raise RuntimeError("District coordinates are unavailable. Add district geometry to PostgreSQL or configure GOOGLE_MAPS_API_KEY.")
    write_center_cache(internet_centers)
    return internet_centers


def assign_nearest_district(dataframe: pd.DataFrame, district_centers: list[dict[str, Any]], latitude_column: str = "origlat", longitude_column: str = "origlon") -> pd.DataFrame:
    result = dataframe.copy()
    result["district_name"] = "Unknown"
    result["district_distance_km"] = np.nan
    if result.empty or not district_centers or latitude_column not in result.columns or longitude_column not in result.columns:
        return result
    result[latitude_column] = pd.to_numeric(result[latitude_column], errors="coerce")
    result[longitude_column] = pd.to_numeric(result[longitude_column], errors="coerce")
    valid_mask = result[latitude_column].between(-90, 90) & result[longitude_column].between(-180, 180)
    centers = pd.DataFrame(district_centers).dropna(subset=["district_name", "latitude", "longitude"])
    if not valid_mask.any() or centers.empty:
        return result
    distances = haversine_matrix(
        result.loc[valid_mask, [latitude_column, longitude_column]].to_numpy(dtype=float),
        centers[["latitude", "longitude"]].to_numpy(dtype=float),
    )
    closest = distances.argmin(axis=1)
    indices = result.index[valid_mask]
    result.loc[indices, "district_name"] = centers.iloc[closest]["district_name"].to_numpy()
    result.loc[indices, "district_distance_km"] = distances[np.arange(len(closest)), closest]
    return result


def centers_to_geojson(centers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "district_id": center.get("district_id"),
                    "district_name": center["district_name"],
                    "coordinate_source": center.get("coordinate_source"),
                },
                "geometry": {"type": "Point", "coordinates": [center["longitude"], center["latitude"]]},
            }
            for center in centers
        ],
    }