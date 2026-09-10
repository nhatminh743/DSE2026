from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

import joblib
import matplotlib

# Required when Matplotlib runs inside FastAPI without a desktop.
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
from sqlalchemy.orm import Session

from app.config import settings
from services.survey_data import load_survey_dataframe


NUMERICAL_FEATURES = [
    "OD_dist",
    "travtime",
    "dist_to_pub",
]

CATEGORICAL_FEATURES = [
    "age",
    "occup",
    "gender",
    "purp",
    "status",
    "own",
]

ALT_COLUMNS = [
    "alt_car",
    "alt_ebike",
    "alt_bike",
    "alt_bus",
    "alt_ltrain",
    "alt_taxi",
    "alt_walk",
]

MODEL_COLUMNS = [
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
]

COLUMN_ALIASES = {
    "od_dist": "OD_dist",
    "od_distance": "OD_dist",
    "oddist": "OD_dist",
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
}


def _column_key(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = (
        normalized.replace("\ufeff", "")
        .strip()
        .replace(" ", "_")
        .replace("-", "_")
        .casefold()
    )
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized


def normalize_model_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    canonical_lookup = {_column_key(column): column for column in MODEL_COLUMNS}
    alias_lookup = {
        _column_key(alias): canonical
        for alias, canonical in COLUMN_ALIASES.items()
    }
    rename_map = {}
    matched_columns = {}

    for original_column in result.columns:
        key = _column_key(original_column)
        canonical_column = canonical_lookup.get(key) or alias_lookup.get(key)

        if canonical_column is None:
            cleaned_column = str(original_column).replace("\ufeff", "").strip()
            if cleaned_column != original_column:
                rename_map[original_column] = cleaned_column
            continue

        if canonical_column in matched_columns:
            previous = matched_columns[canonical_column]
            raise ValueError(
                "Multiple source columns resolve to "
                f"{canonical_column!r}: {previous!r} and {original_column!r}"
            )

        matched_columns[canonical_column] = original_column
        rename_map[original_column] = canonical_column

    return result.rename(columns=rename_map)


def _write_json(path: Path, payload: dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            payload,
            file,
            ensure_ascii=False,
            indent=2,
        )


def fetch_insight_data(
    db: Session,
    max_rows: int = 100_000,
) -> pd.DataFrame:
    return load_survey_dataframe(db=db, max_rows=max_rows)


def clean_insight_data(
    df: pd.DataFrame,
) -> pd.DataFrame:
    result = normalize_model_columns(df)
    print(
        "[MODEL INSIGHTS] Normalized columns:",
        [repr(column) for column in result.columns],
    )

    result = result.replace(
        [
            "NA",
            "N/A",
            "null",
            "None",
            "",
        ],
        np.nan,
    ).copy()

    required_columns = (
        NUMERICAL_FEATURES
        + CATEGORICAL_FEATURES
        + ["vehic"]
    )

    missing_columns = [
        column
        for column in required_columns
        if column not in result.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing model columns: "
            + ", ".join(missing_columns)
            + ". Available columns: "
            + ", ".join(repr(column) for column in result.columns)
        )

    for column in NUMERICAL_FEATURES:
        result[column] = pd.to_numeric(
            result[column],
            errors="coerce",
        )

    result = result.dropna(subset=["vehic"])

    return result.reset_index(drop=True)


def clean_feature_name(
    feature_name: str,
) -> str:
    """
    Convert names such as:
        num__OD_dist
        cat__age_less_18

    into:
        OD_dist
        age_less_18
    """
    if "__" in feature_name:
        return feature_name.split("__", 1)[1]

    return feature_name


def extract_importance(
    feature_names: list[str],
    estimator: Any,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    if not hasattr(estimator, "feature_importances_"):
        return []

    importances = estimator.feature_importances_

    rows = [
        {
            "feature": clean_feature_name(
                str(feature_name)
            ),
            "importance": round(
                float(importance),
                8,
            ),
        }
        for feature_name, importance in zip(
            feature_names,
            importances,
        )
    ]

    rows.sort(
        key=lambda row: row["importance"],
        reverse=True,
    )

    return rows[:top_n]


def extract_positive_shap_values(
    raw_shap_values: Any,
) -> np.ndarray:
    """
    Normalize different SHAP outputs into:

        (number_of_rows, number_of_features)
    """
    if isinstance(raw_shap_values, list):
        # Binary classifiers may return:
        # [negative_class_values, positive_class_values]
        if len(raw_shap_values) > 1:
            return np.asarray(raw_shap_values[1])

        return np.asarray(raw_shap_values[0])

    values = np.asarray(raw_shap_values)

    # Newer SHAP versions can return:
    # rows x features x classes
    if values.ndim == 3:
        if values.shape[2] > 1:
            return values[:, :, 1]

        return values[:, :, 0]

    return values


def save_shap_plots(
    fallback_model: Any,
    model_input: pd.DataFrame,
    output_directory: Path,
    sample_size: int = 1000,
    filename_suffix: str = "",
) -> dict[str, str | None]:
    """
    Generate SHAP plots for the fallback e-bike estimator.
    """
    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    preprocessor = fallback_model.named_steps[
        "preprocessor"
    ]

    classifier = fallback_model.named_steps[
        "classifier"
    ]

    if not hasattr(classifier, "estimators_"):
        raise ValueError(
            "Fallback classifier does not expose "
            "one estimator per fallback mode"
        )

    ebike_index = ALT_COLUMNS.index("alt_ebike")
    ebike_estimator = classifier.estimators_[
        ebike_index
    ]

    if len(model_input) > sample_size:
        sampled_input = model_input.sample(
            n=sample_size,
            random_state=settings.RANDOM_SEED,
        )
    else:
        sampled_input = model_input.copy()

    transformed = preprocessor.transform(
        sampled_input
    )

    feature_names = [
        clean_feature_name(str(name))
        for name in preprocessor.get_feature_names_out()
    ]

    transformed_df = pd.DataFrame(
        transformed,
        columns=feature_names,
        index=sampled_input.index,
    )

    explainer = shap.TreeExplainer(
        ebike_estimator
    )

    raw_shap_values = explainer.shap_values(
        transformed_df
    )

    shap_values = extract_positive_shap_values(
        raw_shap_values
    )

    summary_filename = f"shap_ebike_summary{filename_suffix}.png"

    dependence_filename = f"shap_ebike_distance{filename_suffix}.png"

    summary_path = (
        output_directory / summary_filename
    )

    dependence_path = (
        output_directory / dependence_filename
    )

    # SHAP summary plot
    plt.figure(figsize=(10, 7))

    shap.summary_plot(
        shap_values,
        transformed_df,
        max_display=10,
        show=False,
    )

    plt.title(
        "What Drives E-Bike Adoption?",
        fontsize=14,
        fontweight="bold",
    )

    plt.tight_layout()

    plt.savefig(
        summary_path,
        dpi=160,
        bbox_inches="tight",
    )

    plt.close("all")

    # SHAP dependence plot for OD distance
    if "OD_dist" in transformed_df.columns:
        plt.figure(figsize=(9, 6))

        shap.dependence_plot(
            "OD_dist",
            shap_values,
            transformed_df,
            show=False,
        )

        plt.title(
            "Trip Distance and E-Bike Likelihood",
            fontsize=14,
            fontweight="bold",
        )

        plt.tight_layout()

        plt.savefig(
            dependence_path,
            dpi=160,
            bbox_inches="tight",
        )

        plt.close("all")

        dependence_url = (
            f"/artifacts/{dependence_filename}"
        )
    else:
        dependence_url = None

    return {
        "summary_url": (
            f"/artifacts/{summary_filename}"
        ),
        "distance_dependence_url": (
            dependence_url
        ),
    }


def calculate_elasticity(
    current_model: Any,
    model_input: pd.DataFrame,
) -> list[dict[str, float]]:
    """
    Reproduce the travel-time sensitivity analysis
    from analysis.txt.
    """
    affected_mask = model_input.index

    if len(affected_mask) == 0:
        return []

    classifier = current_model.named_steps[
        "classifier"
    ]

    classes = list(classifier.classes_)

    car_index = (
        classes.index("car")
        if "car" in classes
        else None
    )

    moto_index = (
        classes.index("moto")
        if "moto" in classes
        else None
    )

    rows = []

    for penalty in range(0, 65, 5):
        simulated = model_input.copy()

        simulated["travtime"] = (
            pd.to_numeric(
                simulated["travtime"],
                errors="coerce",
            )
            + penalty
        )

        probabilities = (
            current_model.predict_proba(
                simulated
            )
        )

        car_probability = (
            float(
                probabilities[
                    :,
                    car_index,
                ].mean()
            )
            if car_index is not None
            else 0.0
        )

        moto_probability = (
            float(
                probabilities[
                    :,
                    moto_index,
                ].mean()
            )
            if moto_index is not None
            else 0.0
        )

        alternative_probability = max(
            0.0,
            1.0
            - car_probability
            - moto_probability,
        )

        rows.append({
            "extra_delay_minutes": penalty,
            "car_probability": round(
                car_probability,
                6,
            ),
            "moto_probability": round(
                moto_probability,
                6,
            ),
            "alternative_probability": round(
                alternative_probability,
                6,
            ),
        })

    return rows


def _fallback_probability_matrix(
    fallback_model: Any,
    model_input: pd.DataFrame,
) -> np.ndarray:
    classifier = fallback_model.named_steps["classifier"]
    raw_probabilities = fallback_model.predict_proba(model_input)
    columns = []
    for index, probabilities in enumerate(raw_probabilities):
        classes = np.asarray(classifier.estimators_[index].classes_)
        positive = np.flatnonzero(classes == 1)
        if len(positive):
            columns.append(probabilities[:, positive[0]])
        else:
            columns.append(np.zeros(len(model_input)))
    matrix = np.nan_to_num(np.column_stack(columns), nan=0.0) + 1e-9
    return matrix / matrix.sum(axis=1, keepdims=True)


def calculate_ebike_partial_dependence(
    fallback_model: Any,
    model_input: pd.DataFrame,
) -> list[dict[str, float]]:
    distances = pd.to_numeric(model_input["OD_dist"], errors="coerce").dropna()
    if distances.empty:
        return []
    sampled = model_input.sample(
        n=min(2000, len(model_input)),
        random_state=settings.RANDOM_SEED,
    ).copy()
    lower, upper = distances.quantile([0.05, 0.95]).tolist()
    if lower == upper:
        grid = np.asarray([lower])
    else:
        grid = np.linspace(lower, upper, 20)
    ebike_index = ALT_COLUMNS.index("alt_ebike")
    rows = []
    for distance in grid:
        simulated = sampled.copy()
        simulated["OD_dist"] = float(distance)
        probability = _fallback_probability_matrix(fallback_model, simulated)[:, ebike_index].mean()
        rows.append({
            "distance_km": round(float(distance), 3),
            "ebike_probability": round(float(probability), 6),
        })
    return rows


def calculate_monte_carlo(
    fallback_model: Any,
    model_input: pd.DataFrame,
    ban_car: bool,
    iterations: int = 500,
) -> dict[str, Any]:
    probabilities = _fallback_probability_matrix(fallback_model, model_input)
    if ban_car:
        probabilities[:, ALT_COLUMNS.index("alt_car")] = 0.0
        probabilities = probabilities + 1e-9
        probabilities /= probabilities.sum(axis=1, keepdims=True)
    rng = np.random.default_rng(settings.RANDOM_SEED)
    cumulative = np.cumsum(probabilities, axis=1)
    counts = np.zeros((iterations, len(ALT_COLUMNS)), dtype=int)
    for iteration in range(iterations):
        choices = (rng.random(len(model_input))[:, None] > cumulative).sum(axis=1)
        counts[iteration] = np.bincount(choices, minlength=len(ALT_COLUMNS))
    modes = []
    for index, column in enumerate(ALT_COLUMNS):
        values = counts[:, index]
        modes.append({
            "mode": column.replace("alt_", ""),
            "mean_users": round(float(values.mean()), 2),
            "mean_percentage": round(float(values.mean() * 100 / len(model_input)), 2),
            "p05_users": float(np.quantile(values, 0.05)),
            "p95_users": float(np.quantile(values, 0.95)),
        })
    modes.sort(key=lambda row: row["mean_users"], reverse=True)
    return {
        "iterations": iterations,
        "affected_users": int(len(model_input)),
        "ban_car_fallback": ban_car,
        "modes": modes,
    }


def generate_model_insights_from_dataframe(
    raw_data: pd.DataFrame,
    model_directory: Path | None = None,
    model_type: str | None = None,
) -> dict[str, Any]:
    model_directory = Path(model_directory or settings.MODEL_WEIGHT_DIR)

    if model_type and not all(character.isalnum() or character == "_" for character in model_type):
        raise ValueError("Invalid model type")

    current_filename = f"current_mode_{model_type}.joblib" if model_type else "current_mode_model.joblib"
    fallback_filename = f"fallback_mode_{model_type}.joblib" if model_type else "fallback_mode_model.joblib"

    current_model_path = model_directory / current_filename

    fallback_model_path = model_directory / fallback_filename

    if not current_model_path.exists():
        raise FileNotFoundError(
            f"{current_filename} was not found. "
            "Train the models first."
        )

    if not fallback_model_path.exists():
        raise FileNotFoundError(
            f"{fallback_filename} was not found. "
            "Train the models first."
        )

    current_model = joblib.load(
        current_model_path
    )

    fallback_model = joblib.load(
        fallback_model_path
    )

    print("[MODEL INSIGHTS] Source row count:", len(raw_data))
    print("[MODEL INSIGHTS] Exact columns:")
    for column in raw_data.columns:
        print(repr(column))

    df = clean_insight_data(raw_data)

    affected = df[
        df["vehic"].isin(["car", "moto"])
    ].copy()

    if affected.empty:
        raise ValueError(
            "No car or motorbike respondents were found"
        )

    model_input = affected[
        NUMERICAL_FEATURES
        + CATEGORICAL_FEATURES
    ].copy()

    current_preprocessor = (
        current_model.named_steps[
            "preprocessor"
        ]
    )

    fallback_preprocessor = (
        fallback_model.named_steps[
            "preprocessor"
        ]
    )

    current_classifier = (
        current_model.named_steps[
            "classifier"
        ]
    )

    fallback_classifier = (
        fallback_model.named_steps[
            "classifier"
        ]
    )

    current_feature_names = list(
        current_preprocessor
        .get_feature_names_out()
    )

    fallback_feature_names = list(
        fallback_preprocessor
        .get_feature_names_out()
    )

    current_importance = extract_importance(
        current_feature_names,
        current_classifier,
    )

    fallback_importance = {}

    if hasattr(
        fallback_classifier,
        "estimators_",
    ):
        for index, mode in enumerate(
            ALT_COLUMNS
        ):
            estimator = (
                fallback_classifier
                .estimators_[index]
            )

            fallback_importance[mode] = (
                extract_importance(
                    fallback_feature_names,
                    estimator,
                )
            )

    elasticity = calculate_elasticity(
        current_model,
        model_input,
    )
    partial_dependence = calculate_ebike_partial_dependence(
        fallback_model,
        model_input,
    )
    monte_carlo = {
        "normal": calculate_monte_carlo(fallback_model, model_input, False),
        "total_ice_ban": calculate_monte_carlo(fallback_model, model_input, True),
    }

    shap_error = None

    try:
        shap_plots = save_shap_plots(
            fallback_model=fallback_model,
            model_input=model_input,
            output_directory=Path(settings.ARTIFACT_DIR),
            filename_suffix=f"_{model_type}" if model_type else "",
        )
    except Exception as exc:
        shap_error = str(exc)

        shap_plots = {
            "summary_url": None,
            "distance_dependence_url": None,
        }

    result = {
        "model_type": model_type,
        "affected_respondents": int(
            len(affected)
        ),
        "source_rows": int(len(df)),
        "feature_importance": {
            "current_mode": current_importance,
            "fallback_modes": (
                fallback_importance
            ),
        },
        "elasticity": elasticity,
        "partial_dependence": partial_dependence,
        "monte_carlo": monte_carlo,
        "shap": {
            **shap_plots,
            "error": shap_error,
        },
    }

    _write_json(
        model_directory
        / (f"model_insights_{model_type}.json" if model_type else "model_insights.json"),
        result,
    )

    return result


def generate_model_insights(
    db: Session,
) -> dict[str, Any]:
    raw_data = fetch_insight_data(db)
    print("[MODEL INSIGHTS] Source: PostgreSQL travel_survey")
    return generate_model_insights_from_dataframe(raw_data)


def load_model_insights(
    model_directory: Path | None = None,
    model_type: str | None = None,
) -> dict[str, Any]:
    directory = Path(model_directory or settings.MODEL_WEIGHT_DIR)
    filename = f"model_insights_{model_type}.json" if model_type else "model_insights.json"
    path = directory / filename

    if not path.exists():
        raise FileNotFoundError(
            "Model insights have not been generated"
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)
