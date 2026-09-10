from __future__ import annotations

import asyncio
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_DIR / "backend"
RUNS_DIR = BACKEND_DIR / "weights" / "model_lab" / "runs"
ARTIFACT_DIR = BACKEND_DIR / "artifacts"
OUTPUT_DIR = PROJECT_DIR / "static_showcase" / "data"
MODEL_ORDER = ("gradient_boosting", "random_forest", "decision_tree")
GITHUB_URL = "https://github.com/nhatminh743/DSE2026"

sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal  # noqa: E402
from services.dataset_insights import build_dataset_insights  # noqa: E402
from services.policy_dashboard import build_district_policy_map  # noqa: E402


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as destination:
        json.dump(payload, destination, ensure_ascii=False, indent=2)
        destination.write("\n")


def latest_run_for(model_type: str) -> Path:
    matches: list[Path] = []
    for directory in RUNS_DIR.iterdir():
        metadata_path = directory / "model_metadata.json"
        status_path = directory / "status.json"
        if not metadata_path.exists() or not status_path.exists():
            continue
        metadata = read_json(metadata_path)
        status = read_json(status_path)
        if status.get("state") == "completed" and model_type in metadata.get("model_types", []):
            matches.append(directory)
    if not matches:
        raise FileNotFoundError(f"No completed {model_type} run was found")
    return max(matches, key=lambda path: path.stat().st_mtime)


def export_models():
    runs = {model_type: latest_run_for(model_type) for model_type in MODEL_ORDER}
    results_by_model = {
        model_type: read_json(run_directory / "results.json")
        for model_type, run_directory in runs.items()
    }

    selected_default = max(
        MODEL_ORDER,
        key=lambda model_type: results_by_model[model_type]["models"][model_type]["score"],
    )
    selected_result = results_by_model[selected_default]
    combined = {
        **selected_result,
        "run_id": "static-three-model-showcase",
        "source_type": "precomputed",
        "selected_default_model": selected_default,
        "models": {
            model_type: {
                key: value
                for key, value in results_by_model[model_type]["models"][model_type].items()
                if key != "artifacts"
            }
            for model_type in MODEL_ORDER
        },
        "model_analytics": {
            model_type: {
                "migration": results_by_model[model_type].get("migration", {}),
                "monte_carlo": results_by_model[model_type].get("monte_carlo", {}),
                "travel_time_elasticity": results_by_model[model_type].get("travel_time_elasticity", []),
            }
            for model_type in MODEL_ORDER
        },
    }
    write_json(OUTPUT_DIR / "model-lab" / "results.json", combined)

    metadata = read_json(runs[selected_default] / "model_metadata.json")
    metadata.update(
        {
            "run_id": "static-three-model-showcase",
            "model_types": list(MODEL_ORDER),
            "selected_default_model": selected_default,
            "source_runs": {model_type: path.name for model_type, path in runs.items()},
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "github_url": GITHUB_URL,
        }
    )
    write_json(OUTPUT_DIR / "model-lab" / "metadata.json", metadata)

    for model_type, run_directory in runs.items():
        insight_path = run_directory / f"model_insights_{model_type}.json"
        insights = read_json(insight_path)
        model_output_dir = OUTPUT_DIR / "model-lab" / "models" / model_type
        summary_name = f"shap_ebike_summary_{model_type}.png"
        distance_name = f"shap_ebike_distance_{model_type}.png"
        insights["shap"]["summary_url"] = f"/data/model-lab/models/{model_type}/{summary_name}"
        insights["shap"]["distance_dependence_url"] = f"/data/model-lab/models/{model_type}/{distance_name}"
        write_json(model_output_dir / "insights.json", insights)
        shutil.copy2(ARTIFACT_DIR / summary_name, model_output_dir / summary_name)
        shutil.copy2(ARTIFACT_DIR / distance_name, model_output_dir / distance_name)


def export_dashboard():
    baseline_path = BACKEND_DIR / "datasets" / "baseline.csv"
    dataframe = pd.read_csv(baseline_path)
    write_json(OUTPUT_DIR / "dataset-insights.json", build_dataset_insights(dataframe, "baseline.csv"))

    session = SessionLocal()
    try:
        district_map = asyncio.run(build_district_policy_map(session))
    finally:
        session.close()
    write_json(OUTPUT_DIR / "district-boundaries.json", district_map)


def export_kmedian():
    source_directory = BACKEND_DIR / "weights" / "kmedian" / "default"
    destination_directory = OUTPUT_DIR / "kmedian"
    destination_directory.mkdir(parents=True, exist_ok=True)
    for filename in ("solution.json", "metadata.json"):
        shutil.copy2(source_directory / filename, destination_directory / filename)


def main():
    export_models()
    export_dashboard()
    export_kmedian()
    write_json(
        OUTPUT_DIR / "showcase.json",
        {
            "mode": "static",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "github_url": GITHUB_URL,
            "training_available": False,
            "kmedian_solving_available": False,
        },
    )
    print(f"Static showcase exported to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
