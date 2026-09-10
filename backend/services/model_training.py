from __future__ import annotations

import json
import math
import os
import shutil
import traceback
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.multioutput import MultiOutputClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier
from sklearn.utils.class_weight import compute_sample_weight
from app.config import settings
from services.model_insights import (
    generate_model_insights_from_dataframe,
    normalize_model_columns,
)
from services.survey_data import load_survey_dataframe

NUMERICAL_FEATURES = ["OD_dist", "travtime", "dist_to_pub"]
CATEGORICAL_FEATURES = ["age", "occup", "gender", "purp", "status", "own"]
ALT_COLUMNS = [
    "alt_car",
    "alt_ebike",
    "alt_bike",
    "alt_bus",
    "alt_ltrain",
    "alt_taxi",
    "alt_walk",
]
REQUIRED_COLUMNS = NUMERICAL_FEATURES + CATEGORICAL_FEATURES + ALT_COLUMNS + ["vehic"]
SUPPORTED_MODEL_TYPES = ("gradient_boosting", "random_forest", "decision_tree")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_json_value(value: Any):
    if isinstance(value, dict):
        return {str(key): safe_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        number = float(value)
        return None if math.isnan(number) or math.isinf(number) else number
    if pd.isna(value):
        return None
    return value


def write_json(path: Path, payload: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(safe_json_value(payload), file, ensure_ascii=False, indent=2)
    os.replace(temporary_path, path)


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_run_directory(run_id: str) -> Path:
    return Path(settings.MODEL_RUN_DIR) / run_id


def update_status(run_id: str, **updates):
    path = get_run_directory(run_id) / "status.json"
    status = read_json(path) if path.exists() else {}
    status.update(updates)
    status["updated_at"] = utc_now()
    write_json(path, status)


def create_training_run(source_type: str, source_path: str | None, parameters: dict) -> str:
    run_id = uuid.uuid4().hex
    run_dir = get_run_directory(run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(run_dir / "status.json", {
        "run_id": run_id,
        "state": "queued",
        "progress": 0,
        "message": "Training run queued",
        "source_type": source_type,
        "source_path": source_path,
        "parameters": parameters,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    })
    return run_id


def load_source_dataframe(source_type: str, source_path: str | None) -> pd.DataFrame:
    if source_type == "csv":
        if not source_path:
            raise ValueError("source_path is required for CSV training")
        path = Path(source_path)
        if not path.exists():
            raise FileNotFoundError(f"Dataset not found: {path}")
        return pd.read_csv(path)

    if source_type == "database":
        return load_survey_dataframe(db=None, max_rows=settings.MAX_TRAINING_ROWS)

    raise ValueError(f"Unsupported source type: {source_type}")


def clean_training_data(df: pd.DataFrame) -> pd.DataFrame:
    result = normalize_model_columns(df)
    result = result.replace(["NA", "N/A", "null", "None", ""], np.nan).copy()
    missing = [column for column in REQUIRED_COLUMNS if column not in result.columns]
    if missing:
        raise ValueError("Dataset is missing required columns: " + ", ".join(missing))

    for column in NUMERICAL_FEATURES:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    for column in ALT_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0).clip(0, 1).astype(int)

    result["vehic"] = result["vehic"].astype("string")
    result = result.dropna(subset=["vehic"])
    result = result[result["vehic"].str.strip() != ""]
    return result.reset_index(drop=True)


def build_preprocessor() -> ColumnTransformer:
    numerical = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ])
    categorical = Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value="missing")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    return ColumnTransformer([
        ("num", numerical, NUMERICAL_FEATURES),
        ("cat", categorical, CATEGORICAL_FEATURES),
    ])


def build_classifier(model_type: str, n_estimators: int):
    if model_type == "gradient_boosting":
        return GradientBoostingClassifier(
            n_estimators=n_estimators,
            max_depth=3,
            random_state=settings.RANDOM_SEED,
        )
    if model_type == "random_forest":
        return RandomForestClassifier(
            n_estimators=n_estimators,
            class_weight="balanced",
            random_state=settings.RANDOM_SEED,
            n_jobs=-1,
        )
    if model_type == "decision_tree":
        return DecisionTreeClassifier(
            max_depth=12,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=settings.RANDOM_SEED,
        )
    raise ValueError(f"Unsupported model type: {model_type}")


def build_model_pipeline(model_type: str, n_estimators: int, multioutput: bool = False) -> Pipeline:
    classifier = build_classifier(model_type, n_estimators)
    if multioutput:
        classifier = MultiOutputClassifier(classifier, n_jobs=-1)
    return Pipeline([
        ("preprocessor", build_preprocessor()),
        ("classifier", classifier),
    ])


