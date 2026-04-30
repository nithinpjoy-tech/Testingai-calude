"""LLM provider abstraction.

Demo uses OpenAI directly. Production can swap to Azure OpenAI by setting
LLM_PROVIDER=azure_openai in the environment — no code change in the rest
of the application.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import structlog
from openai import OpenAI, AzureOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import LLMConfig

log = structlog.get_logger(__name__)


class LLMProvider(ABC):
    """Abstract LLM provider. Implementations call a chat-completion endpoint
    and return parsed JSON plus the raw text for audit/UI display."""

    @abstractmethod
    def complete_json(self, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], str]:
        """Return (parsed_json, raw_response_text)."""


class OpenAIProvider(LLMProvider):
    """Direct OpenAI API. Used for the demo."""

    def __init__(self, cfg: LLMConfig, api_key: str):
        if not api_key or api_key == "sk-replace-me":
            raise RuntimeError(
                "OPENAI_API_KEY is missing or still set to the placeholder. "
                "Copy .env.example to .env and set a real key."
            )
        self._cfg = cfg
        self._client = OpenAI(api_key=api_key, timeout=cfg.request_timeout_seconds)

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def complete_json(self, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], str]:
        log.info("llm.request", provider="openai", model=self._cfg.model)
        resp = self._client.chat.completions.create(
            model=self._cfg.model,
            temperature=self._cfg.temperature,
            max_tokens=self._cfg.max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = resp.choices[0].message.content or ""
        log.info(
            "llm.response",
            provider="openai",
            model=self._cfg.model,
            tokens_in=getattr(resp.usage, "prompt_tokens", None),
            tokens_out=getattr(resp.usage, "completion_tokens", None),
        )
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            log.error("llm.json_parse_failed", raw=raw[:500], error=str(e))
            raise RuntimeError(f"LLM returned invalid JSON: {e}\nRaw: {raw[:500]}") from e
        return parsed, raw


class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI deployment. Stubbed for production use."""

    def __init__(self, cfg: LLMConfig, api_key: str, endpoint: str, deployment: str, api_version: str):
        if not all([api_key, endpoint, deployment]):
            raise RuntimeError("Azure OpenAI requires AZURE_OPENAI_API_KEY/_ENDPOINT/_DEPLOYMENT.")
        self._cfg = cfg
        self._deployment = deployment
        self._client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
            timeout=cfg.request_timeout_seconds,
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def complete_json(self, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], str]:
        log.info("llm.request", provider="azure_openai", deployment=self._deployment)
        resp = self._client.chat.completions.create(
            model=self._deployment,
            temperature=self._cfg.temperature,
            max_tokens=self._cfg.max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = resp.choices[0].message.content or ""
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"LLM returned invalid JSON: {e}\nRaw: {raw[:500]}") from e
        return parsed, raw


def build_llm_provider(cfg: LLMConfig, env: dict[str, str]) -> LLMProvider:
    """Factory: pick a provider based on config.provider."""
    provider = (cfg.provider or "openai").lower()
    if provider == "openai":
        return OpenAIProvider(cfg, api_key=env.get("OPENAI_API_KEY", ""))
    if provider == "azure_openai":
        return AzureOpenAIProvider(
            cfg,
            api_key=env.get("AZURE_OPENAI_API_KEY", ""),
            endpoint=env.get("AZURE_OPENAI_ENDPOINT", ""),
            deployment=env.get("AZURE_OPENAI_DEPLOYMENT", ""),
            api_version=env.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
        )
    raise ValueError(f"Unknown LLM provider: {provider}")