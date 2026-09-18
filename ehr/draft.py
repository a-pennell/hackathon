"""The visit note, compiled from what the clinician did: the chart writes the note.

    python3 -m ehr.draft pt_002 --encounter enc_c002

The demo runs one way today: a note arrives, it is read, proposals reach the chart once signed. This is the
same machinery the other way. Every action taken at a visit is already a dated, signed event with the visit
stamped on it (review.encounter_id): a problem raised, a cause asserted, a course stopped, a plan item set,
an insight signed, a proposal rejected with its reason. The draft selects the events of one encounter and
renders them into sections, each carrying the ids it came from. The transcript's own narrative, if the
visit had one, is the first section, verbatim. The clinician edits the prose and signs; nothing here is
authored by the system beyond the sentences that restate the record, and nothing reaches the chart until
the signature (queue `visitnote_<encounter_id>`, kind `encounter_note`, the Document shape of ehr/compose.py).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from ehr.card import problem_card
from ehr.expect import expectations
from ehr.extract import PROPOSED_DIR, save_patient
from ehr.reason import _accepted
from ehr.review import DEFAULT_REVIEWER, accept_item, list_queues, load_queue, review_record
from ehr.trend import DATA_DIR, load_patient

DRAFTER = "drafter-v1/rules"
KIND = "encounter_note"


def _dmy(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _nice(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{f:.0f}" if abs(f) >= 100 else f"{f:.1f}" if abs(f) >= 10 else f"{f:.2f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _first_sentence(text: str) -> str:
    """An insight's first sentence is its observation; the rest is its reasoning, kept behind the citation. Splits on a
    period followed by a space and a capital, so decimals, dates and units survive."""
    parts = re.split(r"(?<=[a-z0-9%)\]])\.\s+(?=[A-Z])", text.strip(), maxsplit=1)
    head = parts[0].rstrip(".")
    return head + "."


SHORT = {"Systolic blood pressure": "SBP", "Diastolic blood pressure": "DBP", "Hemoglobin A1c": "A1c", "Urine albumin/creatinine ratio": "urine ACR",
         "Body weight": "weight", "Heart rate": "HR", "Glucose": "glucose", "Potassium": "potassium", "Creatinine (whole blood)": "creatinine", "Creatinine": "creatinine"}


def _measure_phrases(obs: list[dict], dated: bool = False) -> list[str]:
    """Results as a clinician writes them: blood pressures paired ('BP 154/94'), names shortened, units kept."""
    out, used = [], set()
    sbp = [o for o in obs if o["code"]["value"] == "8480-6"]
    dbp = [o for o in obs if o["code"]["value"] == "8462-4"]
    for s_, d_ in zip(sbp, dbp):
        out.append(f"BP {_nice(s_['value'])}/{_nice(d_['value'])}"); used |= {s_["id"], d_["id"]}
    for o in obs:
        if o["id"] in used:
            continue
        name = SHORT.get(o["name"], o["name"])
        unit = f" {o['unit']}" if o.get("unit") and o["unit"] not in ("mm[Hg]",) else ""
        out.append(f"{name} {_nice(o['value'])}{unit}")
    return out


def _in_encounter(x: dict, enc_id: str, enc_day: str, note_id: str | None) -> bool:
    """An item belongs to the visit if its signature says so, or (older stamps) if it came from the visit's note."""
    r = x.get("review") or {}
    if r.get("encounter_id"):
        return r["encounter_id"] == enc_id
    prov = x.get("provenance") or {}
    return bool(note_id) and prov.get("note_id") == note_id


def _course_events(name: str, segs: list[dict], day: str) -> list[str]:
    events = []
    for i, seg in enumerate(segs):
        prev = segs[i - 1] if i else None
        if seg.get("start") == day:
            events.append(f"{name} {prev.get('dose') or '?'} → {seg.get('dose') or '?'}" if prev and prev.get("end") == day else f"{name} {seg.get('dose') or ''} started".replace("  ", " "))
        if seg.get("end") == day and not (i + 1 < len(segs) and segs[i + 1].get("start") == day):
            events.append(f"{name} {seg.get('dose') or ''} stopped".replace("  ", " "))
    return events


