from __future__ import annotations

import asyncio
import json
import os
import shutil
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.db import SessionLocal
from services.district_centers import resolve_district_centers
from services.stations import fetch_ebike_locations, run_k_median_model


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_kmedian_run_directory(run_id: str) -> Path:
    return Path(settings.K_MEDIAN_RUN_DIR) / run_id


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    os.replace(temporary_path, path)


def update_kmedian_status(run_id: str, **updates: Any) -> None:
    path = get_kmedian_run_directory(run_id) / "status.json"
    status = read_json(path) if path.exists() else {}
    status.update(updates)
    status["updated_at"] = utc_now()
    write_json(path, status)


def create_kmedian_run(k_stations: int, sample_percent: float = 100) -> str:
    run_id = uuid.uuid4().hex
    run_dir = get_kmedian_run_directory(run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(run_dir / "status.json", {
        "run_id": run_id,
        "job_type": "kmedian",
        "state": "queued",
        "progress": 0,
        "message": "K-median job queued",
        "parameters": {"k_stations": k_stations, "sample_percent": sample_percent},
        "created_at": utc_now(),
        "updated_at": utc_now(),
    })
    return run_id


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    shutil.copy2(source, temporary_path)
    os.replace(temporary_path, destination)


def promote_kmedian_default(run_dir: Path) -> None:
    default_dir = Path(settings.K_MEDIAN_WEIGHT_DIR)
    for filename in ["solution.json", "weights.json", "metadata.json"]:
        source = run_dir / filename
        if source.exists():
            atomic_copy(source, default_dir / filename)


def run_kmedian_job(run_id: str, k_stations: int, sample_percent: float = 100) -> None:
    run_dir = get_kmedian_run_directory(run_id)
    db = SessionLocal()
    try:
        update_kmedian_status(run_id, state="running", progress=5, message="Loading district centers", started_at=utc_now())
        district_centers = asyncio.run(resolve_district_centers(db))
        update_kmedian_status(run_id, progress=15, message="Loading survey demand")
        locations = fetch_ebike_locations(
            db=db,
            district_centers=district_centers,
            sample_percent=sample_percent,
        )
        if locations.empty:
            raise ValueError("No valid e-bike demand locations were found")
        update_kmedian_status(
            run_id,
            progress=30,
            message="Running K-median optimization",
            demand_node_count=len(locations),
            eligible_people=locations.attrs.get("eligible_people", len(locations)),
            sample_percent=sample_percent,
        )
        solution = run_k_median_model(df_locations=locations, k_stations=k_stations)
        update_kmedian_status(run_id, progress=85, message="Saving K-median solution")
        demand_columns = [column for column in ["rowid", "origlat", "origlon", "district_name", "freqpweek", "weight"] if column in locations.columns]
        weights_payload = {
            "run_id": run_id,
            "weight_type": "demand_node_weights",
            "description": "K-median demand weights used in the weighted-distance objective",
            "demand_weights": locations[demand_columns].where(locations.notna(), None).to_dict(orient="records"),
        }
        metadata = {
            "run_id": run_id,
            "created_at": utc_now(),
            "requested_k": k_stations,
            "selected_station_count": solution.get("num_stations", 0),
            "demand_node_count": solution.get("num_people", 0),
            "eligible_people": solution.get("eligible_people", len(locations)),
            "sample_percent": sample_percent,
            "objective_weighted_km": solution.get("objective_weighted_km"),
            "solver_status": solution.get("status"),
            "solver_method": solution.get("solver_method"),
        }
        write_json(run_dir / "solution.json", solution)
        write_json(run_dir / "weights.json", weights_payload)
        write_json(run_dir / "metadata.json", metadata)
        promote_kmedian_default(run_dir)
        update_kmedian_status(run_id, state="completed", progress=100, message="K-median completed and solution saved", completed_at=utc_now(), promoted_to_default=True)
    except Exception as exc:
        write_json(run_dir / "error.json", {"error": str(exc), "traceback": traceback.format_exc()})
        update_kmedian_status(run_id, state="failed", progress=100, message=str(exc), completed_at=utc_now())
    finally:
        db.close()
