from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from .models import DemoRun, utc_now


class RunStore:
    """Small durable JSON store suitable for the local sales-demo MVP."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.runs_dir = data_dir / "runs"
        self._lock = threading.RLock()
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def _record_path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{12}", run_id):
            raise ValueError("Invalid run id")
        return self.runs_dir / run_id / "run.json"

    def create(self, run: DemoRun) -> DemoRun:
        with self._lock:
            path = self._record_path(run.id)
            path.parent.mkdir(parents=True, exist_ok=False)
            self._write(path, run)
        return run

    def save(self, run: DemoRun) -> DemoRun:
        with self._lock:
            run.updated_at = utc_now()
            self._write(self._record_path(run.id), run)
        return run

    def get(self, run_id: str) -> DemoRun | None:
        try:
            path = self._record_path(run_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        with self._lock:
            return DemoRun.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[DemoRun]:
        records: list[DemoRun] = []
        with self._lock:
            for path in self.runs_dir.glob("*/run.json"):
                try:
                    records.append(DemoRun.model_validate_json(path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    continue
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def run_dir(self, run_id: str) -> Path:
        path = (self.runs_dir / run_id).resolve()
        if path.parent != self.runs_dir.resolve():
            raise ValueError("Invalid run id")
        return path

    @staticmethod
    def _write(path: Path, run: DemoRun) -> None:
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