def draft_note(patient: dict, encounter_id: str, *, proposed_dir: Path = PROPOSED_DIR, today: date | None = None,
               transcript_upto: int | None = None) -> dict:
    """Compile the visit note for one encounter as a proposed Document. Deterministic; no model call.
    `transcript_upto` compiles the note as it stands part-way through the dictation: the transcript to that character,
    and the closing list read as what is not yet addressed rather than what the visit left."""
    today = today or date.today()
    enc = next((e for e in patient.get("encounters", []) if e["id"] == encounter_id), None)
    if enc is None:
        raise KeyError(f"{encounter_id} is not on this chart")
    enc_day = enc["time"][:10]
    note = next((n for n in patient.get("notes", []) if n.get("encounter_id") == encounter_id), None)
    note_id = note["id"] if note else None
    names = {p["id"]: p["name"] for p in patient["problems"]}
    names.update({m["id"]: m["name"] for m in patient["medications"]})
    queues = list_queues(patient["patient"]["id"], proposed_dir)
    mine = lambda x: _in_encounter(x, encounter_id, enc_day, note_id)  # noqa: E731

    sections: list[dict] = []

    def add(heading, text, cites, source, problem_id=None, key=None):
        # `key` identifies a section across recompiles, so a clinician's edit lands on the section they edited even
        # when two problems share a name. Headings do not: "Plan · Hypertension" is not unique in that chart.
        text = text.strip()
        if text:
            sections.append({"key": key or heading.lower().replace(" ", "_"), "heading": heading, "text": text,
                             "cites": list(dict.fromkeys(c for c in cites if c)), "source": source,
                             **({"problem_id": problem_id} if problem_id else {})})

    # 1. The transcript, verbatim: history and exam as the first section; the dictated assessment and plan folded,
    # since the sections compiled from the record restate them and a provider should not read their A/P twice.
    if note:
        text = note["text"] if transcript_upto is None else note["text"][:transcript_upto]
        m = re.search(r"^\s*(A/P|A&P|Assessment(?: and Plan| & Plan)?|A)\s*:", text, re.M | re.I)
        if m:
            add("Subjective", text[: m.start()], [note["id"]], "transcript")
            sections[-1]["heading"] = "History and exam, as dictated"
            add("Assessment and plan, as dictated", text[m.start():], [note["id"]], "transcript")
            sections[-1]["collapsed"] = True
        else:
            add("As dictated", text, [note["id"]], "transcript")

    # 2. Objective: results recorded at the visit, and results reviewed at it.
    recorded = [o for o in _accepted(patient["observations"]) if o["effective_time"][:10] == enc_day]
    reviewed_ids = {l["from"] for l in _accepted(patient["links"]) if mine(l) and l["from"].startswith("obs_")}
    reviewed = [o for o in _accepted(patient["observations"]) if o["id"] in reviewed_ids and o["effective_time"][:10] != enc_day]
    parts = []
    if recorded:
        parts.append("At this visit: " + ", ".join(_measure_phrases(recorded)) + ".")
    if reviewed:
        parts.append("Reviewed: " + ", ".join(f"{p} ({_dmy(o['effective_time'])})" for p, o in zip(_measure_phrases(reviewed, dated=True), reviewed)) + ".")
    add("Objective", " ".join(parts), [o["id"] for o in recorded + reviewed], "compiled")

    # 3. Problems addressed: anything the visit's signatures touched.
    touched: dict[str, dict] = {}
    def touch(pid):
        if pid in names and pid.startswith("prob_"):
            touched.setdefault(pid, {"raised": False, "causes": [], "rejected": [], "insights": [], "plans": [], "orders": [], "courses": [], "evidence": []})
    for p in patient["problems"]:
        if p["status"] == "active" and mine(p):
            touch(p["id"]); touched[p["id"]]["raised"] = True
    for l in _accepted(patient["links"]):
        if not mine(l):
            continue
        for end in (l["from"], l["to"]):
            touch(end)
        if l["type"] == "suspected_cause" and l["to"] in touched:
            touched[l["to"]]["causes"].append(l)
        elif l["type"] == "evidence_for" and l["to"] in touched:
            touched[l["to"]]["evidence"].append(l)
    for b in queues:
        for l in b["proposed"].get("links", []):
            # A cause the clinician rejected, with their reason, is reasoning and belongs in the assessment. One they never
            # answered is not: it was set aside as unconfirmed (undoable, and listed as such in the manifest), and the
            # screen promises it is left out of the note. Writing it up as "rejected" recorded a decision nobody made.
            if (l.get("review") or {}).get("reason_code") == "needs_confirmation":
                continue
            if l.get("status") == "rejected" and mine(l) and l["type"] == "suspected_cause":
                touch(l["to"])
                if l["to"] in touched:
                    touched[l["to"]]["rejected"].append(l)
    for i in patient.get("insights", []):
        if i.get("status") == "accepted" and mine(i):
            touch(i["problem_id"]); touched.get(i["problem_id"], {}).setdefault("insights", []).append(i)
    for pl in patient.get("plans", []):
        if mine(pl) and pl.get("destination") != "treatment_plan":
            touch(pl["problem_id"]); touched.get(pl["problem_id"], {}).setdefault("plans", []).append(pl)
    for item in patient.get("note_plan_items", []):
        if item.get("encounter_id") == encounter_id:
            touch(item["problem_id"]); touched.get(item["problem_id"], {}).setdefault("plans", []).append(item)
    treatment_only = [pl for pl in patient.get("plans", []) if pl.get("destination") == "treatment_plan"]
    treatment_only_ids = {pl["id"] for pl in treatment_only}
    for o in patient.get("orders", []):
        if mine(o) and o.get("destination") != "treatment_plan" and (o.get("provenance") or {}).get("from_plan") not in treatment_only_ids:
            touch(o["problem_id"]); touched.get(o["problem_id"], {}).setdefault("orders", []).append(o)
    # courses changed on the visit day, attached to the problems they are linked to
    for m in _accepted(patient["medications"]):
        events = _course_events(m["name"], m.get("segments") or [], enc_day)
        # Exclude treatment-only effects without hiding unrelated changes to the same course.
        excluded = set()
        for pl in treatment_only:
            effect = pl.get("medication_effect") or {}
            if effect.get("med_id") == m["id"] and mine(pl):
                excluded.update(set(_course_events(m["name"], effect["after"], enc_day))
                                - set(_course_events(m["name"], effect["before"], enc_day)))
        events = [event for event in events if event not in excluded]
        if not events:
            continue
        linked = {l["to"] for l in _accepted(patient["links"]) if l["from"] == m["id"] and l["type"] in ("treats", "suspected_cause")}
        for pid in linked:
            touch(pid)
            if pid in touched:
                touched[pid]["courses"] += [(e, m["id"]) for e in events]

    order = [p["id"] for p in patient["problems"] if p["id"] in touched]
    win = {"start": (date.fromisoformat(enc_day).replace(year=date.fromisoformat(enc_day).year - 1)).isoformat(), "end": enc_day}
    expected_said: set[str] = set()  # courses whose expectations are already written, under an earlier problem
    for pid in order:
        t = touched[pid]
        pname = names[pid]
        lines, cites = [], [pid]
        if t["raised"]:
            lines.append(f"{pname}, raised at this visit.")
            if note_id:
                cites.append(note_id)
        try:
            card = problem_card(patient, pid, win, proposed_dir=proposed_dir, today=today)
            rep = (card.get("representation") or {}).get("text")
            if rep:
                lines.append(rep)
                cites += (card.get("representation") or {}).get("cites") or []
        except Exception:
            pass
        rep_text = " ".join(lines).lower()
        for l in t["causes"]:
            cause = names.get(l["from"], l["from"])
            if cause.lower() not in rep_text:  # the representation already says it when the course is linked
                lines.append(f"{cause} is recorded as a suspected cause of {pname}.")
            cites += [l["id"], l["from"]]
        for l in t["rejected"]:
            r = l.get("review") or {}
            why = f" {r['reason']}" if r.get("reason") else ""
            lines.append(f"{names.get(l['from'], l['from'])} was proposed as a cause and rejected:{why}".rstrip(":") + ("" if why else "."))
            cites.append(l["id"])
        for i in t["insights"]:
            if i.get("kind") in ("assessment", "representation"):
                continue
            lines.append(_first_sentence(i["statement"]))
            cites += [i["id"]] + list(i.get("evidence") or [])
        authored = [i for i in t["insights"] if i.get("kind") in ("assessment", "representation")]
        if authored:
            # Explicit clinician assessment takes precedence over a generated representation.
            assessment = max(enumerate(authored), key=lambda pair: (pair[1].get("kind") == "assessment", pair[1].get("review", {}).get("at", ""), pair[0]))[1]
            lines = [assessment["statement"]]
            cites = [pid, assessment["id"], *assessment.get("evidence", [])]
        if lines:
            add(f"Assessment · {pname}", " ".join(lines), cites, "compiled", pid, key=f"assessment:{pid}")
        plan_lines, pcites = [], [pid]
        plan_text = " ".join(pl["text"] for pl in t["plans"]).lower()
        for e, mid in t["courses"]:
            if names.get(mid, "").split(" ")[0].lower() in plan_text:  # the plan item already says it
                pcites.append(mid); continue
            plan_lines.append(e + "."); pcites.append(mid)
        for pl in t["plans"]:
            line = pl["text"].strip().rstrip(".")
            plan_lines.append(line[:1].upper() + line[1:] + "."); pcites.append(pl["id"])
        ordered = []
        for o in t["orders"]:
            pcites.append(o["id"])
            if (o.get("provenance") or {}).get("from_plan"):
                continue  # the plan item already says it
            ordered.append(o["name"] + (f" ({o['detail'].rstrip('.')})" if o.get("detail") else ""))
        if ordered:
            plan_lines.append("Ordered: " + "; ".join(ordered) + ".")
        executed = {(o.get("provenance") or {}).get("from_insight") for o in t["orders"]}
        for i in t["insights"]:
            if i["id"] in executed:
                continue  # the order drafted from this insight already says it
            if i.get("suggested_action"):
                a = i["suggested_action"].removeprefix("Consider ").rstrip(".")
                plan_lines.append(a[:1].upper() + a[1:] + " (signed insight)."); pcites.append(i["id"])
        # What the plan is expected to do that looks like harm, and how far is too far. It is reasoning the next reader
        # needs — a creatinine of 1.0 after lisinopril reads as a problem to anyone who does not know it was expected —
        # so the note records it rather than leaving it on a screen. It belongs to the drug, not the problem: a course
        # that treats two problems is written up once, under the first. Only for courses started at this visit.
        started_here = {c["id"] for c in patient["medications"] if (c["segments"][-1].get("start") or "") == enc_day}
        by_drug: dict[str, list[dict]] = {}
        for m in expectations(patient, pid, today=max(today, date.fromisoformat(enc_day))):
            mid = next((i for i in m["trigger"]["ids"] if i in started_here), None)
            if mid and mid not in expected_said:
                by_drug.setdefault(mid, []).append(m)
        for mid, ms in by_drug.items():
            expected_said.add(mid)
            drug = names.get(mid, mid).lower()
            what = " and ".join(
                (f"{x['value']['name'].split(' (')[0].lower()} up to {_num(x['limit'])} {x['value']['unit']} (from {_num(x['baseline']['value'])})"
                 if x["limit_kind"] == "rise" else f"{x['value']['name'].split(' (')[0].lower()} under {_num(x['limit'])} {x['value']['unit']}")
                for x in ms)
            tests = list(dict.fromkeys(x["tested_by"]["text"] for x in ms if x.get("tested_by")))
            tested = (f"; the {_lead_lower(tests[0])} tests {'both' if len(ms) == 2 else 'it'}" if len(tests) == 1 and len(ms) <= 2
                      else f"; tested by {', '.join(tests)}" if tests else "; nothing on the plan tests it yet")
            plan_lines.append(f"Expected on {drug}: {what}{tested}.")
            for x in ms:
                name = x["value"]["name"].split(" (")[0].lower()
                plan_lines.append(f"If {name} is {x['not_expected']}: {_lead_lower(x['then'])}")
            pcites += [i for x in ms for i in x["ids"] if i not in pcites]
        if plan_lines:
            add(f"Plan · {pname}", " ".join(plan_lines), pcites, "compiled", pid, key=f"plan:{pid}")

    # Closing the loop: what is on the problem list and was not touched at this visit. Stated as a fact, not a judgement
    # — a problem can be left for a good reason — but a note that is silent about it reads as if it was forgotten.
    untouched = [p for p in patient["problems"] if p["status"] == "active" and p["id"] not in touched]
    if untouched:
        add("Not yet addressed" if transcript_upto is not None else "Not addressed at this visit",
            "; ".join(p["name"] for p in untouched) + ".", [p["id"] for p in untouched], "compiled", key="not_addressed")

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    author = (note or {}).get("author") or DEFAULT_REVIEWER
    doc = {
        "id": f"doc_{encounter_id}_note", "patient_id": patient["patient"]["id"], "problem_id": None, "encounter_id": encounter_id,
        "kind": KIND, "audience": "chart", "title": f"Visit note · {_dmy(enc['time'])} · {author}",
        "sections": sections, "questions": [], "problems_addressed": order, "status": "proposed",
        "provenance": {"source": "composition", "model": DRAFTER, "evidence": list(dict.fromkeys(c for s in sections for c in s["cites"])),
                       "confidence": 1.0, **({"note_id": note_id} if note_id else {})},
        "created_at": now,
    }
    return {"patient_id": patient["patient"]["id"], "encounter_id": encounter_id, "kind": KIND, "model": DRAFTER, "composed_at": now,
            "proposed": {"documents": [doc]}, "review_hints": {}, "rejected": []}


