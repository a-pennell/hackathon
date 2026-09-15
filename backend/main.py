"""FastAPI backend: serves the per-patient JSON, problem-scoped timelines, trends,
the review queue, and the extraction / reasoning actions. Serves frontend/dist when built.

    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.extract import PROPOSED_DIR, load_note_file, run_extraction  # noqa: E402
from ehr.reason import monitored_codes, run_reasoning  # noqa: E402
from ehr.billing import code_visit  # noqa: E402
from ehr.brief import deterministic_brief, run_live_brief  # noqa: E402
from ehr.card import problem_card  # noqa: E402
from ehr.overview import patient_overview  # noqa: E402
from ehr.orders import run_orders  # noqa: E402
from ehr.compose import run_compose  # noqa: E402
from ehr.review import REASON_CODES, apply_review, ledger_for_problem, list_queues, undo_review  # noqa: E402
from ehr.trend import DATA_DIR, load_patient, trend_from_patient  # noqa: E402

NOTES_DIR = ROOT / "data" / "notes"
app = FastAPI(title="Problem-Oriented EHR", version="0.1")

SPANS = {"3m": 91, "6m": 182, "1y": 365, "2y": 730, "5y": 1826}


def _patient(pid: str) -> dict:
    try:
        return load_patient(pid, DATA_DIR)
    except FileNotFoundError:
        raise HTTPException(404, f"no patient {pid}")


def _window(patient: dict, span: str) -> dict:
    end = date.today()
    if span == "all":
        firsts = [e["time"][:10] for e in patient["encounters"]] + [o["effective_time"][:10] for o in patient["observations"]]
        start = min(firsts) if firsts else end.isoformat()
    else:
        start = (end - timedelta(days=SPANS.get(span, 365))).isoformat()
    return {"start": start, "end": end.isoformat()}


def _accepted(items):
    return [x for x in items if x.get("status") in ("accepted", "active", "resolved")]


@app.get("/api/patients")
def patients():
    out = []
    for p in sorted(DATA_DIR.glob("pt_*.json")):
        d = json.loads(p.read_text())
        out.append({**d["patient"], "problems_active": sum(1 for x in d["problems"] if x["status"] == "active")})
    return out


@app.get("/api/patients/{pid}")
def patient_summary(pid: str):
    d = _patient(pid)
    monitored = {p["id"]: monitored_codes(d, p["id"]) for p in d["problems"]}
    nlp_links = {}
    for l in d["links"]:
        if l["provenance"].get("source") == "nlp_extraction":
            nlp_links[l["to"]] = nlp_links.get(l["to"], 0) + 1
    return {
        "patient": d["patient"],
        "problems": [{**p, "monitored_codes": monitored[p["id"]], "note_links": nlp_links.get(p["id"], 0)} for p in d["problems"]],
        "counts": {k: len(d[k]) for k in ("problems", "observations", "medications", "encounters", "notes", "links", "insights")},
        "insights": d["insights"],
        "documents": d.get("documents", []),
        "orders": d.get("orders", []),
    }


@app.get("/api/patients/{pid}/overview")
def overview(pid: str, since: str | None = None):
    """Orientation: what changed, ranked; active concerns by what they need; open loops. Computed, never stored."""
    d = _patient(pid)
    o = patient_overview(d, since=since, proposed_dir=PROPOSED_DIR)
    # The note that arrived with the newest visit, if a demo note file carries it, and whether it has been read.
    enc = (o["here_for"] or {}).get("encounter")
    note = None
    if enc:
        for p in sorted(NOTES_DIR.glob("*.json")):
            n, e = load_note_file(p)
            if e and e.get("id") == enc["id"]:
                note = {"id": n["id"], "file": str(p.relative_to(ROOT)), "author": n["author"], "time": n["time"],
                        "has_queue": (PROPOSED_DIR / pid / f"{n['id']}.json").exists(),
                        "has_replay": (PROPOSED_DIR / pid / f"{n['id']}.raw.json").exists()}
    o["here_for"]["note"] = note
    return o


@app.get("/api/patients/{pid}/problems/{prob}/timeline")
def timeline(pid: str, prob: str, window: str = "1y", all_meds: bool = True):
    d = _patient(pid)
    problem = next((p for p in d["problems"] if p["id"] == prob), None)
    if not problem:
        raise HTTPException(404, f"no problem {prob}")
    win = _window(d, window)
    start, end = win["start"], win["end"]
    codes = monitored_codes(d, prob)

    series = []
    for code in codes:
        pts = [o for o in _accepted(d["observations"]) if o["code"]["value"] == code and start <= o["effective_time"][:10] <= end]
        pts.sort(key=lambda o: o["effective_time"])
        if not pts:
            continue
        series.append({
            "code": code, "name": pts[-1]["name"], "unit": pts[-1]["unit"], "reference_range": pts[-1]["reference_range"],
            "points": [{"id": o["id"], "time": o["effective_time"], "value": o["value"], "source": o["provenance"]["source"]} for o in pts],
            "trend": trend_from_patient(d, code, win),
        })
    # The series that moved the most leads the sheet: that's the one the clinician is here for.
    series.sort(key=lambda s: -abs(s["trend"]["delta_pct"] or 0))
    series_targets = {f"LOINC:{s['code']}" for s in series}

    links = [l for l in _accepted(d["links"])
             if l["to"] == prob or l["from"] == prob or l["to"] in series_targets or l["from"] in series_targets]
    treats = {l["from"] for l in links if l["type"] == "treats" and l["to"] == prob}
    causes = {l["from"] for l in links if l["type"] == "suspected_cause"}

    meds = []
    for m in _accepted(d["medications"]):
        segs = m["segments"]
        in_window = any((s["end"] is None or s["end"] >= start) and (s["start"] or "") <= end for s in segs)
        relation = ("treats" if m["id"] in treats else "suspected_cause" if m["id"] in causes
                    else "on_board" if in_window else None)
        if relation is None or (relation == "on_board" and not all_meds):
            continue
        meds.append({**m, "relation": relation})
    order = {"suspected_cause": 0, "treats": 1, "on_board": 2}
    meds.sort(key=lambda m: (order[m["relation"]], m["segments"][0]["start"] or ""))

    note_by_enc = {n["encounter_id"]: n for n in d["notes"] if n.get("encounter_id")}
    finding_notes = {l["from"] for l in links if l["from"].startswith("note_")}
    encounters = []
    for e in d["encounters"]:
        if not (start <= e["time"][:10] <= end):
            continue
        n = note_by_enc.get(e["id"])
        encounters.append({**e, "note_id": n["id"] if n else None, "author": n["author"] if n else None,
                           "has_findings": bool(n and n["id"] in finding_notes),
                           "excerpt": (n["text"].strip()[:160] if n else None)})

    proposed = {"observations": [], "medications": [], "links": [], "insights": [], "problems": []}
    for b in list_queues(pid, PROPOSED_DIR):
        p = b["proposed"]
        plinks = [l for l in p.get("links", []) if l["status"] == "proposed"
                  and (l["to"] == prob or l["to"] in series_targets or l["from"] == prob)]
        ref_ids = {l["from"] for l in plinks} | {l["to"] for l in plinks}
        proposed["links"] += [{**l, "queue": b["stem"]} for l in plinks]
        proposed["observations"] += [{**o, "queue": b["stem"]} for o in p.get("observations", []) if o["status"] == "proposed" and o["id"] in ref_ids]
        proposed["medications"] += [{**m, "queue": b["stem"]} for m in p.get("medications", []) if m["status"] == "proposed" and m["id"] in ref_ids]
        proposed["problems"] += [{**x, "queue": b["stem"]} for x in p.get("problems", []) if x["status"] == "proposed" and x["id"] in ref_ids]
        proposed["insights"] += [{**i, "queue": b["stem"]} for i in p.get("insights", []) if i["status"] == "proposed" and i["problem_id"] == prob]

    return {"patient": d["patient"], "problem": problem, "window": win, "series": series, "medications": meds,
            "encounters": encounters, "links": links,
            "insights": [i for i in d["insights"] if i["problem_id"] == prob],
            "orders": [o for o in d.get("orders", []) if o["problem_id"] == prob and start <= (o.get("ordered_at") or o["created_at"])[:10] <= end],
            "proposed": proposed}


@app.get("/api/patients/{pid}/problems/{prob}/brief")
def brief(pid: str, prob: str, window: str = "90d"):
    d = _patient(pid)
    if not any(p["id"] == prob for p in d["problems"]):
        raise HTTPException(404, f"no problem {prob}")
    return deterministic_brief(d, prob, window, proposed_dir=PROPOSED_DIR)


class BriefBody(BaseModel):
    mode: str = "live"  # live | replay
    window: str = "90d"


@app.post("/api/patients/{pid}/problems/{prob}/brief")
def brief_live(pid: str, prob: str, body: BriefBody):
    replay = None
    if body.mode == "replay":
        replay = PROPOSED_DIR / pid / f"brief_{prob}.raw.json"
        if not replay.exists():
            raise HTTPException(400, "no saved model response to replay for this brief; run live once")
    try:
        return run_live_brief(pid, prob, body.window, replay=replay, data_dir=DATA_DIR)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"brief failed: {type(e).__name__}: {e}")


@app.get("/api/patients/{pid}/problems/{prob}/card")
def card(pid: str, prob: str, window: str = "1y"):
    """The problem card: the clinician's model of one concern, computed from the chart. Never stored."""
    d = _patient(pid)
    try:
        return problem_card(d, prob, window, proposed_dir=PROPOSED_DIR)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/patients/{pid}/problems/{prob}/trail")
