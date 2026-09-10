import pandas as pd
from sqlalchemy.orm import Session

from services.analytics import (
    normalize_model_columns,
    predict_affected_users,
)
from services.district_centers import assign_nearest_district
from services.survey_data import load_survey_dataframe


def load_district_survey_data(
    db: Session,
    district_centers: list[dict],
) -> pd.DataFrame:
    dataframe = normalize_model_columns(load_survey_dataframe(db=db))
    return assign_nearest_district(dataframe, district_centers)


def get_district_affected_summary(
    db: Session,
    district_centers: list[dict],
    scenario: str = "ice_ban"
):
    """
    Returns affected respondents grouped by district.

    A respondent is affected when vehic is car or moto.
    """

    dataframe = load_district_survey_data(db, district_centers)
    if "vehic" not in dataframe.columns:
        return []
    affected = dataframe[dataframe["vehic"].isin(["car", "moto"])].copy()
    if affected.empty:
        return []
    grouped = (
        affected.groupby("district_name", dropna=False)
        .agg(
            affected_count=("vehic", "size"),
            affected_car=("vehic", lambda values: int((values == "car").sum())),
            affected_moto=("vehic", lambda values: int((values == "moto").sum())),
        )
        .reset_index()
        .sort_values("affected_count", ascending=False)
    )
    total_affected = int(grouped["affected_count"].sum())

    return [
        {
            "district_name": row["district_name"],
            "affected_respondents": int(row["affected_count"]),
            "affected_car": int(row["affected_car"]),
            "affected_moto": int(row["affected_moto"]),
            "affected_percentage": round(100.0 * int(row["affected_count"]) / total_affected, 2) if total_affected else 0.0,
        }
        for _, row in grouped.iterrows()
    ]


def get_district_predictions(
    db: Session,
    district_centers: list[dict],
    scenario: str = "ice_ban"
):
    """
    Get district-level predictions for fallback modes.
    """
    df = load_district_survey_data(db, district_centers)

    print("[DISTRICT ANALYTICS] DataFrame columns:")
    for column in df.columns:
        print(repr(column))

    df = normalize_model_columns(df)

    df = df[df["vehic"].isin(["car", "moto"])].copy() if "vehic" in df.columns else pd.DataFrame()
    if "district_name" not in df.columns:
        df["district_name"] = "Unknown"
    df["district_name"] = df["district_name"].fillna("Unknown").astype(str)

    if df.empty:
        return []

    predicted = predict_affected_users(df)

    if predicted.empty:
        return []

    probability_columns = [
        col
        for col in predicted.columns
        if col.startswith("p_")
    ]

    aggregations = {"affected": "sum"}

    if "rowid" in predicted.columns:
        aggregations["rowid"] = "count"

    for col in probability_columns:
        aggregations[col] = "mean"

    grouped = (
        predicted
        .groupby(
            ["district_name"],
            dropna=False
        )
        .agg(aggregations)
        .reset_index()
    )

    if "rowid" in grouped.columns:
        grouped = grouped.rename(columns={"rowid": "affected_respondents"})
    else:
        counts = (
            predicted.groupby("district_name", dropna=False)
            .size()
            .rename("affected_respondents")
            .reset_index()
        )
        grouped = grouped.merge(counts, on="district_name", how="left")

    grouped = grouped.fillna(0)
    grouped["expected_current_car"] = (
        grouped["affected_respondents"]
        * grouped.get("p_current_car", 0)
    )
    grouped["expected_current_moto"] = (
        grouped["affected_respondents"]
        * grouped.get("p_current_moto", 0)
    )

    probability_prefix = "p_ban_" if scenario == "ice_ban" else "p_"
    for mode in ["car", "ebike", "bike", "bus", "ltrain", "taxi", "walk"]:
        source_column = f"{probability_prefix}{mode}"
        if source_column in grouped.columns:
            grouped[f"p_{mode}"] = grouped[source_column]

    return grouped.to_dict(orient="records")
