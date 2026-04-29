"""Structured JSON logger + append-only audit trail."""
import json
import logging
from datetime import datetime
from pathlib import Path

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            '{"time":"%(asctime)s","level":"%(levelname)s","module":"%(name)s","msg":"%(message)s"}'
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

def audit(event: str, payload: dict, audit_path: str = "data/audit.jsonl") -> None:
    """Append one audit record — every LLM call and every executed command."""
    Path(audit_path).parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.utcnow().isoformat(), "event": event, **payload}
    with open(audit_path, "a") as f:
        f.write(json.dumps(record) + "\n")
