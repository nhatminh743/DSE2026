from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from services.policy_dashboard import build_policy_eda_from_dataframe, json_safe


def _histogram(series: pd.Series, bins: int = 10) -> list[dict[str, Any]]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return []
    counts, edges = np.histogram(values, bins=min(bins, max(1, values.nunique())))
    return [
        {
            "range": f"{edges[index]:.2g}–{edges[index + 1]:.2g}",
            "count": int(count),
        }
        for index, count in enumerate(counts)
    ]


def build_dataset_profile(dataframe: pd.DataFrame) -> dict[str, Any]:
    numeric_columns = list(dataframe.select_dtypes(include=np.number).columns)
    categorical_columns = [column for column in dataframe.columns if column not in numeric_columns]
    cell_count = int(dataframe.shape[0] * dataframe.shape[1])
    missing_cells = int(dataframe.isna().sum().sum())

    missing = (
        dataframe.isna().mean().mul(100).sort_values(ascending=False).head(15)
        if len(dataframe)
        else pd.Series(dtype=float)
    )
    numeric_distributions = [
        {"column": str(column), "values": _histogram(dataframe[column])}
        for column in numeric_columns[:6]
    ]
    categorical_distributions = []
    for column in categorical_columns[:6]:
        counts = dataframe[column].fillna("Missing").astype(str).value_counts().head(10)
        total = max(1, int(len(dataframe)))
        categorical_distributions.append(
            {
                "column": str(column),
                "values": [
                    {
                        "category": str(category),
                        "count": int(count),
                        "percentage": round(float(count / total * 100), 2),
                    }
                    for category, count in counts.items()
                ],
            }
        )

    correlations = []
    if len(numeric_columns) >= 2:
        matrix = dataframe[numeric_columns[:20]].corr(numeric_only=True)
        for left_index, left in enumerate(matrix.columns):
            for right in matrix.columns[left_index + 1 :]:
                value = matrix.loc[left, right]
                if pd.notna(value):
                    correlations.append(
                        {"left": str(left), "right": str(right), "correlation": round(float(value), 4)}
                    )
        correlations.sort(key=lambda row: abs(row["correlation"]), reverse=True)

    return json_safe(
        {
            "summary": {
                "rows": int(len(dataframe)),
                "columns": int(len(dataframe.columns)),
                "numeric_columns": len(numeric_columns),
                "categorical_columns": len(categorical_columns),
                "missing_cells": missing_cells,
                "missing_percentage": round(missing_cells / cell_count * 100, 2) if cell_count else 0,
            },
            "missing_by_column": [
                {"column": str(column), "percentage": round(float(value), 2)}
                for column, value in missing.items()
            ],
            "numeric_distributions": numeric_distributions,
            "categorical_distributions": categorical_distributions,
            "correlations": correlations[:12],
        }
    )


def build_dataset_insights(dataframe: pd.DataFrame, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "profile": build_dataset_profile(dataframe),
        "policy_eda": build_policy_eda_from_dataframe(dataframe, source=source),
    }
