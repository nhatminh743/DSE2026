import json
from io import BytesIO
import shutil
import traceback
import uuid
from pathlib import Path
import pandas as pd
from services.model_insights import (
    generate_model_insights,
    generate_model_insights_from_dataframe,
    load_model_insights,
)
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import (
    get_db,
    init_geocode_cache,
    init_survey_submissions_table,
    init_user_profiles_table,
)
from app.schemas import PlannerRequest, PlannerResponse, SurveySubmission
from services.maps import fetch_route_details
from services.places import autocomplete_places, place_coordinates
from services.public_transport import fetch_transport_details
from services.calculator import calculate_modes
from services.geocoding import reverse_geocode
from services.hanoi_districts import (
    build_hanoi_district_geojson,
    fetch_hanoi_districts,
)
from services.districts import (
    get_district_affected_summary,
    get_district_predictions,
)
from services.district_centers import centers_to_geojson, resolve_district_centers
from services.analytics import ModelWeightsUnavailable, get_model_weight_status
from services.policy_dashboard import build_district_policy_map, build_policy_eda
from services.dataset_insights import build_dataset_insights
from services.survey_data import load_baseline_dataframe
from services.job_process import launch_job, terminate_job
from services.kmedian_jobs import create_kmedian_run, get_kmedian_run_directory
from services.stations import get_ebike_eligibility
from services.model_training import (
    SUPPORTED_MODEL_TYPES,
    create_training_run,
    get_run_directory,
    package_artifacts,
    read_json,
    run_training_job,
    write_json,
)
from services.llm_analysis import analyze_model_results, explain_model_chart, explain_model_report
from services.model_bundle import simulate_uploaded_bundle
from services.firebase_service import (
    create_survey_response,
    delete_survey_response,
    get_or_create_profile,
    list_survey_responses,
    require_user,
    update_profile,
)
from services.survey_validation import validate_survey_payload
app = FastAPI(title="Citizen Planner Engine", version="1.0")

