from __future__ import annotations

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from mito_harness.config import settings


class LLMClient:
    """Neural Deep как основной провайдер, llm7 — fallback (OpenAI-compatible)."""

    def __init__(self) -> None:
        s = settings()
        if not s["neural_deep_api_key"] and not s["llm7_api_key"]:
            raise RuntimeError("Нужен NEURAL_DEEP_API_KEY или LLM7_API_KEY в .env")
        self.primary = None
        self.primary_model = s["neural_deep_model"]
        if s["neural_deep_api_key"]:
            self.primary = OpenAI(
                base_url=s["neural_deep_base_url"],
                api_key=s["neural_deep_api_key"],
                timeout=120.0,
            )
        self.fallback = None
        self.fallback_model = s["llm7_model"]
        if s["llm7_api_key"]:
            self.fallback = OpenAI(
                base_url=s["llm7_base_url"],
                api_key=s["llm7_api_key"],
                timeout=120.0,
            )

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=8))
    def chat(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 3500,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        last_err: Exception | None = None
        if self.primary:
            try:
                r = self.primary.chat.completions.create(
                    model=self.primary_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return (r.choices[0].message.content or "").strip()
            except Exception as e:  # noqa: BLE001
                last_err = e
        if self.fallback:
            r = self.fallback.chat.completions.create(
                model=self.fallback_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return (r.choices[0].message.content or "").strip()
        raise RuntimeError(f"LLM unavailable: {last_err}")


_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm
