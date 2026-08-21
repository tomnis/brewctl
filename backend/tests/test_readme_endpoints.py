"""README's endpoint tables must match the OpenAPI schemas.

Run in a subprocess deliberately: the generator imports `brewctl.api.server`,
which builds HttpScale/HttpValve at import time. Importing it inside this
process would bind the real classes and break the api tests, whose conftest
patches those classes for the `client` fixture.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "backend" / "scripts" / "gen_endpoint_docs.py"


def test_readme_endpoint_tables_are_current():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "README endpoint tables are stale -- run `make docs`.\n" + result.stderr
    )