cors_origins = [
    origin.strip()
    for origin in settings.CORS_ALLOW_ORIGINS.split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins or ["*"],
    allow_credentials=cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/auth/firebase")
def authenticate_with_firebase(user: dict = Depends(require_user)):
    """Accept only Firebase ID tokens created with the Google provider."""
    try:
        return {"user": get_or_create_profile(user)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/account")
def get_account(user: dict = Depends(require_user)):
    try:
        return get_or_create_profile(user)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/account/profile")
async def update_account_profile(
    display_name: str = Form(...),
    avatar_url: str | None = Form(None),
    user: dict = Depends(require_user),
):
    display_name = display_name.strip()
    if not 1 <= len(display_name) <= 80:
        raise HTTPException(status_code=422, detail="Display name must contain 1 to 80 characters")
    if avatar_url and not (
        avatar_url.startswith("https://firebasestorage.googleapis.com/")
        or avatar_url.startswith("https://storage.googleapis.com/")
    ):
        raise HTTPException(status_code=422, detail="Avatar must be stored in Firebase Storage")
    try:
        return {"user": update_profile(user, display_name, avatar_url)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.on_event("startup")
def startup_event():
    """Initialize database tables on startup."""
    for directory in [
        settings.ARTIFACT_DIR,
        settings.DATASET_DIR,
        settings.MODEL_WEIGHT_DIR,
        settings.MODEL_RUN_DIR,
        settings.K_MEDIAN_WEIGHT_DIR,
        settings.K_MEDIAN_RUN_DIR,
    ]:
        Path(directory).mkdir(parents=True, exist_ok=True)
    try:
        init_geocode_cache()
    except Exception:
        pass

    try:
        init_survey_submissions_table()
    except Exception:
        pass

    try:
        init_user_profiles_table()
    except Exception:
        pass


@app.get("/api/maps/autocomplete")
async def maps_autocomplete(input: str = Query(..., min_length=2, max_length=200)):
    try:
        suggestions = await autocomplete_places(input)
        return {"suggestions": suggestions}
    except ModelWeightsUnavailable as exc:
        prediction_error = str(exc)
        print("[DISTRICT ANALYTICS] No model weight yet; using survey summary.")
        try:
            db.rollback()
        except Exception:
            pass
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Autocomplete failed: {exc}")


@app.get("/api/maps/place-details")
async def maps_place_details(place_id: str = Query(..., min_length=5, max_length=300)):
    try:
        place = await place_coordinates(place_id)
        return place
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Place details failed: {exc}")

@app.get("/api/maps/reverse-geocode")
async def maps_reverse_geocode(
    lat: float,
    lon: float,
):
    try:
        result = await reverse_geocode(
            latitude=lat,
            longitude=lon,
            language="vi",
        )

        return result

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Reverse geocoding failed: {exc}",
        )

@app.post("/api/calculator/public_transport")
async def public_transport(req: PlannerRequest):
    if None in (req.orig_lat, req.orig_lon, req.dest_lat, req.dest_lon):
        raise HTTPException(
            status_code=400,
            detail="Provide orig_lat, orig_lon, dest_lat, and dest_lon to test directions API",
        )

    origin = f"{req.orig_lat},{req.orig_lon}"
    destination = f"{req.dest_lat},{req.dest_lon}"
    transport_mode = (req.transport_mode or "public_transport").lower()
    if transport_mode not in {"public_transport", "transit", "motorbike", "car", "driving", "two_wheeler"}:
        raise HTTPException(
            status_code=400,
            detail="transport_mode must be one of: public_transport, motorbike, car",
        )

    route_data = await fetch_transport_details(origin, destination, transport_mode)

    return {
        "origin": origin,
        "destination": destination,
        **route_data,
    }

@app.post("/api/v1/plan", response_model=PlannerResponse)
async def evaluate_commute(req: PlannerRequest, db: Session = Depends(get_db)):
    orig_str = None
    dest_str = None
    trips_per_week = req.trips_per_week

    # Option A: Pull coordinates directly from PostGIS travel_survey record
    if req.rowid:
        query = text("""
            SELECT 
                CONCAT(ST_Y(orig_geom::geometry), ',', ST_X(orig_geom::geometry)) AS origin,
                CONCAT(ST_Y(dest_geom::geometry), ',', ST_X(dest_geom::geometry)) AS destination,
                freqpweek
            FROM travel_survey
            WHERE rowid = :rowid AND orig_geom IS NOT NULL AND dest_geom IS NOT NULL;
        """)
        row = db.execute(query, {"rowid": req.rowid}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Survey row or geometry coordinates not found")
        orig_str, dest_str = row.origin, row.destination

    # Option B: Coordinates passed directly from frontend map pin
    elif None not in (req.orig_lat, req.orig_lon, req.dest_lat, req.dest_lon):
        orig_str = f"{req.orig_lat},{req.orig_lon}"
        dest_str = f"{req.dest_lat},{req.dest_lon}"
    else:
        raise HTTPException(status_code=400, detail="Provide either a survey 'rowid' or full lat/lon coordinates")

    # Fetch live routes from Google Maps
    driving_data = await fetch_route_details(orig_str, dest_str, mode="driving")
    transit_data = await fetch_route_details(orig_str, dest_str, mode="transit")

    # Run calculation engine
    options = calculate_modes(
        driving_data=driving_data,
        transit_data=transit_data,
        trips_per_week=trips_per_week,
        ev_loan_override=req.ev_monthly_loan
    )

    return {
            "origin": orig_str,
            "destination": dest_str,
            "one_way_distance_km": driving_data["distance_km"],
            "trips_per_week": trips_per_week,
            "driving_polyline": driving_data.get("polyline"),
            "transit_polyline": transit_data.get("polyline"),
            "options": options
        }


@app.get("/api/analytics/districts")
async def district_analytics(
    scenario: str = "ice_ban",
    db: Session = Depends(get_db),
):
    prediction_error = None

    try:
        district_centers = await resolve_district_centers(db)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"District coordinates unavailable: {exc}")

    try:
        districts_data = get_district_predictions(
            db=db,
            district_centers=district_centers,
            scenario=scenario,
        )

        if districts_data:
            return {
                "scenario": scenario,
                "source": "model_predictions",
                "districts": districts_data,
            }
    except ModelWeightsUnavailable as exc:
        prediction_error = str(exc)
        print("[DISTRICT ANALYTICS] No model weight yet; using survey summary.")
        try:
            db.rollback()
        except Exception:
            pass
    except Exception as exc:
        prediction_error = str(exc)
        print("[DISTRICT ANALYTICS] Model prediction failed:", exc)
        traceback.print_exc()
        db.rollback()

    try:
        summary = get_district_affected_summary(db=db, district_centers=district_centers, scenario=scenario)
        if summary:
            return {
                "scenario": scenario,
                "source": "survey_summary",
                "weight_status": get_model_weight_status()["status"],
                "districts": [
                    {
                        **row,
                        "p_car": row["affected_car"] / row["affected_respondents"] if row["affected_respondents"] else 0,
                        "p_moto": row["affected_moto"] / row["affected_respondents"] if row["affected_respondents"] else 0,
                        "p_ebike": 0,
                        "p_bus": 0,
                    }
                    for row in summary
                ],
                "warning": prediction_error,
            }
    except Exception as exc:
        print("[DISTRICT ANALYTICS] Database summary failed:", exc)
        traceback.print_exc()
        db.rollback()

    return {
        "scenario": scenario,
        "source": "district_centers_only",
        "weight_status": get_model_weight_status()["status"],
        "districts": [
            {
            "district_name": center["district_name"],
                "affected_respondents": 0,
                "p_car": 0,
                "p_moto": 0,
                "p_ebike": 0,
                "p_bus": 0,
            }
            for center in district_centers
        ],
        "warning": prediction_error or "District model data is unavailable",
    }


@app.get("/api/analytics/district-boundaries")
async def district_boundaries(
    db: Session = Depends(get_db),
):
    """Return actual Hanoi district polygons enriched with policy metrics."""
    try:
        return await build_district_policy_map(db)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"District policy map is unavailable: {exc}")


@app.get("/api/analytics/policy-dashboard")
async def policy_dashboard_analytics(
    db: Session = Depends(get_db),
):
    try:
        return build_policy_eda(db)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"Policy dashboard analytics are unavailable: {exc}")


