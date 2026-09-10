from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.config import settings
from services.analytics import normalize_model_columns, predict_affected_users
from services.district_centers import assign_nearest_district, resolve_district_centers
from services.survey_data import load_baseline_dataframe

HANOI_BOUNDARY_URL = (
    "https://raw.githubusercontent.com/duongthanhthai/"
    "don-vi-hanh-chinh-viet-nam/refs/heads/master/data/gis/01.json"
)
ALT_COLUMNS = ["alt_car", "alt_ebike", "alt_bike", "alt_bus", "alt_ltrain", "alt_taxi", "alt_walk"]
SUSTAINABLE_COLUMNS = ["alt_ebike", "alt_bike", "alt_bus", "alt_ltrain", "alt_walk"]
ALT_LABELS = {"alt_car": "Car", "alt_ebike": "E-bike", "alt_bike": "Bike", "alt_bus": "Bus", "alt_ltrain": "Light rail", "alt_taxi": "Taxi", "alt_walk": "Walk"}
MODE_LABELS = {"moto": "Motorbike", "car": "Car", "ebike": "E-bike", "bike": "Bike", "walk": "Walk", "bus": "Bus", "taxi": "Taxi", "tram": "Tram", "ltrain": "Light rail"}
DISTANCE_LABELS = ["<=3 km", "3-5 km", "5-10 km", "10-15 km", ">15 km"]
DISTANCE_BINS = [-0.001, 3, 5, 10, 15, 30]
FREQUENCY_MIDPOINTS = {"1_3": 2.0, "4_7": 5.5, "8_10": 9.0, "11_13": 12.0, "14_16": 15.0, "17_20": 18.5, "more_20": 21.0}
OCCUPATION_LABELS = {"state": "State", "private": "Private", "fdi": "FDI", "student": "Student", "retired": "Retired"}
PERCEPTION_MAPPING = {"verybad": "Negative", "bad": "Negative", "neutral": "Neutral", "good": "Positive", "verygood": "Positive"}
PERCEPTION_ORDER = ["Negative", "Neutral", "Positive"]


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
        return value if np.isfinite(value) else None
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if value is None or not pd.api.types.is_scalar(value):
        return value
    return None if pd.isna(value) else value


def normalize_district_key(value: Any) -> str:
    if value is None:
        return ""
    value = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    value = re.sub(r"^(quận|huyện|thị xã|thành phố)\s+", "", value)
    return re.sub(r"\s+", " ", value).strip()


def prepare_policy_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    result = normalize_model_columns(dataframe)
    for column in ["OD_dist", "travtime", "dist_to_pub", "origlat", "origlon", "destlat", "destlon"]:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    for column in ALT_COLUMNS:
        if column not in result:
            result[column] = 0
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0).clip(0, 1)
    for source, target, lower, upper in [("OD_dist", "OD_dist_clean", 0, 30), ("travtime", "travtime_clean", 0, 180), ("dist_to_pub", "dist_to_pub_clean", 0, 10_000)]:
        values = result.get(source, pd.Series(np.nan, index=result.index))
        result[target] = values.where(values.between(lower, upper))
    return result


async def load_hanoi_boundaries() -> dict[str, Any]:
    cache_path = Path(settings.HANOI_BOUNDARY_CACHE_FILE)
    payload = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(HANOI_BOUNDARY_URL)
            response.raise_for_status()
            payload = response.json()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False)
    except Exception:
        if cache_path.exists():
            with cache_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
    if not payload:
        raise RuntimeError("Hanoi district boundaries are unavailable")
    features = []
    for area in payload.get("level2s", []):
        if not all(area.get(key) for key in ("type", "coordinates", "name")):
            continue
        features.append({"type": "Feature", "properties": {"district_id": area.get("level2_id"), "district_name": area["name"], "district_key": normalize_district_key(area["name"])}, "geometry": {"type": area["type"], "coordinates": area["coordinates"]}})
    return {"type": "FeatureCollection", "features": features}