def trail(pid: str, prob: str, pending: bool = True):
    d = _patient(pid)
    if not any(p["id"] == prob for p in d["problems"]):
        raise HTTPException(404, f"no problem {prob}")
    entries = ledger_for_problem(d, prob, PROPOSED_DIR, include_pending=pending)
    # Resolve ids inside link / med-change summaries to names the clinician recognises.
    names = {p["id"]: p["name"] for p in d["problems"]}
    names.update({m["id"]: m["name"] for m in d["medications"]})
    names.update({o["id"]: f"{o['name']} {o['value']} {o['unit'] or ''} · {o['effective_time'][:10]}" for o in d["observations"]})
    names.update({n["id"]: f"note {n['id'].replace('note_', '')} · {n['time'][:10]}" for n in d["notes"]})
    for b in list_queues(pid, PROPOSED_DIR):
        for k in ("problems", "medications", "observations"):
            for it in b["proposed"].get(k, []):
                names.setdefault(it["id"], it.get("name") or it["id"])
    for e in entries:
        if e["kind"] in ("link", "medication_change"):
            e["what"] = " ".join(names.get(w, w) for w in e["what"].split(" "))
    signed_docs = [{"id": x["id"], "kind": "document", "what": f"{x['kind']} to {x['audience']}: {x['title']}", "queue": None,
                    "source": x["provenance"]["source"], "confidence": x["provenance"].get("confidence"), "quote": None,
                    "decision": "accepted", "reason_code": (x.get("review") or {}).get("reason_code"), "reason": (x.get("review") or {}).get("reason"),
                    "by": (x.get("review") or {}).get("by"), "at": (x.get("review") or {}).get("at") or x["created_at"]}
                   for x in d.get("documents", []) if x["problem_id"] == prob and not any(e["id"] == x["id"] for e in entries)]
    return sorted(entries + signed_docs, key=lambda e: e["at"] or "")