@app.get("/api/analytics/dataset-insights")
def default_dataset_insights():
    """Profile the canonical CSV when the user has not uploaded a dataset."""
    try:
        dataframe = load_baseline_dataframe(max_rows=settings.MAX_TRAINING_ROWS)
        return build_dataset_insights(dataframe, "baseline.csv")
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"Default dataset insights are unavailable: {exc}")


@app.post("/api/analytics/dataset-insights")
async def uploaded_dataset_insights(file: UploadFile | None = File(None)):
    """Profile an uploaded CSV, falling back to baseline.csv when omitted."""
    if file is None or not file.filename:
        return default_dataset_insights()
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")
    content = await file.read()
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV files are limited to 25 MB")
    try:
        dataframe = pd.read_csv(BytesIO(content), nrows=settings.MAX_TRAINING_ROWS)
        if dataframe.empty or len(dataframe.columns) == 0:
            raise ValueError("The uploaded CSV has no data rows")
        return build_dataset_insights(dataframe, Path(file.filename).name)
    except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not read CSV: {exc}")

    # Legacy boundary fallback retained below for compatibility with old deployments.
    try:
        query = text("""
            SELECT
                id,
                name,
                ST_AsGeoJSON(geom)::json AS geometry
            FROM districts
            WHERE geom IS NOT NULL;
        """)

        rows = db.execute(query).mappings().all()

        if rows:
            features = []
            for row in rows:
                features.append({
                    "type": "Feature",
                    "properties": {
                        "district_id": row["id"],
                        "district_name": row["name"],
                    },
                    "geometry": row["geometry"],
                })

            return {
                "type": "FeatureCollection",
                "features": features,
            }
    except Exception:
        pass

    # Query the public district list and geocode each district center so
    # the map layers render using Hanoi administrative names instead of a
    # hard-coded mock polygon set.
    try:
        geojson = await build_hanoi_district_geojson()
        if geojson.get("features"):
            return geojson
    except Exception:
        pass

    # Return a minimal mock fallback only if the public API is unreachable.
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "district_id": 1,
                    "district_name": "Hoàn Kiếm",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [105.84, 21.05],
                            [105.86, 21.05],
                            [105.86, 21.03],
                            [105.84, 21.03],
                            [105.84, 21.05],
                        ]
                    ]
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "district_id": 2,
                    "district_name": "Ba Đình",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [105.81, 21.05],
                            [105.84, 21.05],
                            [105.84, 21.02],
                            [105.81, 21.02],
                            [105.81, 21.05],
                        ]
                    ]
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "district_id": 3,
                    "district_name": "Hai Bà Trưng",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [105.84, 21.03],
                            [105.87, 21.03],
                            [105.87, 21.00],
                            [105.84, 21.00],
                            [105.84, 21.03],
                        ]
                    ]
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "district_id": 4,
                    "district_name": "Cầu Giấy",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [105.79, 21.05],
                            [105.82, 21.05],
                            [105.82, 21.02],
                            [105.79, 21.02],
                            [105.79, 21.05],
                        ]
                    ]
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "district_id": 5,
                    "district_name": "Thanh Xuân",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [105.82, 21.02],
                            [105.85, 21.02],
                            [105.85, 20.99],
                            [105.82, 20.99],
                            [105.82, 21.02],
                        ]
                    ]
                },
            },
        ],
    }


