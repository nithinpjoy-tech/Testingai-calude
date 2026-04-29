"""Triage engine.

Takes a parsed `TestRun`, calls the LLM provider with our system prompt,
validates the response against `TriageResult`, and records to the audit log.
"""

from __future__ import annotations

import structlog
from pydantic import ValidationError

from .audit import AuditLog
from .config import TriageConfig
from .llm import LLMProvider
from .models import TestRun, TriageResult, Verdict
from .prompts import SYSTEM_PROMPT, build_user_prompt

log = structlog.get_logger(__name__)


class TriageError(RuntimeError):
    """Raised when triage cannot produce a valid result."""


class TriageEngine:
    def __init__(self, llm: LLMProvider, cfg: TriageConfig, audit: AuditLog):
        self._llm = llm
        self._cfg = cfg
        self._audit = audit

    def triage(self, run: TestRun) -> TriageResult:
        if run.verdict != Verdict.FAIL:
            log.warning("triage.non_fail_input", verdict=run.verdict)

        # Send the canonical JSON form so the LLM receives exactly what we model.
        run_json = run.model_dump_json(indent=2, exclude_none=True)
        user_prompt = build_user_prompt(run_json)

        self._audit.record(
            "llm.request",
            {"test_id": run.test_id, "system_prompt_len": len(SYSTEM_PROMPT), "user_prompt_len": len(user_prompt)},
        )

        try:
            parsed, raw = self._llm.complete_json(SYSTEM_PROMPT, user_prompt)
        except Exception as e:
            self._audit.record("llm.error", {"test_id": run.test_id, "error": str(e)})
            raise TriageError(f"LLM call failed: {e}") from e

        try:
            result = TriageResult.model_validate({**parsed, "raw_llm_response": raw})
        except ValidationError as e:
            self._audit.record(
                "llm.schema_violation",
                {"test_id": run.test_id, "errors": e.errors(), "raw": raw[:1000]},
            )
            raise TriageError(
                "LLM response did not match TriageResult schema. "
                "Inspect prompt / model config. Errors: " + str(e.errors()[:3])
            ) from e

        # Confidence floor enforcement.
        if result.diagnosis.confidence < self._cfg.require_confidence_above:
            log.warning(
                "triage.low_confidence",
                confidence=result.diagnosis.confidence,
                floor=self._cfg.require_confidence_above,
            )

        # Evidence requirement.
        if self._cfg.cite_evidence_required and not result.diagnosis.evidence:
            raise TriageError("LLM returned a diagnosis with no evidence. Rejected.")

        self._audit.record(
            "llm.result",
            {
                "test_id": run.test_id,
                "category": result.diagnosis.category.value,
                "confidence": result.diagnosis.confidence,
                "fix_steps": len(result.fix_script.steps),
                "evidence_count": len(result.diagnosis.evidence),
            },
        )
        return result
