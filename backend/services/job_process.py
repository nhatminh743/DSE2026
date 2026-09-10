from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parent.parent
TERMINAL_STATES = {"completed", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    os.replace(temporary_path, path)


def update_job_status(status_path: Path, **updates: Any) -> dict[str, Any]:
    status = read_json(status_path) if status_path.exists() else {}
    status.update(updates)
    status["updated_at"] = utc_now()
    write_json_atomic(status_path, status)
    return status


def launch_job(job_type: str, run_id: str, payload: dict[str, Any], status_path: Path) -> int:
    command = [sys.executable, "-m", "services.job_worker", job_type, run_id, json.dumps(payload)]
    log_path = status_path.parent / "worker.log"
    log_file = log_path.open("a", encoding="utf-8")
    options: dict[str, Any] = {"cwd": str(BACKEND_DIR), "stdout": log_file, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **options)
    finally:
        log_file.close()
    update_job_status(status_path, pid=process.pid, state="queued", message="Job queued")
    return process.pid


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def terminate_job(status_path: Path, timeout_seconds: float = 5.0) -> dict[str, Any]:
    if not status_path.exists():
        raise FileNotFoundError("Job not found")
    status = read_json(status_path)
    if status.get("state") in TERMINAL_STATES:
        return status
    pid = status.get("pid")
    update_job_status(status_path, state="stopping", message="Stopping job", cancel_requested=True)
    if pid:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], check=False, capture_output=True)
            else:
                process_group = os.getpgid(int(pid))
                os.killpg(process_group, signal.SIGTERM)
                deadline = time.time() + timeout_seconds
                while time.time() < deadline and _process_exists(int(pid)):
                    time.sleep(0.1)
                if _process_exists(int(pid)):
                    os.killpg(os.getpgid(int(pid)), signal.SIGKILL)
        except Exception as exc:
            update_job_status(status_path, stop_warning=str(exc))
    latest = read_json(status_path)
    if latest.get("state") not in {"completed", "failed"}:
        latest = update_job_status(status_path, state="cancelled", progress=latest.get("progress", 0), message="Job cancelled by user", cancelled_at=utc_now())
    return latest