@app.get("/api/kmedian-runs/eligibility")
def get_kmedian_eligibility(db: Session = Depends(get_db)):
    return get_ebike_eligibility(db)


@app.get("/api/kmedian-runs/default")
def get_default_kmedian_solution():
    directory = Path(settings.K_MEDIAN_WEIGHT_DIR)
    solution_path = directory / "solution.json"
    if not solution_path.exists():
        return {"status": "no_weight_yet", "message": "No weight yet", "solution": None, "weights": None}
    return {
        "status": "ready",
        "message": "Saved K-median solution loaded",
        "solution": read_json(solution_path),
        "weights": read_json(directory / "weights.json") if (directory / "weights.json").exists() else None,
        "metadata": read_json(directory / "metadata.json") if (directory / "metadata.json").exists() else None,
    }


@app.post("/api/kmedian-runs")
def start_kmedian_run(
    k: int = Query(100, ge=1, le=5000),
    sample_percent: float = Query(100, ge=1, le=100),
):
    run_id = create_kmedian_run(k_stations=k, sample_percent=sample_percent)
    run_dir = get_kmedian_run_directory(run_id)
    pid = launch_job(
        "kmedian",
        run_id,
        {"k_stations": k, "sample_percent": sample_percent},
        run_dir / "status.json",
    )
    return {
        "run_id": run_id,
        "pid": pid,
        "state": "queued",
        "status_url": f"/api/kmedian-runs/{run_id}",
        "results_url": f"/api/kmedian-runs/{run_id}/results",
        "stop_url": f"/api/kmedian-runs/{run_id}/stop",
    }


@app.get("/api/kmedian-runs/{run_id}")
def get_kmedian_run(run_id: str):
    path = get_kmedian_run_directory(run_id) / "status.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="K-median run not found")
    return read_json(path)


