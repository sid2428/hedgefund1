"""Base agent: shared Groq client, retry/backoff, logging, JSON parsing.

Groq's API is OpenAI-compatible chat completions. The default model is
`llama-3.3-70b-versatile` with a 128k context window — adequate for full SEC
filings without aggressive chunking.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from groq import APIConnectionError, APIError, AsyncGroq, RateLimitError
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.utils.logger import get_logger

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_jinja_env = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR)),
    autoescape=select_autoescape(disabled_extensions=("j2",)),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


class BaseAgent:
    """Common Groq plumbing for the four pipeline agents."""

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self.client = AsyncGroq(
            api_key=settings.GROQ_API_KEY,
            timeout=timeout or settings.GROQ_TIMEOUT_SECONDS,
        )
        self.model = model or settings.GROQ_MODEL
        self.max_tokens = max_tokens or settings.GROQ_MAX_TOKENS
        self.log = get_logger(self.__class__.__name__)

    # ---- Prompt rendering -------------------------------------------------
    @staticmethod
    def render_prompt(template_name: str, **context: Any) -> str:
        template = _jinja_env.get_template(template_name)
        return template.render(**context)

    # ---- LLM call with retry ---------------------------------------------
    async def call_claude(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Send a single user prompt to Groq and return the assistant text.

        Method name kept as `call_claude` so existing tests / callers don't
        churn; the underlying client is `AsyncGroq` (OpenAI-compatible).
        """
        attempt = 0
        async for attempt_ctx in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=15),
            retry=retry_if_exception_type((RateLimitError, APIConnectionError, APIError)),
            reraise=True,
        ):
            with attempt_ctx:
                attempt += 1
                started = time.perf_counter()
                messages: list[dict[str, str]] = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": prompt})

                response = await self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=max_tokens or self.max_tokens,
                    temperature=temperature,
                    messages=messages,
                )
                duration_ms = (time.perf_counter() - started) * 1000
                content = self._extract_content(response)
                usage = getattr(response, "usage", None)
                self.log.info(
                    "llm_call",
                    provider="groq",
                    model=self.model,
                    attempt=attempt,
                    duration_ms=round(duration_ms, 1),
                    input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
                    output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
                )
                return content

        # Unreachable; AsyncRetrying re-raises on exhaustion.
        raise RuntimeError("call_claude exhausted retries without raising")

    @staticmethod
    def _extract_content(response: Any) -> str:
        """Pull the assistant text from a chat-completions response."""
        choices = getattr(response, "choices", None) or []
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        if message is None:
            return ""
        return (getattr(message, "content", None) or "").strip()

    # ---- JSON parsing -----------------------------------------------------
    @staticmethod
    def parse_json_response(response: str) -> Any:
        """Strip markdown fences and parse JSON. Returns None on failure."""
        if not response:
            return None
        cleaned = response.strip()
        # Strip leading "```json" or "```" fences and trailing fences.
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        # Sometimes the model emits trailing prose after the JSON; try to find the
        # outermost JSON value (object or array).
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        # Try to extract the first balanced JSON value.
        for opener, closer in (("[", "]"), ("{", "}")):
            start = cleaned.find(opener)
            if start == -1:
                continue
            depth = 0
            for i, ch in enumerate(cleaned[start:], start=start):
                if ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cleaned[start : i + 1])
                        except json.JSONDecodeError:
                            break
        return None
