"""Configuration loading. YAML defaults overridden by environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4-turbo"
    temperature: float = 0.1
    max_tokens: int = 3000
    request_timeout_seconds: int = 60
    max_retries: int = 3


class ExecutorConfig(BaseModel):
    backend: str = "simulated"
    dry_run: bool = False
    step_timeout_seconds: int = 30
    halt_on_step_failure: bool = True


class TriageConfig(BaseModel):
    require_confidence_above: float = 0.0
    cite_evidence_required: bool = True


class UIConfig(BaseModel):
    title: str = "Test Failure Triage — AI Assistant"
    show_raw_llm_response: bool = True


class AuditConfig(BaseModel):
    enabled: bool = True
    path: str = "./audit.log"
    redact_keys: list[str] = Field(default_factory=lambda: ["api_key", "password", "secret"])


class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
    triage: TriageConfig = Field(default_factory=TriageConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)


def _apply_env_overrides(cfg: AppConfig, env: dict[str, str]) -> AppConfig:
    """Selected env vars override YAML config values."""
    if v := env.get("LLM_PROVIDER"):
        cfg.llm.provider = v
    if v := env.get("OPENAI_MODEL"):
        cfg.llm.model = v
    if v := env.get("EXECUTOR_BACKEND"):
        cfg.executor.backend = v
    if v := env.get("AUDIT_LOG_PATH"):
        cfg.audit.path = v
    return cfg


def load_config(path: str | Path | None = None, env: dict[str, str] | None = None) -> AppConfig:
    env = dict(env if env is not None else os.environ)
    yaml_path = Path(path) if path else Path(__file__).parent.parent.parent / "config" / "default.yaml"
    raw: dict[str, Any] = {}
    if yaml_path.exists():
        raw = yaml.safe_load(yaml_path.read_text()) or {}
    cfg = AppConfig.model_validate(raw)
    return _apply_env_overrides(cfg, env)