@app.post("/api/kmedian-runs/{run_id}/stop")
def stop_kmedian_run(run_id: str):
    try:
        return terminate_job(get_kmedian_run_directory(run_id) / "status.json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="K-median run not found")


@app.get("/api/kmedian-runs/{run_id}/results")
def get_kmedian_results(run_id: str):
    run_dir = get_kmedian_run_directory(run_id)
    status_path = run_dir / "status.json"
    solution_path = run_dir / "solution.json"
    weights_path = run_dir / "weights.json"
    if not status_path.exists():
        raise HTTPException(status_code=404, detail="K-median run not found")
    status = read_json(status_path)
    if status.get("state") != "completed":
        raise HTTPException(status_code=409, detail={"message": "K-median run is not completed", "state": status.get("state")})
    if not solution_path.exists():
        raise HTTPException(status_code=404, detail="K-median solution not found")
    return {"status": "ready", "solution": read_json(solution_path), "weights": read_json(weights_path) if weights_path.exists() else None}


@app.get("/api/analytics/k-median")
def get_saved_kmedian():
    return get_default_kmedian_solution()


ALLOWED_MODEL_ARTIFACTS = {
    "current_mode_model.joblib",
    "fallback_mode_model.joblib",
    "model_metadata.json",
    "results.json",
    "solution.json",
    "eda_summary.json",
    "model_artifacts.zip",
}


@app.post("/api/model-runs/train")
async def train_models(
    source_type: str = Form("database"),
    test_size: float = Form(0.2),
    n_estimators: int = Form(100),
    models: str = Form("all"),
    file: UploadFile | None = File(None),
):
    if source_type not in {"database", "csv"}:
        raise HTTPException(status_code=400, detail="source_type must be database or csv")
    if not 0.05 <= test_size <= 0.5:
        raise HTTPException(status_code=400, detail="test_size must be between 0.05 and 0.5")
    if not 10 <= n_estimators <= 1000:
        raise HTTPException(status_code=400, detail="n_estimators must be between 10 and 1000")
    model_types = list(SUPPORTED_MODEL_TYPES) if models == "all" else [item.strip() for item in models.split(",") if item.strip()]
    unsupported = [name for name in model_types if name not in SUPPORTED_MODEL_TYPES]
    if not model_types or unsupported:
        raise HTTPException(
            status_code=400,
            detail=f"models must be 'all' or a comma-separated subset of: {', '.join(SUPPORTED_MODEL_TYPES)}",
        )

    source_path = None
    if source_type == "csv":
        if file is None or not (file.filename or "").lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="A CSV file is required")
        dataset_dir = Path(settings.DATASET_DIR)
        dataset_dir.mkdir(parents=True, exist_ok=True)
        source_path = str(dataset_dir / f"{uuid.uuid4().hex}.csv")
        with open(source_path, "wb") as output:
            shutil.copyfileobj(file.file, output)

    run_id = create_training_run(
        source_type,
        source_path,
        {"test_size": test_size, "n_estimators": n_estimators, "model_types": model_types},
    )
    pid = launch_job(
        "model",
        run_id,
        {"source_type": source_type, "source_path": source_path, "test_size": test_size, "n_estimators": n_estimators, "model_types": model_types},
        get_run_directory(run_id) / "status.json",
    )
    return {
        "run_id": run_id,
        "pid": pid,
        "state": "queued",
        "status_url": f"/api/model-runs/{run_id}",
        "results_url": f"/api/model-runs/{run_id}/results",
        "stop_url": f"/api/model-runs/{run_id}/stop",
    }


@app.get("/api/model-runs/default")
def get_default_model():
    status = get_model_weight_status()
    if status["status"] != "ready":
        return {**status, "weights": None, "metadata": None, "solution": None}
    directory = Path(settings.MODEL_WEIGHT_DIR)
    solution_path = directory / "solution.json"
    return {
        **status,
        "weights": {"current_mode": "current_mode_model.joblib", "fallback_mode": "fallback_mode_model.joblib"},
        "metadata": read_json(directory / "model_metadata.json"),
        "solution": read_json(solution_path) if solution_path.exists() else None,
    }


