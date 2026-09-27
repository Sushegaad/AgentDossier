import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SEED = ROOT / "data" / "seed" / "top_100_ai_agents_by_domain_2026-09-25.xlsx"


@pytest.fixture(scope="session")
def seed_import():
    pytest.importorskip("openpyxl")
    from agentdossier.connectors.seed_xlsx import import_seed

    return import_seed(SEED)


def load_fixture(*parts: str):
    return json.loads((FIXTURES.joinpath(*parts)).read_text())