def get_positive_probability(probability_array: np.ndarray, classes: np.ndarray) -> np.ndarray:
    positive = np.where(np.asarray(classes) == 1)[0]
    return probability_array[:, positive[0]] if len(positive) else np.zeros(probability_array.shape[0])


def predict_fallback_probabilities(model: Pipeline, features: pd.DataFrame) -> np.ndarray:
    classifier = model.named_steps["classifier"]
    probabilities = model.predict_proba(features)
    columns = [
        get_positive_probability(probability, classifier.estimators_[index].classes_)
        for index, probability in enumerate(probabilities)
    ]
    matrix = np.nan_to_num(np.column_stack(columns), nan=0.0) + 1e-9
    return matrix / matrix.sum(axis=1, keepdims=True)


def create_eda_summary(df: pd.DataFrame) -> dict:
    mode_counts = df["vehic"].fillna("missing").value_counts().rename_axis("mode").reset_index(name="count").to_dict(orient="records")
    purpose_counts = df["purp"].fillna("missing").value_counts().rename_axis("purpose").reset_index(name="count").to_dict(orient="records")
    current_car = int((df["vehic"] == "car").sum())
    current_moto = int((df["vehic"] == "moto").sum())
    return {
        "row_count": int(len(df)),
        "mode_counts": mode_counts,
        "purpose_counts": purpose_counts,
        "affected_summary": {
            "current_car": current_car,
            "current_moto": current_moto,
            "total_car_users": current_car,
            "total_moto_users": current_moto,
            "total_affected": current_car + current_moto,
            "total_respondents": int(len(df)),
        },
    }


def feature_importance(model: Pipeline, multioutput: bool = False):
    preprocessor = model.named_steps["preprocessor"]
    classifier = model.named_steps["classifier"]
    names = preprocessor.get_feature_names_out()

    def rows(estimator):
        importances = getattr(estimator, "feature_importances_", None)
        if importances is None:
            coefficients = getattr(estimator, "coef_", None)
            if coefficients is None:
                return []
            importances = np.abs(np.asarray(coefficients)).mean(axis=0)
        return sorted([
            {"feature": name.split("__", 1)[-1], "importance": float(value)}
            for name, value in zip(names, importances)
        ], key=lambda item: item["importance"], reverse=True)[:20]

    if multioutput:
        return {name: rows(classifier.estimators_[index]) for index, name in enumerate(ALT_COLUMNS)}
    return rows(classifier)


def simulate_migration(model: Pipeline, df: pd.DataFrame, ban_car: bool) -> list[dict]:
    affected = df[df["vehic"].isin(["car", "moto"])]
    if affected.empty:
        return []
    probabilities = predict_fallback_probabilities(model, affected[NUMERICAL_FEATURES + CATEGORICAL_FEATURES])
    if ban_car:
        probabilities[:, ALT_COLUMNS.index("alt_car")] = 0.0
        probabilities = probabilities + 1e-9
        probabilities /= probabilities.sum(axis=1, keepdims=True)
    expected = probabilities.sum(axis=0)
    return sorted([
        {
            "mode": mode.replace("alt_", ""),
            "expected_users": float(expected[index]),
            "expected_percentage": float(100 * expected[index] / len(affected)),
        }
        for index, mode in enumerate(ALT_COLUMNS)
    ], key=lambda item: item["expected_users"], reverse=True)


def simulate_monte_carlo(
    model: Pipeline,
    df: pd.DataFrame,
    ban_car: bool,
    iterations: int = 500,
) -> dict:
    affected = df[df["vehic"].isin(["car", "moto"])]
    if affected.empty:
        return {"iterations": iterations, "affected_users": 0, "modes": []}
    features = affected[NUMERICAL_FEATURES + CATEGORICAL_FEATURES]
    probabilities = predict_fallback_probabilities(model, features)
    if ban_car:
        probabilities[:, ALT_COLUMNS.index("alt_car")] = 0.0
        probabilities = probabilities + 1e-9
        probabilities /= probabilities.sum(axis=1, keepdims=True)

    rng = np.random.default_rng(settings.RANDOM_SEED)
    cumulative = np.cumsum(probabilities, axis=1)
    counts = np.zeros((iterations, len(ALT_COLUMNS)), dtype=int)
    for iteration in range(iterations):
        draws = rng.random(len(affected))
        choices = (draws[:, None] > cumulative).sum(axis=1)
        counts[iteration] = np.bincount(choices, minlength=len(ALT_COLUMNS))

    rows = []
    for index, column in enumerate(ALT_COLUMNS):
        values = counts[:, index]
        rows.append({
            "mode": column.replace("alt_", ""),
            "mean_users": float(values.mean()),
            "mean_percentage": float(values.mean() * 100 / len(affected)),
            "p05_users": float(np.quantile(values, 0.05)),
            "p95_users": float(np.quantile(values, 0.95)),
        })
    rows.sort(key=lambda item: item["mean_users"], reverse=True)
    return {
        "iterations": iterations,
        "affected_users": int(len(affected)),
        "ban_car_fallback": ban_car,
        "modes": rows,
    }