@app.get("/api/model-runs/default/download")
def download_default_model_bundle():
    directory = Path(settings.MODEL_WEIGHT_DIR)
    if get_model_weight_status()["status"] != "ready":
        raise HTTPException(status_code=404, detail="Saved model weights are not available")
    metadata = read_json(directory / "model_metadata.json")
    run_id = metadata.get("run_id")
    run_bundle = get_run_directory(str(run_id)) / "model_artifacts.zip" if run_id else None
    if run_bundle and run_bundle.exists():
        path = run_bundle
    else:
        package_artifacts(directory)
        path = directory / "model_artifacts.zip"
    return FileResponse(path=path, filename="hanoi-models-default.zip", media_type="application/zip")


@app.post("/api/model-runs/{run_id}/stop")
def stop_model_run(run_id: str):
    try:
        return terminate_job(get_run_directory(run_id) / "status.json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Training run not found")


@app.get("/api/model-runs/{run_id}")
def get_model_run(run_id: str):
    path = get_run_directory(run_id) / "status.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Training run not found")
    return read_json(path)


@app.get("/api/model-runs/{run_id}/results")
def get_model_results(run_id: str):
    run_dir = get_run_directory(run_id)
    status_path = run_dir / "status.json"
    results_path = run_dir / "solution.json"
    if not status_path.exists():
        raise HTTPException(status_code=404, detail="Training run not found")
    status = read_json(status_path)
    if status.get("state") == "cancelled":
        raise HTTPException(status_code=409, detail={"message": "Training was cancelled", "state": "cancelled"})
    if status.get("state") != "completed":
        raise HTTPException(status_code=409, detail={"message": "Training is not completed", "state": status.get("state")})
    if not results_path.exists():
        raise HTTPException(status_code=404, detail="Training solution not found")
    return read_json(results_path)


@app.post("/api/model-runs/{run_id}/insights/generate")
def regenerate_run_insights(run_id: str, model_type: str | None = Form(None)):
    run_dir = get_run_directory(run_id)
    snapshot_path = run_dir / "training_snapshot.csv"

    if not snapshot_path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "message": "The training-data snapshot was not found for this run.",
            },
        )

    try:
        metadata_path = run_dir / "model_metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError("Model metadata was not found for this run")
        metadata = read_json(metadata_path)
        available_models = metadata.get("model_types") or []
        selected_model = model_type or metadata.get("selected_default_model")
        if selected_model not in available_models:
            raise ValueError(
                f"Model type {selected_model!r} is unavailable. Available models: {', '.join(available_models)}"
            )
        return generate_model_insights_from_dataframe(
            pd.read_csv(snapshot_path),
            model_directory=run_dir,
            model_type=selected_model,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc)})
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"message": str(exc)},
        )


@app.get("/api/model-runs/{run_id}/artifacts/{artifact_name}")
def download_model_artifact(run_id: str, artifact_name: str):
    if artifact_name not in ALLOWED_MODEL_ARTIFACTS:
        raise HTTPException(status_code=400, detail="Unsupported artifact")
    path = get_run_directory(run_id) / artifact_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path=path, filename=f"{run_id}-{artifact_name}", media_type="application/octet-stream")


@app.get("/api/model-runs/{run_id}/download")
def download_model_bundle(run_id: str):
    path = get_run_directory(run_id) / "model_artifacts.zip"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Model artifact bundle not found")
    return FileResponse(path=path, filename=f"hanoi-models-{run_id}.zip", media_type="application/zip")


STATIC_MODEL_RUN_ID = "static-three-model-showcase"


def _read_static_model_file(*parts: str) -> dict:
    project_directory = Path(__file__).resolve().parents[2]
    candidates = [
        project_directory / "static_showcase" / "data" / "model-lab" / Path(*parts),
        project_directory / "frontend_dist" / "data" / "model-lab" / Path(*parts),
    ]
    for path in candidates:
        if path.is_file():
            return read_json(path)
    raise FileNotFoundError("Static Model Lab data is unavailable in this deployment")


