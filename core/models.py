from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

STATUSES = {"open", "ready", "running", "blocked", "review", "done", "rejected"}
TIERS = {"strategic", "default", "cheap"}
ROLES = ["strategist", "researcher", "red_team", "editor", "commercial_bridge", "archivist"]
TASK_FIELDS = ["ID", "priority", "domain", "task", "status", "created_at", "updated_at", "source", "definition_of_done", "dependencies", "model_tier", "estimated_cost", "actual_cost", "output_artifacts"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_path(path: str) -> str:
    p = PurePosixPath(path)
    if not path or "\\" in path or "\x00" in path or p.is_absolute() or ".." in p.parts:
        raise ValueError("Недопустимый путь файла")
    if not path.startswith("data/") or p.suffix not in {".md", ".txt", ".json", ".csv", ".jsonl"}:
        raise ValueError("Допустимы только текстовые файлы внутри data/")
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in p.parts):
        raise ValueError("Недопустимое имя файла")
    return path


def parse_backlog(text: str) -> list[dict]:
    tasks = []
    for index, row in enumerate(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))), 1):
        item = {key: row.get(key, "") or "" for key in TASK_FIELDS}
        item["ID"] = item["ID"] or f"VM-{index:03d}"
        item["created_at"] = item["created_at"] or "2026-09-29"
        item["updated_at"] = item["updated_at"] or item["created_at"]
        item["source"] = item["source"] or "spec/BACKLOG.csv"
        item["model_tier"] = item["model_tier"] or ("cheap" if item["domain"] == "archive" else "default")
        item["status"] = item["status"] or "open"
        item["priority"] = item["priority"] or "P1"
        tasks.append(item)
    validate_tasks(tasks)
    return tasks


def write_backlog(tasks: list[dict]) -> str:
    validate_tasks(tasks)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, TASK_FIELDS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(tasks)
    return buffer.getvalue()


def validate_tasks(tasks: list[dict]) -> None:
    seen = set()
    for task in tasks:
        task_id = task.get("ID", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", task_id) or task_id in seen:
            raise ValueError("Некорректный или повторяющийся ID задачи")
        seen.add(task_id)
        if task.get("status") not in STATUSES or task.get("priority") not in {"P0", "P1", "P2", "P3"}:
            raise ValueError("Некорректный статус или приоритет")
        if task.get("model_tier") not in TIERS or not task.get("task") or not task.get("definition_of_done"):
            raise ValueError("Нужны текст задачи, критерий готовности и model_tier")


def validate_state(state: dict) -> None:
    if not isinstance(state.get("identity"), dict):
        raise ValueError("STATE должен содержать identity")
    constraints = state.get("constraints", {})
    if any(constraints.get(key) is not False for key in ["image_generation", "video_generation", "autopublish"]):
        raise ValueError("Разрешена только текстовая работа без публикации")
    for key in ["active_questions", "current_hypotheses", "open_decisions"]:
        if not isinstance(state.get(key), list):
            raise ValueError(f"STATE.{key} должен быть массивом")


def validate_workspace(data: dict) -> None:
    validate_state(data["state"])
    validate_tasks(data["backlog"])
    for artifact in data["artifacts"].values():
        safe_path(artifact["path"])
    if data.get("schema_version") != 1:
        raise ValueError("Неподдерживаемая версия хранилища")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactDraft(StrictModel):
    title: str
    type: Literal["research", "strategy", "editorial", "decision", "report", "archive", "other"]
    extension: Literal["md", "txt", "json", "csv"]
    content: str


class Proposal(StrictModel):
    summary: str
    artifacts: list[ArtifactDraft]
    findings: list[str]
    hypotheses: list[str]
    decisions: list[str]
    rejected_ideas: list[str]
    next_tasks: list[str]
    why_viktor: str
    why_now: str
    evidence: str
    non_generic: str
    test_30_days: str
    horizon_6_24_months: str
    falsification: str


class Critique(StrictModel):
    flags: list[str]
    summary: str


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"