def travel_time_elasticity(model: Pipeline, df: pd.DataFrame) -> list[dict]:
    affected = df[df["vehic"].isin(["car", "moto"])]
    if affected.empty:
        return []
    features = affected[NUMERICAL_FEATURES + CATEGORICAL_FEATURES].copy()
    classes = list(model.named_steps["classifier"].classes_)
    car_index = classes.index("car") if "car" in classes else None
    moto_index = classes.index("moto") if "moto" in classes else None
    rows = []
    for penalty in range(0, 65, 5):
        simulated = features.copy()
        simulated["travtime"] = simulated["travtime"] + penalty
        probabilities = model.predict_proba(simulated)
        car = float(probabilities[:, car_index].mean()) if car_index is not None else 0.0
        moto = float(probabilities[:, moto_index].mean()) if moto_index is not None else 0.0
        rows.append({
            "extra_delay_minutes": penalty,
            "car_probability": car,
            "moto_probability": moto,
            "alternative_probability": max(0.0, 1.0 - car - moto),
        })
    return rows


def package_artifacts(run_dir: Path):
    with zipfile.ZipFile(run_dir / "model_artifacts.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        allowed_suffixes = {".joblib", ".json", ".csv"}
        excluded = {"status.json", "error.json", "insight_error.json"}
        for path in sorted(run_dir.iterdir()):
            if path.is_file() and path.suffix in allowed_suffixes and path.name not in excluded:
                archive.write(path, arcname=path.name)


def atomic_copy(source: Path, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    shutil.copy2(source, temporary_path)
    os.replace(temporary_path, destination)


def promote_latest_artifacts(run_dir: Path):
    model_dir = Path(settings.MODEL_WEIGHT_DIR)
    model_dir.mkdir(parents=True, exist_ok=True)
    for filename in ["current_mode_model.joblib", "fallback_mode_model.joblib", "model_metadata.json", "solution.json", "eda_summary.json"]:
        source = run_dir / filename
        if source.exists():
            atomic_copy(source, model_dir / filename)


def run_training_job(
    run_id: str,
    source_type: str,
    source_path: str | None,
    test_size: float = 0.2,
    n_estimators: int = 100,
    model_types: list[str] | None = None,
):
    run_dir = get_run_directory(run_id)
    try:
        requested_models = model_types or list(SUPPORTED_MODEL_TYPES)
        requested_models = list(dict.fromkeys(requested_models))
        unsupported = [name for name in requested_models if name not in SUPPORTED_MODEL_TYPES]
        if unsupported:
            raise ValueError("Unsupported model types: " + ", ".join(unsupported))
        if not requested_models:
            raise ValueError("Select at least one model type")

        update_status(run_id, state="running", progress=5, message="Loading source data", started_at=utc_now())
        raw_df = load_source_dataframe(source_type, source_path)
        actual_source = raw_df.attrs.get("source", source_type)
        update_status(
            run_id,
            progress=15,
            message="Cleaning and validating data",
            raw_row_count=len(raw_df),
            requested_source=source_type,
            actual_source=actual_source,
        )
        df = clean_training_data(raw_df)
        if len(df) < 20:
            raise ValueError("At least 20 valid rows are required for training")

        X = df[NUMERICAL_FEATURES + CATEGORICAL_FEATURES]
        y_current = df["vehic"]
        y_fallback = df[ALT_COLUMNS]
        stratify = y_current if y_current.value_counts().min() >= 2 else None
        X_train, X_test, y_train, y_test = train_test_split(X, y_current, test_size=test_size, random_state=settings.RANDOM_SEED, stratify=stratify)
        X_fallback_train, X_fallback_test, y_fallback_train, y_fallback_test = train_test_split(X, y_fallback, test_size=test_size, random_state=settings.RANDOM_SEED)
        model_outputs = {}
        trained_models = {}
        sample_weights = compute_sample_weight(class_weight="balanced", y=y_train)
        for index, model_type in enumerate(requested_models):
            start_progress = 25 + int(index * 40 / len(requested_models))
            update_status(
                run_id,
                progress=start_progress,
                message=f"Training {model_type.replace('_', ' ')} models",
                active_model=model_type,
            )
            current_model = build_model_pipeline(model_type, n_estimators, multioutput=False)
            current_model.fit(X_train, y_train, classifier__sample_weight=sample_weights)
            current_report = classification_report(
                y_test,
                current_model.predict(X_test),
                zero_division=0,
                output_dict=True,
            )

            fallback_model = build_model_pipeline(model_type, n_estimators, multioutput=True)
            fallback_model.fit(X_fallback_train, y_fallback_train)
            fallback_report = classification_report(
                y_fallback_test,
                fallback_model.predict(X_fallback_test),
                target_names=ALT_COLUMNS,
                zero_division=0,
                output_dict=True,
            )
            score = float(
                (
                    current_report.get("macro avg", {}).get("f1-score", 0)
                    + fallback_report.get("macro avg", {}).get("f1-score", 0)
                ) / 2
            )
            trained_models[model_type] = (current_model, fallback_model)
            model_outputs[model_type] = {
                "score": score,
                "metrics": {
                    "current_mode": current_report,
                    "fallback_modes": fallback_report,
                },
                "feature_importance": {
                    "current_mode": feature_importance(current_model),
                    "fallback_modes": feature_importance(fallback_model, multioutput=True),
                },
                "artifacts": {
                    "current_mode": f"current_mode_{model_type}.joblib",
                    "fallback_mode": f"fallback_mode_{model_type}.joblib",
                },
            }
            joblib.dump(current_model, run_dir / f"current_mode_{model_type}.joblib")
            joblib.dump(fallback_model, run_dir / f"fallback_mode_{model_type}.joblib")

        selected_default = max(model_outputs, key=lambda name: model_outputs[name]["score"])
        current_model, fallback_model = trained_models[selected_default]
        current_report = model_outputs[selected_default]["metrics"]["current_mode"]
        fallback_report = model_outputs[selected_default]["metrics"]["fallback_modes"]

        update_status(run_id, progress=75, message="Generating model analytics", active_model=None)
        eda_summary = create_eda_summary(df)
        results = {
            "run_id": run_id,
            "source_type": source_type,
            "actual_source": actual_source,
            "row_count": int(len(df)),
            "features": {"numerical": NUMERICAL_FEATURES, "categorical": CATEGORICAL_FEATURES, "fallback_targets": ALT_COLUMNS},
            "selected_default_model": selected_default,
            "models": model_outputs,
            "metrics": {"current_mode": current_report, "fallback_modes": fallback_report},
            "feature_importance": {"current_mode": feature_importance(current_model), "fallback_modes": feature_importance(fallback_model, multioutput=True)},
            "migration": {"normal": simulate_migration(fallback_model, df, False), "total_ice_ban": simulate_migration(fallback_model, df, True)},
            "monte_carlo": {
                "normal": simulate_monte_carlo(fallback_model, df, False),
                "total_ice_ban": simulate_monte_carlo(fallback_model, df, True),
            },
            "travel_time_elasticity": travel_time_elasticity(current_model, df),
            "eda": eda_summary,
        }
        metadata = {
            "run_id": run_id,
            "created_at": utc_now(),
            "numerical_features": NUMERICAL_FEATURES,
            "categorical_features": CATEGORICAL_FEATURES,
            "alt_cols": ALT_COLUMNS,
            "current_classes": [str(item) for item in current_model.named_steps["classifier"].classes_],
            "source_type": source_type,
            "actual_source": actual_source,
            "row_count": len(df),
            "random_seed": settings.RANDOM_SEED,
            "n_estimators": n_estimators,
            "test_size": test_size,
            "model_types": requested_models,
            "selected_default_model": selected_default,
        }
        update_status(run_id, progress=90, message="Saving model artifacts")
        joblib.dump(current_model, run_dir / "current_mode_model.joblib")
        joblib.dump(fallback_model, run_dir / "fallback_mode_model.joblib")
        write_json(run_dir / "model_metadata.json", metadata)
        write_json(run_dir / "eda_summary.json", eda_summary)
        write_json(run_dir / "solution.json", results)
        write_json(run_dir / "results.json", results)
        df.to_csv(run_dir / "training_snapshot.csv", index=False)
        package_artifacts(run_dir)
        promote_latest_artifacts(run_dir)

        update_status(run_id, state="completed", progress=100, message="Training completed and weights saved", completed_at=utc_now(), promoted_to_default=True, downloads={"bundle": f"/api/model-runs/{run_id}/download"})

        try:
            generated_insights = generate_model_insights_from_dataframe(df)
            write_json(run_dir / "model_insights.json", generated_insights)
        except Exception as insight_error:
            write_json(run_dir / "insight_error.json", {"error": str(insight_error)})
    except Exception as exc:
        write_json(run_dir / "error.json", {"error": str(exc), "traceback": traceback.format_exc()})
        update_status(run_id, state="failed", progress=100, message=str(exc), completed_at=utc_now())
