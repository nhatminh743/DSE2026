from __future__ import annotations

import json
import sys

from services.kmedian_jobs import run_kmedian_job
from services.model_training import run_training_job


def main():
    if len(sys.argv) != 4:
        raise RuntimeError("Usage: job_worker <job_type> <run_id> <payload>")
    job_type = sys.argv[1]
    run_id = sys.argv[2]
    payload = json.loads(sys.argv[3])
    if job_type == "model":
        run_training_job(
            run_id=run_id,
            source_type=payload["source_type"],
            source_path=payload.get("source_path"),
            test_size=float(payload.get("test_size", 0.2)),
            n_estimators=int(payload.get("n_estimators", 100)),
            model_types=payload.get("model_types", ["gradient_boosting", "random_forest", "decision_tree"]),
        )
        return
    if job_type == "kmedian":
        run_kmedian_job(
            run_id=run_id,
            k_stations=int(payload["k_stations"]),
            sample_percent=float(payload.get("sample_percent", 100)),
        )
        return
    raise ValueError(f"Unsupported job type: {job_type}")


if __name__ == "__main__":
    main()