def _lead_lower(t: str) -> str:
    """Lower the first letter to run a phrase on inside a sentence — unless it opens an acronym (BMP, ACR, HCTZ)."""
    return t[:1].lower() + t[1:] if len(t) > 1 and not t[1].isupper() else t


def _num(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))


def stem_for(encounter_id: str) -> str:
    return f"visitnote_{encounter_id}"


def run_draft(patient_id: str, encounter_id: str, *, data_dir: Path = DATA_DIR) -> dict:
    """Create a draft once. Existing drafts expose updates without replacing their text."""
    data_dir = Path(data_dir)
    proposed_dir = data_dir.parent / "proposed"
    patient = load_patient(patient_id, data_dir)
    qp = proposed_dir / patient_id / f"{stem_for(encounter_id)}.json"
    if qp.exists():
        from ehr.draft_updates import read_draft
        return read_draft(patient_id, encounter_id, data_dir)
    batch = draft_note(patient, encounter_id, proposed_dir=proposed_dir)
    from ehr.draft_updates import keyed, read_draft
    batch["proposed"]["documents"][0]["sections"] = keyed(batch["proposed"]["documents"][0]["sections"])
    batch["source_sections"] = batch["proposed"]["documents"][0]["sections"]
    qp.parent.mkdir(parents=True, exist_ok=True)
    qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
    return read_draft(patient_id, encounter_id, data_dir)


