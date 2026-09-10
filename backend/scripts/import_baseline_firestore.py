from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402


def native(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def main():
    parser = argparse.ArgumentParser(description="Upload baseline.csv as one Firestore document per survey row")
    parser.add_argument("--file", default=str(BACKEND_DIR / "datasets" / "baseline.csv"))
    parser.add_argument("--collection", default=settings.FIRESTORE_BASELINE_COLLECTION)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    dataframe = pd.read_csv(arguments.file)
    required = {"rowid", "age", "gender", "origlat", "origlon", "destlat", "destlon", "vehic", "alt_ebike"}
    missing = sorted(required - set(dataframe.columns))
    if missing:
        raise ValueError(f"Baseline CSV is missing required columns: {', '.join(missing)}")
    if dataframe["rowid"].duplicated().any():
        raise ValueError("rowid must be unique before importing")
    print(f"Validated {len(dataframe):,} rows and {len(dataframe.columns)} columns from {arguments.file}")
    if arguments.dry_run:
        return

    from services.firebase_service import firestore_client

    client = firestore_client()
    collection = client.collection(arguments.collection)
    imported_at = datetime.now(timezone.utc)
    batch = client.batch()
    pending = 0
    completed = 0
    for record in dataframe.to_dict(orient="records"):
        document_id = str(int(record["rowid"]))
        payload = {key: native(value) for key, value in record.items()}
        payload["_imported_at"] = imported_at
        batch.set(collection.document(document_id), payload)
        pending += 1
        if pending == 400:
            batch.commit()
            completed += pending
            print(f"Uploaded {completed:,}/{len(dataframe):,}")
            batch = client.batch()
            pending = 0
    if pending:
        batch.commit()
        completed += pending
    print(f"Uploaded {completed:,} rows to {arguments.collection}")


if __name__ == "__main__":
    main()