@app.get("/api/patients/{pid}/trend/{code}")
def trend_api(pid: str, code: str, window: str = "1y"):
    d = _patient(pid)
    return trend_from_patient(d, code, _window(d, window))


@app.get("/api/patients/{pid}/queue")
def queue(pid: str):
    """Queue batches plus a `labels` map so the UI can name every id a link touches."""
    d = _patient(pid)
    batches = list_queues(pid, PROPOSED_DIR)
    wanted = set()
    for b in batches:
        for l in b["proposed"].get("links", []):
            wanted.update((l["from"], l["to"]))
        for i in b["proposed"].get("insights", []):
            wanted.update(i.get("evidence", []))
        for x in b["proposed"].get("documents", []) + b["proposed"].get("orders", []):
            wanted.update(x["provenance"].get("evidence", []))
    labels = {}
    for p in d["problems"]:
        if p["id"] in wanted: labels[p["id"]] = p["name"]
    for m in d["medications"]:
        if m["id"] in wanted: labels[m["id"]] = m["name"]
    for o in d["observations"]:
        if o["id"] in wanted: labels[o["id"]] = f"{o['name']} {o['value']} {o['unit'] or ''} · {o['effective_time'][:10]}"
    for n in d["notes"]:
        if n["id"] in wanted: labels[n["id"]] = f"note {n['id'].replace('note_', '')} · {n['time'][:10]}"
    for e in d["encounters"]:
        if e["id"] in wanted: labels[e["id"]] = f"visit {e['time'][:10]} · {e['type']}"
    for i in d.get("insights", []):
        if i["id"] in wanted: labels[i["id"]] = f"insight: {i['statement'][:60]}"
    return {"batches": batches, "labels": labels}


