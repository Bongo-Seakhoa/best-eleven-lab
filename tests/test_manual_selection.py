"""Manual swaps use the browser's real selection engine, without network/data builds."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node is required to exercise the browser engine")
def test_manual_selection_records_presets_and_exact_swaps():
    fixtures = ROOT / "tests" / "fixtures" / "selection"
    result = subprocess.run(
        [NODE, str(ROOT / "site" / "tests" / "manual_cli.mjs"),
         str(fixtures / "men-test-australia.json"), str(fixtures / "men-t20i-australia.json"),
         str(fixtures / "men-test-australia-historic.json")],
        capture_output=True, text=True, timeout=30, check=True,
    )
    assert json.loads(result.stdout)["ok"]
