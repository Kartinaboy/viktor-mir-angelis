from __future__ import annotations

import os
from zoneinfo import ZoneInfo

from .models import ROLES

# Standard rates from the individual model pages, checked 2026-09-30.
# Keep estimates conservative. Settings permits explicit pricing for custom model IDs.
PRICING = {
    "gpt-6-astra": {"input": 10.0, "cached": 1.0, "output": 50.0, "cache_write": 12.5, "context_limit": 1050000},
    "gpt-6-sol": {"input": 2.0, "cached": 0.2, "output": 10.0, "cache_write": 2.5, "context_limit": 1050000},
    "gpt-6-luna": {"input": 0.1, "cached": 0.01, "output": 0.5, "cache_write": 0.125, "context_limit": 1050000},
}
PRICING_SOURCES = [f"https://developers.openai.com/api/docs/models/{model}" for model in PRICING]


def defaults() -> dict:
    return {
        "models": {
            "strategic": os.getenv("OPENAI_MODEL_STRATEGIC", "gpt-6-astra"),
            "default": os.getenv("OPENAI_MODEL_DEFAULT", "gpt-6-sol"),
            "cheap": os.getenv("OPENAI_MODEL_CHEAP", "gpt-6-luna"),
        },
        "reasoning_effort": "medium",
        "daily_budget": float(os.getenv("ANGELIS_DAILY_BUDGET_USD", "2")),
        "run_budget": float(os.getenv("ANGELIS_RUN_BUDGET_USD", "0.35")),
        "max_output_tokens": 6000,
        "timezone": "Europe/Moscow",
        "roles": {role: True for role in ROLES},
        "web_research": False,
        "scheduler_enabled": False,
        "autonomous_mode": False,
        "jobs": [
            {"id": "morning", "title": "Утренний обзор STATE", "time": "08:00", "enabled": True},
            {"id": "backlog", "title": "Задача из BACKLOG", "time": "09:00", "enabled": True},
            {"id": "report", "title": "Вечерний отчёт", "time": "21:00", "enabled": True},
            {"id": "maintenance", "title": "Обслуживание архива", "time": "23:00", "enabled": True},
        ],
        "pricing": PRICING,
        "pricing_checked_at": "2026-09-30",
        "search_call_usd": 0.01,
    }


def validate_settings(settings: dict) -> None:
    ZoneInfo(settings["timezone"])
    if settings["reasoning_effort"] not in {"low", "medium", "high", "xhigh"}:
        raise ValueError("Некорректный reasoning effort")
    if not 0 < float(settings["daily_budget"]) <= 100 or not 0 < float(settings["run_budget"]) <= 20:
        raise ValueError("Лимиты должны быть положительными: день ≤ $100, запуск ≤ $20")
    if not 1000 <= settings["max_output_tokens"] <= 12000:
        raise ValueError("max_output_tokens должен быть от 1000 до 12000")
    for model in settings["models"].values():
        if not isinstance(model, str) or not model.strip() or model not in settings["pricing"]:
            raise ValueError("Для каждой модели нужна строка ID и цена в pricing")
    for rate in settings["pricing"].values():
        if any(float(rate.get(key, -1)) < 0 for key in ["input", "cached", "output", "cache_write"]):
            raise ValueError("Цены не могут быть отрицательными")
        if not 10000 <= int(rate.get("context_limit", 0)) <= 2000000:
            raise ValueError("Укажите допустимый размер контекста модели")
    for job in settings["jobs"]:
        hour, minute = (int(n) for n in job["time"].split(":"))
        if not 0 <= hour < 24 or not 0 <= minute < 60:
            raise ValueError("Некорректное время задания")
