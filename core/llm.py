from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Proposal, Critique


@dataclass
class LLMResponse:
    text: str
    usage: dict
    response_id: str = ""
    search_calls: int = 0
    sources: list[dict] = field(default_factory=list)


class ProviderError(RuntimeError):
    pass


class ResponsesLLM:
    """Responses fallback adapter. Local STATE/files provide persistent memory.

    A response_id is saved for audit; it is not claimed to be an Agents session_id.
    No media, shell, eval, functions, or publishing tools are exposed to the model.
    """
    def __init__(self, api_key: str):
        from openai import OpenAI
        if not api_key:
            raise ValueError("Добавьте OPENAI_API_KEY в Secrets")
        self.client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1", timeout=120, max_retries=0)

    def complete(self, *, instructions: str, input_text: str, model: str,
                 effort: str, max_output: int, schema: dict | None = None,
                 web: bool = False) -> LLMResponse:
        arguments: dict[str, Any] = {
            "model": model, "instructions": instructions, "input": input_text,
            "reasoning": {"effort": effort}, "max_output_tokens": max_output,
            "store": False, "service_tier": "default",
        }
        if schema:
            arguments["text"] = {"format": {"type": "json_schema", "name": "angelis_result", "strict": True, "schema": schema}}
        if web:
            arguments.update({"tools": [{"type": "web_search", "search_context_size": "low"}],
                              "max_tool_calls": 1, "include": ["web_search_call.action.sources"]})
        try:
            response = self.client.responses.create(**arguments)
        except Exception as error:
            status = getattr(error, "status_code", None)
            suffix = f" (HTTP {status})" if status else ""
            raise ProviderError(f"OpenAI: {type(error).__name__}{suffix}. Запрос не повторяется автоматически; проверьте ключ, доступ к модели и журнал.") from None
        usage = response.usage.model_dump() if response.usage else {}
        sources = []
        calls = 0
        for output in response.output:
            item = output.model_dump()
            if item.get("type") == "web_search_call":
                calls += 1
                for source in (item.get("action") or {}).get("sources", []) or []:
                    if source.get("url"):
                        sources.append({"url": source["url"], "title": source.get("title", "")})
            for part in item.get("content", []) or []:
                for annotation in part.get("annotations", []) or []:
                    if annotation.get("type") == "url_citation":
                        sources.append({"url": annotation["url"], "title": annotation.get("title", "")})
        # Return billed usage even when output is incomplete. Caller records cost before validation.
        return LLMResponse(response.output_text, usage, response.id, calls, sources)


class MockLLM:
    """Explicit test-only provider; never wired into the production UI."""
    def complete(self, **kwargs) -> LLMResponse:
        import json
        schema = kwargs.get("schema") or {}
        properties = schema.get("properties", {})
        if "artifacts" in properties:
            payload = {
                "summary": "Тестовый цикл завершён. Синтетические данные; это не художественная рекомендация.",
                "artifacts": [{"title": "Mock cycle evidence", "type": "strategy", "extension": "md",
                               "content": "# MOCK: проверка полного цикла\n\nТест подтверждает создание файла и сохранение.\n\nГипотеза: требует материалов Виктора.\nТест 30 дней: собрать минимальные доказательства.\nОпровержение: материалы не показывают повторяющийся механизм.\n"}],
                "findings": ["MOCK: персистентность проверена"], "hypotheses": ["MOCK: проверяемая гипотеза"],
                "decisions": [], "rejected_ideas": ["MOCK: универсальная мотивационная рубрика"], "next_tasks": [],
                "why_viktor": "MOCK: четыре практики из seed", "why_now": "MOCK: первый цикл",
                "evidence": "MOCK: только seed STATE/BACKLOG", "non_generic": "MOCK: спецификация Виктора",
                "test_30_days": "MOCK: проверить на реальных материалах", "horizon_6_24_months": "MOCK: проверяемое направление",
                "falsification": "MOCK: отсутствие подтверждающих работ",
            }
            text = json.dumps(payload, ensure_ascii=False)
        elif "flags" in properties:
            text = json.dumps({"flags": [], "summary": "MOCK: проверка схемы критика"})
        else:
            text = "# MOCK role output\n\nСинтетическая записка для проверки оркестрации."
        return LLMResponse(text, {"input_tokens": 1000, "output_tokens": 500, "input_tokens_details": {"cached_tokens": 100}}, "mock-response")