def _motorbikes(dataframe: pd.DataFrame) -> pd.DataFrame:
    return dataframe[dataframe["vehic"].eq("moto")].copy() if "vehic" in dataframe else dataframe.iloc[0:0].copy()


def build_mode_share(dataframe: pd.DataFrame) -> list[dict[str, Any]]:
    if "vehic" not in dataframe:
        return []
    share = dataframe["vehic"].dropna().astype(str).value_counts(normalize=True).mul(100).sort_values(ascending=False)
    return [{"mode": MODE_LABELS.get(mode, mode), "percentage": round(float(value), 2)} for mode, value in share.items()]


def build_alternative_share(motorbike: pd.DataFrame) -> list[dict[str, Any]]:
    if motorbike.empty:
        return []
    return sorted([{"alternative": ALT_LABELS[column], "percentage": round(float(motorbike[column].mean() * 100), 2)} for column in ALT_COLUMNS], key=lambda row: row["percentage"], reverse=True)


def build_consideration_future(motorbike: pd.DataFrame) -> list[dict[str, Any]]:
    if motorbike.empty:
        return []
    future = motorbike.get("fut_veh", pd.Series("", index=motorbike.index)).astype(str)
    return [{"mode": label, "considered": round(float(motorbike[column].mean() * 100), 2), "future_intention": round(float(future.eq(mode).mean() * 100), 2)} for label, column, mode in [("Car", "alt_car", "car"), ("E-bike", "alt_ebike", "ebike"), ("Bike", "alt_bike", "bike")]]


def build_transition_segments(motorbike: pd.DataFrame) -> list[dict[str, Any]]:
    if motorbike.empty:
        return []
    car = motorbike["alt_car"].eq(1)
    sustainable = motorbike[SUSTAINABLE_COLUMNS].max(axis=1).eq(1)
    segments = np.select([~car & sustainable, car & sustainable, car & ~sustainable], ["Sustainable only", "Car + Sustainable", "Car only"], default="Neither")
    share = pd.Series(segments).value_counts(normalize=True).mul(100)
    return [{"segment": label, "percentage": round(float(share.get(label, 0)), 2)} for label in ["Sustainable only", "Car + Sustainable", "Car only", "Neither"]]


def build_alternative_count(motorbike: pd.DataFrame) -> list[dict[str, Any]]:
    if motorbike.empty:
        return []
    counts = motorbike[ALT_COLUMNS].sum(axis=1).round().astype(int).value_counts(normalize=True).sort_index().mul(100)
    return [{"count": int(count), "percentage": round(float(value), 2)} for count, value in counts.items()]


def add_distance_groups(motorbike: pd.DataFrame) -> pd.DataFrame:
    valid = motorbike[motorbike["OD_dist_clean"].notna()].copy()
    if not valid.empty:
        valid["distance_group"] = pd.cut(valid["OD_dist_clean"], bins=DISTANCE_BINS, labels=DISTANCE_LABELS, include_lowest=True)
    return valid


def build_car_by_distance(motorbike: pd.DataFrame) -> list[dict[str, Any]]:
    valid = add_distance_groups(motorbike)
    if valid.empty:
        return []
    grouped = valid.groupby("distance_group", observed=False)["alt_car"].mean().mul(100).reindex(DISTANCE_LABELS)
    return [{"distance": label, "car": round(float(grouped.get(label)), 2) if pd.notna(grouped.get(label)) else None} for label in DISTANCE_LABELS]


def build_alternatives_by_distance(motorbike: pd.DataFrame) -> list[dict[str, Any]]:
    valid = add_distance_groups(motorbike)
    if valid.empty:
        return []
    grouped = valid.groupby("distance_group", observed=False)[["alt_car", "alt_bus", "alt_ebike"]].mean().mul(100).reindex(DISTANCE_LABELS)
    return [{"distance": label, **{key: round(float(grouped.loc[label, column]), 2) if pd.notna(grouped.loc[label, column]) else None for key, column in [("car", "alt_car"), ("bus", "alt_bus"), ("ebike", "alt_ebike")]}} for label in DISTANCE_LABELS]


