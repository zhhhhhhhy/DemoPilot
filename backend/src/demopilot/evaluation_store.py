from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from .evaluation_models import EvaluationRun
from .models import utc_now


class EvaluationStore:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "evaluations"
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)

    def _record_path(self, evaluation_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{12}", evaluation_id):
            raise ValueError("Invalid evaluation id")
        return self.root / evaluation_id / "evaluation.json"

    def create(self, evaluation: EvaluationRun) -> EvaluationRun:
        with self._lock:
            path = self._record_path(evaluation.id)
            path.parent.mkdir(parents=True, exist_ok=False)
            self._write(path, evaluation)
        return evaluation

    def save(self, evaluation: EvaluationRun) -> EvaluationRun:
        with self._lock:
            evaluation.updated_at = utc_now()
            self._write(self._record_path(evaluation.id), evaluation)
        return evaluation

    def get(self, evaluation_id: str) -> EvaluationRun | None:
        try:
            path = self._record_path(evaluation_id)
        except ValueError:
            return None
        if not path.is_file():
            return None
        with self._lock:
            return EvaluationRun.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[EvaluationRun]:
        evaluations: list[EvaluationRun] = []
        with self._lock:
            for path in self.root.glob("*/evaluation.json"):
                try:
                    evaluations.append(
                        EvaluationRun.model_validate_json(path.read_text(encoding="utf-8"))
                    )
                except (OSError, ValueError):
                    continue
        return sorted(evaluations, key=lambda item: item.created_at, reverse=True)

    def latest_baseline(
        self, provider: str, *, exclude_id: str
    ) -> EvaluationRun | None:
        return next(
            (
                item
                for item in self.list()
                if item.id != exclude_id
                and item.status == "completed"
                and item.request.provider == provider
            ),
            None,
        )

    def save_report(self, evaluation: EvaluationRun, content: str) -> Path:
        path = self._record_path(evaluation.id).parent / "report.md"
        temp = path.with_suffix(".tmp")
        temp.write_text(content, encoding="utf-8")
        temp.replace(path)
        return path

    def report_path(self, evaluation_id: str) -> Path | None:
        try:
            path = self._record_path(evaluation_id).parent / "report.md"
        except ValueError:
            return None
        return path if path.is_file() else None

    @staticmethod
    def _write(path: Path, evaluation: EvaluationRun) -> None:
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(evaluation.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)