def sign_draft(patient_id: str, encounter_id: str, sections: list[dict] | None, *, by: str = DEFAULT_REVIEWER,
               data_dir: Path = DATA_DIR, expected_revision: str | None = None) -> dict:
    """Take the clinician's edited text, keep every citation, and sign the note into the chart's documents."""
    data_dir = Path(data_dir)
    qp, batch = load_queue(patient_id, stem_for(encounter_id), data_dir.parent / "proposed")
    doc = batch["proposed"]["documents"][0]
    if doc.get("status") != "proposed":
        raise ValueError("A signed visit note cannot be overwritten. Add an amendment instead.")
    from ehr.draft_updates import edited_sections, fingerprint, preview_updates
    if expected_revision is not None and expected_revision != fingerprint(batch):
        raise ValueError("This draft changed elsewhere. Reopen it before signing.")
    if preview_updates(patient_id, encounter_id, sections, data_dir)["changes"]:
        raise ValueError("Updates are available from the chart. Review and incorporate them before signing.")
    doc["sections"] = edited_sections(doc["sections"], sections)
    for section in doc["sections"]:
        if not section["text"].strip():
            section["cites"] = []
    doc["provenance"]["evidence"] = list(dict.fromkeys(c for s in doc["sections"] for c in s["cites"]))
    patient = load_patient(patient_id, data_dir)
    done = accept_item(patient, batch, doc["id"], review=review_record("accepted", by, encounter_id=encounter_id))
    save_patient(patient, data_dir)
    qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
    return {"document_id": doc["id"], "signed_at": doc["review"]["at"], "by": by, "done": done}


def render_text(doc: dict) -> str:
    out = [doc["title"], ""]
    for s in doc["sections"]:
        out += [s["heading"].upper(), s["text"], ""]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("--encounter", required=True)
    ap.add_argument("--sign", action="store_true", help="sign the queued draft as it stands")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)
    if args.sign:
        print(json.dumps(sign_draft(args.patient_id, args.encounter, None, data_dir=Path(args.data_dir)), indent=2))
        return 0
    batch = run_draft(args.patient_id, args.encounter, data_dir=Path(args.data_dir))
    print(render_text(batch["proposed"]["documents"][0]))
    print(f"\nreview queue: {Path(args.data_dir).parent / 'proposed' / args.patient_id / (batch['stem'] + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