def build_occupation_heatmap(motorbike: pd.DataFrame) -> dict[str, Any]:
    valid = add_distance_groups(motorbike)
    if valid.empty or "occup" not in valid:
        return {"columns": DISTANCE_LABELS, "rows": []}
    valid["occupation"] = valid["occup"].map(OCCUPATION_LABELS).fillna(valid["occup"])
    heatmap = valid.pivot_table(index="occupation", columns="distance_group", values="alt_car", aggfunc="mean", observed=False).mul(100).reindex(columns=DISTANCE_LABELS)
    return {"columns": DISTANCE_LABELS, "rows": [{"occupation": str(index), "values": [round(float(value), 2) if pd.notna(value) else None for value in row]} for index, row in heatmap.iterrows()]}


def build_pt_proximity(motorbike: pd.DataFrame) -> list[dict[str, Any]]:
    valid = motorbike[motorbike["dist_to_pub_clean"].notna()].copy()
    if valid.empty:
        return []
    within = valid["dist_to_pub_clean"] <= 500
    return [{"group": label, "bus": round(float(valid.loc[mask, "alt_bus"].mean() * 100), 2) if mask.any() else None, "car": round(float(valid.loc[mask, "alt_car"].mean() * 100), 2) if mask.any() else None} for label, mask in [("Within 500m of PT", within), ("More than 500m from PT", ~within)]]


def build_perception_chart(motorbike: pd.DataFrame) -> list[dict[str, Any]]:
    output = {label: {"perception": label} for label in PERCEPTION_ORDER}
    for label, opinion, alternative in [("car", "opinion_car", "alt_car"), ("ebike", "opinion_ebike", "alt_ebike"), ("bus", "opinion_bus", "alt_bus")]:
        if opinion not in motorbike:
            continue
        mapped = motorbike[opinion].astype(str).str.casefold().map(PERCEPTION_MAPPING)
        grouped = motorbike.assign(_perception=mapped).groupby("_perception")[alternative].mean().mul(100)
        for perception in PERCEPTION_ORDER:
            value = grouped.get(perception)
            output[perception][label] = round(float(value), 2) if pd.notna(value) else None
    return [output[label] for label in PERCEPTION_ORDER]


def build_policy_eda_from_dataframe(
    raw: pd.DataFrame,
    source: str | None = None,
) -> dict[str, Any]:
    """Build the notebook-derived policy EDA from any compatible dataframe."""
    dataframe = prepare_policy_dataframe(raw)
    motorbike = _motorbikes(dataframe)
    car_considerers = motorbike[motorbike["alt_car"].eq(1)]
    sustainable_rate = float(car_considerers[SUSTAINABLE_COLUMNS].max(axis=1).eq(1).mean() * 100) if not car_considerers.empty else 0.0
    payload = {"source": source or raw.attrs.get("source", "uploaded_csv"), "summary": {"respondents": int(len(dataframe)), "motorbike_users": int(len(motorbike)), "motorbike_share": round(float(len(motorbike) / len(dataframe) * 100), 2) if len(dataframe) else 0, "valid_od_distance_rows": int(dataframe["OD_dist_clean"].notna().sum()), "valid_pt_distance_rows": int(dataframe["dist_to_pub_clean"].notna().sum()), "average_alternatives": round(float(motorbike[ALT_COLUMNS].sum(axis=1).mean()), 2) if not motorbike.empty else 0, "multiple_alternative_share": round(float(motorbike[ALT_COLUMNS].sum(axis=1).ge(2).mean() * 100), 2) if not motorbike.empty else 0, "car_considerers_with_sustainable": round(sustainable_rate, 2)}, "mode_share": build_mode_share(dataframe), "alternative_share": build_alternative_share(motorbike), "consideration_future": build_consideration_future(motorbike), "transition_segments": build_transition_segments(motorbike), "alternative_count": build_alternative_count(motorbike), "car_by_distance": build_car_by_distance(motorbike), "alternatives_by_distance": build_alternatives_by_distance(motorbike), "occupation_distance_heatmap": build_occupation_heatmap(motorbike), "pt_proximity": build_pt_proximity(motorbike), "perception": build_perception_chart(motorbike)}
    return json_safe(payload)


