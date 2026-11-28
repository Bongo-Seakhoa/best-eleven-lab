"""Decide whether a scheduled Pages rebuild would reuse the published inputs."""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from importlib.metadata import distributions
from pathlib import Path

import requests

PUBLISHED_INPUTS = "https://bongo-seakhoa.github.io/best-eleven-lab/data/build-inputs.json"


def build_inputs(source_state: Path, revision: str, runtime: dict) -> dict | None:
    try:
        sources = json.loads(source_state.read_text(encoding="utf-8"))
        digests = {key: sources[key]["sha256"] for key in ("matches", "people")}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not all(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha) for sha in digests.values()):
        return None
    return {"schema": "best-eleven/pages-inputs/v1", "revision": revision,
            "sourceDigests": digests, "runtime": runtime}


def runner_versions() -> dict:
    return {
        "python": platform.python_version(),
        "node": subprocess.check_output(["node", "--version"], text=True).strip(),
        "platform": [platform.system(), platform.machine(), *platform.libc_ver()],
        "packages": sorted([dist.metadata["Name"], dist.version] for dist in distributions()
                           if dist.metadata["Name"].lower() != "pip"),
    }


def needs_build(event: str, inputs: dict | None, run: str) -> bool:
    if event != "schedule" or inputs is None:
        return True
    try:
        with requests.get(PUBLISHED_INPUTS, params={"run": run},
                          headers={"Cache-Control": "no-cache"}, timeout=(3, 7)) as response:
            response.raise_for_status()
            return response.json() != inputs
    except (requests.RequestException, ValueError):
        print("Published build inputs could not be verified.")
        return True


def main() -> None:
    inputs = build_inputs(Path("data/raw/sources.json"), os.environ["GITHUB_SHA"], runner_versions())
    run = f'{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}'
    rebuild = needs_build(os.environ["GITHUB_EVENT_NAME"], inputs, run)
    cache_key = ""
    if inputs is not None:
        sources = inputs["sourceDigests"]
        cache_key = f'cricsheet-{sources["matches"]}-{sources["people"]}'
        stamp = Path(os.environ["RUNNER_TEMP"]) / "best-eleven-build-inputs.json"
        stamp.write_text(json.dumps(inputs, sort_keys=True) + "\n", encoding="utf-8")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        print(f"rebuild={str(rebuild).lower()}", file=output)
        print(f"raw_cache_key={cache_key}", file=output)
    print("Build and validate the site." if rebuild else "Published inputs match. Skipping rebuild and deployment.")


if __name__ == "__main__":
    main()
