"""Utilidades compartidas por los tests. pytest carga este archivo solo.

`load_fixture("football_data/team_86.json")` lee una respuesta real de la API guardada en
tests/fixtures/. Así los tests no llaman a la API ni gastan cuota.
"""

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())