def build_policy_eda(db: Session) -> dict[str, Any]:
    # Policy metrics intentionally use the checked-in baseline so dashboard
    # values cannot change with database availability or table contents.
    raw = load_baseline_dataframe(max_rows=settings.MAX_TRAINING_ROWS)
    return build_policy_eda_from_dataframe(raw, source="baseline.csv")


async def build_district_policy_map(db: Session) -> dict[str, Any]:
    raw = load_baseline_dataframe(max_rows=settings.MAX_TRAINING_ROWS)
    dataframe = prepare_policy_dataframe(raw)
    centers = await resolve_district_centers(db)
    dataframe = assign_nearest_district(dataframe, centers, "origlat", "origlon")
    motorbike = _motorbikes(dataframe)
    metric_source = "no_motorbike_rows"
    if motorbike.empty:
        policy_data = motorbike
    else:
        try:
            policy_data = predict_affected_users(motorbike)
            metric_source = "model_predictions"
        except Exception as exc:
            print(f"[POLICY MAP] Model unavailable, using stated alternatives: {exc}")
            policy_data = motorbike.copy()
            metric_source = "stated_alternatives"
    for column in SUSTAINABLE_COLUMNS:
        if column not in policy_data:
            policy_data[column] = 0
    policy_data["no_sustainable_alt"] = policy_data[SUSTAINABLE_COLUMNS].sum(axis=1).eq(0).astype(int)
    frequency = policy_data.get("freqpweek", pd.Series(1, index=policy_data.index))
    policy_data["sampled_weekly_trips"] = frequency.map(FREQUENCY_MIDPOINTS).fillna(pd.to_numeric(frequency, errors="coerce")).fillna(1)
    sources = {name: (model if model in policy_data else fallback) for name, model, fallback in [("car_rebound_risk", "p_car", "alt_car"), ("ebike_propensity", "p_ebike", "alt_ebike"), ("bus_propensity", "p_bus", "alt_bus"), ("rail_propensity", "p_ltrain", "alt_ltrain")]}
    if policy_data.empty:
        metric_rows = []
    else:
        count_spec = ("rowid", "nunique") if "rowid" in policy_data else ("vehic", "size")
        metrics = policy_data.groupby("district_name", dropna=False).agg(affected_respondents=count_spec, sampled_weekly_trips=("sampled_weekly_trips", "sum"), car_rebound_risk=(sources["car_rebound_risk"], "mean"), ebike_propensity=(sources["ebike_propensity"], "mean"), bus_propensity=(sources["bus_propensity"], "mean"), rail_propensity=(sources["rail_propensity"], "mean"), no_sustainable_alt_rate=("no_sustainable_alt", "mean"), median_pt_distance=("dist_to_pub_clean", "median"), median_od_distance=("OD_dist_clean", "median"), average_origin_center_distance=("district_distance_km", "mean")).reset_index()
        metric_rows = metrics.to_dict(orient="records")
    boundaries = await load_hanoi_boundaries()
    metrics_by_key = {normalize_district_key(row["district_name"]): row for row in metric_rows}
    metric_fields = ["affected_respondents", "sampled_weekly_trips", "car_rebound_risk", "ebike_propensity", "bus_propensity", "rail_propensity", "no_sustainable_alt_rate", "median_pt_distance", "median_od_distance", "average_origin_center_distance"]
    for feature in boundaries["features"]:
        properties = feature["properties"]
        metrics = metrics_by_key.get(properties["district_key"], {})
        properties.update({key: metrics.get(key) for key in metric_fields})
        properties.update({"average_route_exposure": None, "metric_source": metric_source})
    boundaries["metadata"] = {"survey_source": raw.attrs.get("source", "database"), "metric_source": metric_source, "assignment_method": "nearest district center using haversine distance", "boundary_type": "legacy Hanoi district-level polygons", "route_exposure_available": False}
    return json_safe(boundaries)