class ReviewBody(BaseModel):
    accept: list[str] = []
    reject: list[str] = []
    accept_all: bool = False
    accept_changes: bool = False
    reason: str | None = None
    reason_code: str | None = None
    by: str = "Dr. Chen"


@app.post("/api/patients/{pid}/queue/{stem}/review")
def review(pid: str, stem: str, body: ReviewBody):
    try:
        if body.reason_code is not None and body.reason_code not in REASON_CODES:
            raise HTTPException(400, f"reason_code must be one of {REASON_CODES}")
        done = apply_review(pid, stem, accept=body.accept, reject=body.reject,
                            accept_all=body.accept_all, accept_changes=body.accept_changes,
                            reason=body.reason, reason_code=body.reason_code, by=body.by, data_dir=DATA_DIR)
    except FileNotFoundError:
        raise HTTPException(404, f"no queue {stem}")
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    decided = [d.split(" ")[1] for d in done if d.split(" ")[0] in ("problem", "observation", "medication", "link", "insight", "document", "order")]
    return {"done": done, "decided": decided}


class UndoBody(BaseModel):
    ids: list[str]


@app.post("/api/patients/{pid}/queue/{stem}/undo")
def undo(pid: str, stem: str, body: UndoBody):
    try:
        return {"done": undo_review(pid, stem, body.ids, data_dir=DATA_DIR)}
    except FileNotFoundError:
        raise HTTPException(404, f"no queue {stem}")


@app.get("/api/patients/{pid}/notes/{note_id}")
def chart_note(pid: str, note_id: str):
    d = _patient(pid)
    n = next((x for x in d["notes"] if x["id"] == note_id), None)
    if not n:
        raise HTTPException(404, f"no note {note_id}")
    demo = next((p for p in NOTES_DIR.glob("*.json") if load_note_file(p)[0]["id"] == note_id), None)
    raw = PROPOSED_DIR / pid / f"{note_id}.raw.json"
    return {**n, "file": str(demo.relative_to(ROOT)) if demo else None,
            "excerpt": n["text"].strip()[:200], "has_replay": raw.exists(),
            "has_queue": (PROPOSED_DIR / pid / f"{note_id}.json").exists()}


@app.get("/api/notes")
def notes():
    out = []
    for p in sorted(NOTES_DIR.glob("*.json")):
        note, enc = load_note_file(p)
        raw = PROPOSED_DIR / note["patient_id"] / f"{note['id']}.raw.json"
        queued = PROPOSED_DIR / note["patient_id"] / f"{note['id']}.json"
        out.append({"file": str(p.relative_to(ROOT)), "id": note["id"], "patient_id": note["patient_id"],
                    "time": note["time"], "author": note["author"], "encounter": enc,
                    "excerpt": note["text"].strip()[:200], "text": note["text"],
                    "has_replay": raw.exists(), "has_queue": queued.exists()})
    return out


class ExtractBody(BaseModel):
    note_file: str
    mode: str = "live"  # live | replay


@app.post("/api/patients/{pid}/extract")
def extract(pid: str, body: ExtractBody):
    note_path = ROOT / body.note_file
    if not note_path.exists():
        raise HTTPException(404, f"no note file {body.note_file}")
    note, _ = load_note_file(note_path)
    replay = None
    if body.mode == "replay":
        replay = PROPOSED_DIR / pid / f"{note['id']}.raw.json"
        if not replay.exists():
            raise HTTPException(400, "no saved model response to replay for this note; run live once")
    try:
        batch = run_extraction(pid, note_path, replay=replay, data_dir=DATA_DIR)
    except Exception as e:  # surface API/auth problems to the UI instead of a 500
        raise HTTPException(502, f"extraction failed: {type(e).__name__}: {e}")
    return batch


class ReasonBody(BaseModel):
    problem_id: str
    mode: str = "live"  # live | rules | replay
    window: str = "1y"


