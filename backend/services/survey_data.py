from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine


VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quoted_table_name(table_name: str) -> str:
    parts = table_name.split(".")
    if not parts or any(not VALID_IDENTIFIER.fullmatch(part) for part in parts):
        raise ValueError(f"Invalid configured table name: {table_name!r}")
    return ".".join(f'"{part}"' for part in parts)


def _fallback_path() -> Path:
    configured_path = Path(settings.SURVEY_FALLBACK_FILE).resolve()
    if configured_path.exists():
        return configured_path

    checkout_path = Path(settings.DATASET_DIR).resolve().parent.parent / "analysis" / "data" / "hn_survey_26k.csv"
    return checkout_path


def load_baseline_dataframe(max_rows: int | None = None) -> pd.DataFrame:
    """Load the canonical baseline CSV without consulting PostgreSQL."""
    if settings.USE_FIRESTORE_BASELINE:
        from services.firebase_service import load_baseline_collection

        dataframe = pd.DataFrame(load_baseline_collection(max_rows or settings.MAX_TRAINING_ROWS))
        if dataframe.empty:
            raise FileNotFoundError(
                f"Firestore collection {settings.FIRESTORE_BASELINE_COLLECTION!r} is empty"
            )
        dataframe.attrs["source"] = "firestore_baseline"
        return dataframe
    path = Path(settings.POLICY_DASHBOARD_FILE).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Baseline survey dataset does not exist: {path}")

    dataframe = pd.read_csv(path, nrows=max_rows or settings.MAX_TRAINING_ROWS)
    dataframe.attrs["source"] = "baseline_csv"
    dataframe.attrs["source_path"] = str(path)
    return dataframe


def load_survey_dataframe(
    db: Session | None = None,
    max_rows: int | None = None,
) -> pd.DataFrame:
    max_rows = max_rows or settings.MAX_TRAINING_ROWS
    query = text(f"SELECT * FROM {quoted_table_name(settings.SURVEY_TABLE)} LIMIT :max_rows")
    database_error: Exception | None = None

    try:
        if db is not None:
            dataframe = pd.DataFrame(
                db.execute(query, {"max_rows": max_rows}).mappings().all()
            )
        else:
            with engine.connect() as connection:
                dataframe = pd.read_sql(query, connection, params={"max_rows": max_rows})

        if not dataframe.empty:
            dataframe.attrs["source"] = "database"
            return dataframe
    except Exception as exc:
        database_error = exc
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass

    fallback_path = _fallback_path()
    if not fallback_path.exists():
        message = f"Survey database is unavailable and fallback dataset does not exist: {fallback_path}"
        if database_error is not None:
            message += f". Database error: {database_error}"
        raise FileNotFoundError(message)

    dataframe = pd.read_csv(fallback_path, nrows=max_rows)
    dataframe.attrs["source"] = "csv_fallback"
    dataframe.attrs["source_path"] = str(fallback_path)
    return dataframe
