from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import joblib

from services.model_training import clean_training_data, simulate_monte_carlo
from services.survey_data import load_baseline_dataframe


MAX_UNCOMPRESSED_BUNDLE_BYTES = 250 * 1024 * 1024
ALLOWED_BUNDLE_FILES = {
    "fallback_mode_model.joblib",
    "current_mode_model.joblib",
    "model_metadata.json",
    "training_snapshot.csv",
}


def simulate_uploaded_bundle(
    bundle_bytes: bytes,
    iterations: int = 500,
    ban_car: bool = True,
) -> dict[str, Any]:
    buffer = io.BytesIO(bundle_bytes)
    if not zipfile.is_zipfile(buffer):
        raise ValueError("Uploaded file is not a valid ZIP bundle")

    with tempfile.TemporaryDirectory(prefix="dse-model-bundle-") as temporary_directory:
        output_directory = Path(temporary_directory)
        with zipfile.ZipFile(buffer) as archive:
            members = {Path(item.filename).name: item for item in archive.infolist() if not item.is_dir()}
            total_size = sum(item.file_size for item in members.values())
            if total_size > MAX_UNCOMPRESSED_BUNDLE_BYTES:
                raise ValueError("Model bundle is too large after decompression")
            if "fallback_mode_model.joblib" not in members:
                raise ValueError("Bundle is missing fallback_mode_model.joblib")
            for filename in ALLOWED_BUNDLE_FILES & members.keys():
                destination = output_directory / filename
                with archive.open(members[filename]) as source, destination.open("wb") as target:
                    target.write(source.read())

        # joblib uses pickle internally. The UI explicitly warns users to upload
        # only bundles they created or otherwise trust.
        fallback_model = joblib.load(output_directory / "fallback_mode_model.joblib")
        snapshot_path = output_directory / "training_snapshot.csv"
        if snapshot_path.exists():
            import pandas as pd

            raw_dataframe = pd.read_csv(snapshot_path)
            data_source = "bundle_training_snapshot"
        else:
            raw_dataframe = load_baseline_dataframe()
            data_source = "baseline_csv"
        dataframe = clean_training_data(raw_dataframe)
        metadata_path = output_directory / "model_metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else None
        return {
            "status": "ready",
            "data_source": data_source,
            "metadata": metadata,
            "monte_carlo": simulate_monte_carlo(
                fallback_model,
                dataframe,
                ban_car=ban_car,
                iterations=iterations,
            ),
        }