@app.post("/api/model-analysis/llm")
async def analyze_model_with_llm(run_id: str | None = Form(None)):
    if run_id == STATIC_MODEL_RUN_ID:
        try:
            results = _read_static_model_file("results.json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    elif run_id:
        solution_path = get_run_directory(run_id) / "solution.json"
        if not solution_path.exists():
            raise HTTPException(status_code=404, detail="Model solution not found")
        results = read_json(solution_path)
    else:
        solution_path = Path(settings.MODEL_WEIGHT_DIR) / "solution.json"
        if not solution_path.exists():
            raise HTTPException(status_code=404, detail="Model solution not found")
        results = read_json(solution_path)
    try:
        analysis = await analyze_model_results(results)
        if run_id and run_id != STATIC_MODEL_RUN_ID:
            write_json(get_run_directory(run_id) / "llm_analysis.json", analysis)
        return analysis
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM analysis failed: {exc}")


@app.post("/api/model-analysis/chart")
async def explain_chart_with_llm(
    chart_id: str = Form(...),
    run_id: str | None = Form(None),
    model_type: str | None = Form(None),
):
    try:
        if chart_id == "model_report":
            if not model_type:
                raise ValueError("Choose a model before explaining its report")
            if model_type not in SUPPORTED_MODEL_TYPES:
                raise ValueError("Unsupported model type")
            if run_id == STATIC_MODEL_RUN_ID:
                results = _read_static_model_file("results.json")
            elif run_id:
                results = read_json(get_run_directory(run_id) / "solution.json")
            else:
                results = read_json(Path(settings.MODEL_WEIGHT_DIR) / "solution.json")
            return await explain_model_report(model_type, results)
        if run_id == STATIC_MODEL_RUN_ID:
            if not model_type:
                raise ValueError("Choose a model before explaining its chart")
            if model_type not in SUPPORTED_MODEL_TYPES:
                raise ValueError("Unsupported model type")
            insights = _read_static_model_file("models", model_type, "insights.json")
        else:
            insights = (
                load_model_insights(get_run_directory(run_id), model_type)
                if run_id and model_type
                else load_model_insights()
            )
        return await explain_model_chart(chart_id, insights)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini chart explanation failed: {exc}")


@app.post("/api/model-bundles/simulate")
async def simulate_model_bundle(
    file: UploadFile = File(...),
    iterations: int = Form(500),
    ban_car: bool = Form(True),
):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="A ZIP model bundle is required")
    if not 100 <= iterations <= 5000:
        raise HTTPException(status_code=400, detail="iterations must be between 100 and 5000")
    try:
        return simulate_uploaded_bundle(await file.read(), iterations=iterations, ban_car=ban_car)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not load model bundle: {exc}")


@app.get("/api/analytics/model-insights")
def get_model_insights():
    try:
        return load_model_insights()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/analytics/model-insights/generate")
def generate_insights(db: Session = Depends(get_db)):
    try:
        run_directory = Path(settings.MODEL_RUN_DIR)
        completed_snapshots = []

        if run_directory.exists():
            for candidate in run_directory.iterdir():
                snapshot_path = candidate / "training_snapshot.csv"
                status_path = candidate / "status.json"

                if not snapshot_path.exists() or not status_path.exists():
                    continue

                if read_json(status_path).get("state") == "completed":
                    completed_snapshots.append(snapshot_path)

        if completed_snapshots:
            latest_snapshot = max(
                completed_snapshots,
                key=lambda path: path.stat().st_mtime,
            )
            return generate_model_insights_from_dataframe(
                pd.read_csv(latest_snapshot)
            )

        return generate_model_insights(db)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Model insights failed: {exc}")


