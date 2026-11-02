import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import AgentProfile  # noqa: E402


@pytest.fixture
def profile() -> AgentProfile:
    return AgentProfile.from_yaml(ROOT / "config" / "agent.yaml")