@app.post("/api/patients/{pid}/reason")
def reason(pid: str, body: ReasonBody):
    replay = None
    if body.mode == "replay":
        replay = PROPOSED_DIR / pid / f"reason_{body.problem_id}.raw.json"
        if not replay.exists():
            raise HTTPException(400, "no saved model response to replay for this problem; run live once")
    try:
        batch = run_reasoning(pid, body.problem_id, window=body.window, rules_only=(body.mode == "rules"),
                              replay=replay, data_dir=DATA_DIR)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"reasoning failed: {type(e).__name__}: {e}")
    return batch


class ComposeBody(BaseModel):
    problem_id: str
    kind: str = "referral"
    audience: str = "nephrology"
    mode: str = "live"  # live | replay
    window: str = "1y"


@app.post("/api/patients/{pid}/compose")
def compose_doc(pid: str, body: ComposeBody):
    replay = None
    if body.mode == "replay":
        replay = PROPOSED_DIR / pid / f"{body.kind}_{body.problem_id}.raw.json"
        if not replay.exists():
            raise HTTPException(400, "no saved model response to replay for this document; run live once")
    try:
        return run_compose(pid, body.problem_id, kind=body.kind, audience=body.audience, window=body.window,
                           replay=replay, data_dir=DATA_DIR)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"composition failed: {type(e).__name__}: {e}")


class OrdersBody(BaseModel):
    problem_id: str
    mode: str = "live"  # live | replay
    window: str = "1y"


@app.post("/api/patients/{pid}/orders")
def orders(pid: str, body: OrdersBody):
    replay = None
    if body.mode == "replay":
        replay = PROPOSED_DIR / pid / f"orders_{body.problem_id}.raw.json"
        if not replay.exists():
            raise HTTPException(400, "no saved model response to replay for these orders; run live once")
    try:
        return run_orders(pid, body.problem_id, window=body.window, replay=replay, data_dir=DATA_DIR)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"ordering failed: {type(e).__name__}: {e}")


@app.get("/api/patients/{pid}/coding")
def coding(pid: str, encounter: str | None = None, on: str | None = None):
    """Diagnosis codes and E/M level derived from what was signed on the visit day. Computed, never stored."""
    d = _patient(pid)
    return code_visit(d, encounter, on=on or date.today().isoformat(), proposed_dir=PROPOSED_DIR)


PRISTINE = DATA_DIR / ".pristine"   # snapshot of every chart at server start; gitignored


def _is_clean(chart: dict) -> bool:
    """A chart with nothing AI-signed on it: the state the demo starts from."""
    return not chart.get("documents") and not chart.get("orders") and all(
        x["provenance"]["source"] == "fhir_import"
        for k in ("problems", "observations", "medications", "links", "insights") for x in chart.get(k, []))


def _snapshot_charts():
    """Snapshot each chart for 'Reset demo'. Only a clean chart is ever snapshotted: uvicorn's
    reloader restarts this process on every code edit, and mid-demo state must not become the
    thing reset returns to. If the chart is dirty at start, the previous snapshot is kept."""
    PRISTINE.mkdir(exist_ok=True)
    for p in DATA_DIR.glob("pt_*.json"):
        if p.name.endswith(".import-report.json"):
            continue
        chart = json.loads(p.read_text())
        if _is_clean(chart):
            (PRISTINE / p.name).write_bytes(p.read_bytes())
        elif not (PRISTINE / p.name).exists():
            print(f"warning: {p.name} has AI-signed items and no clean snapshot exists; 'Reset demo' unavailable until you start from a clean chart")


_snapshot_charts()


@app.post("/api/patients/{pid}/reset")
def reset(pid: str):
    """Demo reset: restore the chart to its state at server start and clear validated queues.
    Saved model responses (*.raw.json) are kept so replay still works."""
    src = PRISTINE / f"{pid}.json"
    if not src.exists():
        raise HTTPException(404, f"no pristine snapshot for {pid}")
    (DATA_DIR / f"{pid}.json").write_bytes(src.read_bytes())
    removed = []
    for q in (PROPOSED_DIR / pid).glob("*.json"):
        if not q.name.endswith(".raw.json"):
            q.unlink()
            removed.append(q.name)
    return {"restored": pid, "queues_cleared": removed}


DIST = ROOT / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = DIST / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