@app.get("/api/analytics/eda")
def get_eda():
    """Get EDA summary from artifacts."""
    try:
        path = Path(settings.MODEL_WEIGHT_DIR) / "eda_summary.json"

        if path.exists():
            with open(path) as f:
                return json.load(f)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="EDA artifacts are unavailable; train a model first",
        )

    raise HTTPException(
        status_code=503,
        detail="EDA artifacts are unavailable; train a model first",
    )

    # Kept below only as historical reference for the previous response shape.
    return {
        "mode_counts": [
            {"mode": "car", "count": 2400},
            {"mode": "moto", "count": 3200},
            {"mode": "ebike", "count": 850},
            {"mode": "bike", "count": 620},
            {"mode": "bus", "count": 1950},
            {"mode": "taxi", "count": 480},
            {"mode": "walk", "count": 1100},
            {"mode": "ltrain", "count": 320},
        ],
        "purpose_counts": [
            {"purpose": "work", "count": 4500},
            {"purpose": "study", "count": 2200},
            {"purpose": "shopping", "count": 1900},
            {"purpose": "leisure", "count": 1320},
            {"purpose": "other", "count": 500},
        ],
        "affected_summary": {
            "total_car_users": 2400,
            "total_moto_users": 3200,
            "total_affected": 5600,
            "total_respondents": 10420,
        },
    }
artifact_directory = Path(settings.ARTIFACT_DIR)
artifact_directory.mkdir(parents=True, exist_ok=True)

# Mount artifacts directory for static files
try:
    app.mount(
        "/artifacts",
        StaticFiles(
            directory=str(artifact_directory)
        ),
        name="artifacts",
    )
except Exception:
    pass


@app.post("/api/survey/responses")
def submit_survey(
    submission: SurveySubmission,
    user: dict = Depends(require_user),
):
    """
    Save survey response to survey_submissions table.
    """
    allowed_fields = {
        "age",
        "occup",
        "gender",
        "origlat",
        "origlon",
        "destlat",
        "destlon",
        "purp",
        "vehic",
        "freqpweek",
        "OD_dist",
        "travtime",
        "reason",
        "own_car",
        "own_motob",
        "own_ebike",
        "own_bike",
        "freq_car",
        "freq_motob",
        "freq_ebike",
        "freq_bike",
        "freq_taxi",
        "freq_bus",
        "school_acc",
        "market_acc",
        "hosp_acc",
        "bank_acc",
        "leis_acc",
        "type",
        "status",
        "own",
        "reas_not_car",
        "reas_not_motob",
        "reas_not_ebike",
        "reas_not_bike",
        "dist_to_pub",
        "aware_ban",
        "fut_veh",
        "alt_veh",
        "alt_car",
        "alt_ebike",
        "alt_bike",
        "alt_bus",
        "alt_ltrain",
        "alt_taxi",
        "alt_walk",
        "opinion_car",
        "opinion_motob",
        "opinion_ebike",
        "opinion_bike",
        "opinion_taxi",
        "opinion_bus",
        "opinion_ban",
    }

    cleaned_payload, validation_errors = validate_survey_payload(submission.payload, allowed_fields)
    if validation_errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Check the highlighted survey fields",
                "errors": validation_errors,
            },
        )

    try:
        return create_survey_response(user, cleaned_payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/survey/responses/mine")
def list_my_survey_responses(
    user: dict = Depends(require_user),
):
    try:
        return {"responses": list_survey_responses(user)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.delete("/api/survey/responses/{response_id}")
def delete_my_survey_response(
    response_id: str,
    user: dict = Depends(require_user),
):
    try:
        deleted = delete_survey_response(user, response_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Survey response not found")
    return {"id": response_id, "message": "Survey response deleted"}


frontend_directory = Path(__file__).resolve().parents[2] / "frontend_dist"
if not frontend_directory.is_dir():
    frontend_directory = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_directory.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(frontend_directory), html=True),
        name="frontend",
    )

