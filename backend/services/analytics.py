import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from app.config import settings


MODEL_COLUMN_ALIASES = {
    "od_dist": "OD_dist",
    "oddist": "OD_dist",
    "od_distance": "OD_dist",
    "origin_destination_distance": "OD_dist",
    "travel_time": "travtime",
    "trav_time": "travtime",
    "traveltime": "travtime",
    "distance_to_public_transport": "dist_to_pub",
    "distance_to_transit": "dist_to_pub",
    "dist_to_public_transport": "dist_to_pub",
    "occupation": "occup",
    "purpose": "purp",
    "vehicle": "vehic",
    "district": "district_name",
}


def _column_key(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = normalized.replace("\ufeff", "").strip().casefold()
    normalized = re.sub(r"[\s-]+", "_", normalized)
    return re.sub(r"_+", "_", normalized)


def normalize_model_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map database/CSV column variants to trained-model names."""
    canonical_columns = {
        "OD_dist",
        "travtime",
        "dist_to_pub",
        "age",
        "occup",
        "gender",
        "purp",
        "status",
        "own",
        "vehic",
        "district_name",
        "rowid",
    }
    aliases = {
        _column_key(column): column for column in canonical_columns
    }
    aliases.update({
        _column_key(alias): canonical
        for alias, canonical in MODEL_COLUMN_ALIASES.items()
    })

    rename_map = {}
    matched = {}

    for original_column in df.columns:
        canonical = aliases.get(_column_key(original_column))
        if canonical is None:
            cleaned = str(original_column).replace("\ufeff", "").strip()
            if cleaned != original_column:
                rename_map[original_column] = cleaned
            continue

        if canonical in matched:
            raise ValueError(
                "Multiple source columns resolve to "
                f"{canonical!r}: {matched[canonical]!r} and "
                f"{original_column!r}"
            )

        matched[canonical] = original_column
        rename_map[original_column] = canonical

    return df.rename(columns=rename_map)


class ModelWeightsUnavailable(FileNotFoundError):
    """Raised when no promoted/default model weights exist."""


MODEL_WEIGHT_FILENAMES = {
    "current_mode_model": "current_mode_model.joblib",
    "fallback_mode_model": "fallback_mode_model.joblib",
    "metadata": "model_metadata.json",
}


def get_model_weight_paths() -> dict[str, Path]:
    directory = Path(settings.MODEL_WEIGHT_DIR)
    return {key: directory / filename for key, filename in MODEL_WEIGHT_FILENAMES.items()}


def get_model_weight_status() -> dict[str, Any]:
    paths = get_model_weight_paths()
    missing = [path.name for path in paths.values() if not path.exists()]
    if missing:
        return {
            "status": "no_weight_yet",
            "message": "No weight yet",
            "directory": str(settings.MODEL_WEIGHT_DIR),
            "missing_files": missing,
        }
    return {
        "status": "ready",
        "message": "Saved model weights are ready",
        "directory": str(settings.MODEL_WEIGHT_DIR),
        "files": {key: path.name for key, path in paths.items()},
    }


def _model_signature(paths: dict[str, Path]) -> tuple:
    return tuple(
        (key, path.name, path.stat().st_mtime_ns, path.stat().st_size)
        for key, path in sorted(paths.items())
    )


@lru_cache(maxsize=4)
def _load_model_artifacts_cached(model_directory: str, signature: tuple):
    model_dir = Path(model_directory)

    current_mode_model = joblib.load(
        model_dir / "current_mode_model.joblib"
    )

    fallback_mode_model = joblib.load(
        model_dir / "fallback_mode_model.joblib"
    )

    with (model_dir / "model_metadata.json").open("r", encoding="utf-8") as file:
        metadata = json.load(file)

    return {
        "current_mode_model": current_mode_model,
        "fallback_mode_model": fallback_mode_model,
        "metadata": metadata,
    }


def load_model_artifacts():
    paths = get_model_weight_paths()
    status = get_model_weight_status()
    if status["status"] != "ready":
        raise ModelWeightsUnavailable(
            "No weight yet. Missing: "
            + ", ".join(status["missing_files"])
            + f". Expected directory: {status['directory']}"
        )
    return _load_model_artifacts_cached(
        str(settings.MODEL_WEIGHT_DIR),
        _model_signature(paths),
    )


def prepare_model_input(df: pd.DataFrame) -> pd.DataFrame:
    artifacts = load_model_artifacts()
    metadata = artifacts["metadata"]

    numerical_features = metadata["numerical_features"]
    categorical_features = metadata["categorical_features"]

    result = normalize_model_columns(df)

    missing_columns = [
        column
        for column in numerical_features + categorical_features
        if column not in result.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing model input columns: "
            + ", ".join(missing_columns)
            + ". Available columns: "
            + ", ".join(repr(column) for column in result.columns)
        )

    for col in numerical_features:
        result[col] = pd.to_numeric(
            result[col],
            errors="coerce"
        )

    return result[numerical_features + categorical_features]


def predict_affected_users(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns one row per affected respondent with:
    - current mode probabilities
    - fallback mode probabilities
    - normalized fallback probabilities
    """

    artifacts = load_model_artifacts()

    current_model = artifacts["current_mode_model"]
    fallback_model = artifacts["fallback_mode_model"]
    alt_cols = artifacts["metadata"]["alt_cols"]

    df = normalize_model_columns(df)

    if "vehic" not in df.columns:
        raise ValueError("The dataset does not contain the vehic column")

    affected_mask = df["vehic"].isin(["car", "moto"])
    affected = df.loc[affected_mask].copy()

    if affected.empty:
        return affected

    X_affected = prepare_model_input(affected)

    # Current mode probabilities
    current_probas = current_model.predict_proba(X_affected)
    current_classes = list(
        current_model.named_steps["classifier"].classes_
    )

    for idx, class_name in enumerate(current_classes):
        affected[f"p_current_{class_name}"] = current_probas[:, idx]

    # Fallback probabilities
    fallback_probas = fallback_model.predict_proba(X_affected)

    classifier = fallback_model.named_steps["classifier"]
    raw_columns = []

    for index, proba in enumerate(fallback_probas):
        classes = np.asarray(classifier.estimators_[index].classes_)
        positive_index = np.where(classes == 1)[0]
        raw_columns.append(
            proba[:, positive_index[0]]
            if len(positive_index)
            else np.zeros(len(affected))
        )

    raw_probs = np.column_stack(raw_columns)

    raw_probs = np.nan_to_num(raw_probs, nan=0.0)
    raw_probs = raw_probs + 1e-9

    normalized_probs = raw_probs / raw_probs.sum(
        axis=1,
        keepdims=True
    )

    for idx, mode in enumerate(alt_cols):
        affected[f"p_{mode.replace('alt_', '')}"] = normalized_probs[:, idx]

    # Scenario: ICE car and motorbike ban
    # Remove car fallback from alternatives
    ban_probs = normalized_probs.copy()

    if "alt_car" in alt_cols:
        car_idx = alt_cols.index("alt_car")
        ban_probs[:, car_idx] = 0.0

    ban_probs = ban_probs + 1e-9
    ban_probs = ban_probs / ban_probs.sum(
        axis=1,
        keepdims=True
    )

    for idx, mode in enumerate(alt_cols):
        clean_mode = mode.replace("alt_", "")
        affected[f"p_ban_{clean_mode}"] = ban_probs[:, idx]

    affected["affected"] = True

    return affected
