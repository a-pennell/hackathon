"""The tests read golden charts, and the golden charts are also what the demo runs on. A demo left mid-run (a note read,
proposals accepted, a follow-up landed) used to fail a dozen tests for no real reason. So the suite never reads the live
data directory: before any `ehr` module is imported, this builds a clean copy in a temp directory and points
EHR_DATA_DIR at it.

A chart is taken from the working tree when it is in its starting state, so an intentional edit to a golden file is
what gets tested. When the working file carries demo state, the committed version (git HEAD) is used instead.
Recordings (`*.raw.json`) are copied as they are; validated queues are never copied.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "data"


def _demo_state(chart: dict, queue_dir: Path) -> bool:
    if chart.get("plans") or chart.get("orders") or chart.get("documents") or chart.get("note_plan_items") or chart.get("corrections"):
        return True
    for k in ("problems", "observations", "medications", "links", "insights"):
        for x in chart.get(k, []):
            prov = x.get("provenance") or {}
            if prov.get("source") not in ("fhir_import", "curated") or prov.get("followup"):
                return True
    return queue_dir.is_dir() and any(not q.name.endswith(".raw.json") for q in queue_dir.glob("*.json"))


def _build() -> Path:
    base = Path(tempfile.mkdtemp(prefix="ehr-golden-"))
    (base / "patients").mkdir()
    for f in sorted((LIVE / "patients").glob("pt_*.json")):
        text = f.read_text()
        if not f.name.endswith(".import-report.json"):
            pid = f.stem
            try:
                dirty = _demo_state(json.loads(text), LIVE / "proposed" / pid)
            except (ValueError, KeyError):
                dirty = True
            if dirty:
                head = subprocess.run(["git", "show", f"HEAD:data/patients/{f.name}"], cwd=ROOT, capture_output=True, text=True)
                if head.returncode == 0:
                    text = head.stdout
        (base / "patients" / f.name).write_text(text)
    for d in (LIVE / "proposed").glob("*"):
        if d.is_dir():
            (base / "proposed" / d.name).mkdir(parents=True)
            for raw in d.glob("*.raw.json"):
                shutil.copy(raw, base / "proposed" / d.name / raw.name)
    return base


GOLDEN = _build()
os.environ["EHR_DATA_DIR"] = str(GOLDEN / "patients")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(GOLDEN, ignore_errors=True)
