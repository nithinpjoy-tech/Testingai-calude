"""tests/conftest.py — shared fixtures for the test suite."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

SAMPLE_JSON = Path(__file__).parent.parent / "data/samples/pppoe_vlan_mismatch.json"


@pytest.fixture()
def sample_json_path() -> Path:
    return SAMPLE_JSON


@pytest.fixture()
def mock_claude():
    """Patch anthropic.Anthropic so no real API calls are made in tests."""
    with patch("anthropic.Anthropic") as mock:
        instance = MagicMock()
        mock.return_value = instance
        # Canned response — matches expected XML output schema
        instance.messages.create.return_value = MagicMock(
            content=[MagicMock(text="<triage><root_cause>VLAN mismatch</root_cause></triage>")],
            usage=MagicMock(input_tokens=512, output_tokens=256),
        )
        yield instance
