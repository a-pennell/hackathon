import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.extract import (  # noqa: E402
    OUTPUT_SCHEMA, build_messages, chart_context, ingest, validate, verbatim_quote,
)
from ehr.review import accept_item, accept_medication_change, reject_item  # noqa: E402

NOTE_TEXT = """Willie here for follow-up.
S: Knees still bothering him. He has been taking naproxen 500 mg twice a day most days since around April.
Still on metformin 500 mg twice daily. Uses furosemide about every other day now.
O: BP 84/52 sitting. 1+ bilateral pitting edema to the ankles.
Most recent labs (8/19): creatinine 5.7, up from 3.69 in May. eGFR 15.6. K 4.2.
A/P: 1. CKD progressing, eGFR is now under 20. 2. Hold HCTZ starting today. 3. Bilateral knee osteoarthritis."""


@pytest.fixture
def patient():
    return {
        "patient": {"id": "pt_t", "name": "T", "dob": "1967-07-05", "sex": "M"},
        "problems": [
            {"id": "prob_ckd3", "patient_id": "pt_t", "name": "Chronic kidney disease stage 3", "code": None,
             "status": "active", "onset_date": "2025-11-26", "resolved_date": None, "provenance": {"source": "fhir_import"}},
            {"id": "prob_htn", "patient_id": "pt_t", "name": "Essential hypertension", "code": None,
             "status": "active", "onset_date": "2009-07-15", "resolved_date": None, "provenance": {"source": "fhir_import"}},
            {"id": "prob_chf", "patient_id": "pt_t", "name": "Chronic congestive heart failure", "code": None,
             "status": "active", "onset_date": "2022-12-22", "resolved_date": None, "provenance": {"source": "fhir_import"}},
        ],
        "observations": [
            {"id": "obs_00001", "patient_id": "pt_t", "code": {"system": "LOINC", "value": "38483-4"}, "name": "Creatinine (whole blood)",
             "value": 5.7, "unit": "mg/dL", "reference_range": None, "effective_time": "2026-08-19T10:00:00-07:00",
             "status": "accepted", "provenance": {"source": "fhir_import"}},
        ],
        "medications": [
            {"id": "med_metformin", "patient_id": "pt_t", "name": "Metformin", "code": None, "status": "accepted",
             "segments": [{"start": "2016-08-24", "end": None, "dose": "500 mg", "route": "PO", "frequency": None}],
             "provenance": {"source": "fhir_import"}},
            {"id": "med_hctz", "patient_id": "pt_t", "name": "Hydrochlorothiazide", "code": None, "status": "accepted",
             "segments": [{"start": "2016-08-24", "end": None, "dose": "25 mg", "route": "PO", "frequency": "daily"}],
             "provenance": {"source": "fhir_import"}},
        ],
        "encounters": [{"id": "enc_0001", "patient_id": "pt_t", "time": "2026-09-11T09:00:00-07:00", "type": "office visit", "summary": "f/u"}],
        "notes": [], "links": [], "insights": [],
    }


@pytest.fixture
def note():
    return {"id": "note_demo_002", "patient_id": "pt_t", "encounter_id": "enc_0001",
            "time": "2026-09-11T09:40:00-07:00", "author": "Dr. Chen", "text": NOTE_TEXT}


@pytest.fixture
def raw():
    """A plausible model response, including three things the validator must reject."""
    return {
        "problems": [
            {"ref": "new_1", "quote": "CKD progressing, eGFR is now under 20", "name": "Chronic kidney disease stage 4",
             "status": "active", "onset_date": None, "supersedes_problem_id": "prob_ckd3", "confidence": 0.7},
            {"ref": "new_2", "quote": "Bilateral knee osteoarthritis", "name": "Bilateral knee osteoarthritis",
             "status": "active", "onset_date": None, "supersedes_problem_id": None, "confidence": 0.9},
        ],
        "observations": [
            {"quote": "creatinine 5.7", "loinc": "38483-4", "value": 5.7, "unit": "mg/dL", "date": "2026-08-19",
             "problem_refs": ["prob_ckd3", "new_1"], "confidence": 0.95},
            {"quote": "eGFR   15.6", "loinc": "33914-3", "value": 15.6, "unit": None, "date": "2026-08-19",
             "problem_refs": ["prob_ckd3"], "confidence": 0.95},
            {"quote": "BP 84/52", "loinc": "8480-6", "value": 84, "unit": "mm[Hg]", "date": None, "problem_refs": ["prob_htn"], "confidence": 0.9},
            {"quote": "BP 84/52", "loinc": "8462-4", "value": 52, "unit": "mm[Hg]", "date": None, "problem_refs": ["prob_htn"], "confidence": 0.9},
            {"quote": "K 4.2", "loinc": "9999-9", "value": 4.2, "unit": None, "date": "2026-08-19", "problem_refs": [], "confidence": 0.9},  # bad code
            {"quote": "hemoglobin 9.1", "loinc": "718-7", "value": 9.1, "unit": None, "date": None, "problem_refs": [], "confidence": 0.9},  # not in note
        ],
        "findings": [
            {"quote": "1+ bilateral pitting edema to the ankles", "summary": "ankle edema", "problem_refs": ["prob_chf"], "confidence": 0.85},
            {"quote": "Knees still bothering him", "summary": "knee pain", "problem_refs": ["prob_nope"], "confidence": 0.8},  # bad ref
        ],
        "medications": [
            {"ref": "new_3", "quote": "taking naproxen 500 mg twice a day most days since around April", "name": "Naproxen",
             "dose": "500 mg", "route": "PO", "frequency": "twice daily", "start": "2026-04-01", "end": None,
             "existing_med_id": None, "change": "new", "treats_problem_refs": ["new_2"], "confidence": 0.9},
            {"ref": "new_4", "quote": "Still on metformin 500 mg twice daily", "name": "Metformin", "dose": "500 mg", "route": None,
             "frequency": "twice daily", "start": None, "end": None, "existing_med_id": "med_metformin", "change": "confirm",
             "treats_problem_refs": [], "confidence": 0.95},
            {"ref": "new_5", "quote": "Hold HCTZ starting today", "name": "Hydrochlorothiazide", "dose": None, "route": None,
             "frequency": None, "start": None, "end": "2026-09-11", "existing_med_id": "med_hctz", "change": "stop",
             "treats_problem_refs": [], "confidence": 0.9},
        ],
        "suspected_causes": [
            {"quote": "taking naproxen 500 mg twice a day most days since around April", "cause_ref": "new_3",
             "effect_ref": "LOINC:38483-4", "rationale": "NSAID exposure preceding creatinine rise", "confidence": 0.7},
        ],
    }


def test_verbatim_quote_tolerates_whitespace_and_case():
    assert verbatim_quote("eGFR   15.6", NOTE_TEXT) == "eGFR 15.6"
    assert verbatim_quote("bp 84/52", NOTE_TEXT) == "BP 84/52"
    assert verbatim_quote("hemoglobin 9.1", NOTE_TEXT) is None
    assert verbatim_quote("", NOTE_TEXT) is None


def test_validate_builds_schema_entities_and_rejects_bad_items(patient, note, raw):
    batch = validate(patient, note, raw, "claude-test")
    p = batch["proposed"]

    assert [x["name"] for x in p["problems"]] == ["Chronic kidney disease stage 4", "Bilateral knee osteoarthritis"]
    assert all(x["status"] == "proposed" and x["id"].startswith("prob_demo_002_") for x in p["problems"])
    assert batch["review_hints"][p["problems"][0]["id"]].startswith("supersedes prob_ckd3")

    # creatinine 5.7 on 8/19 already exists -> reused, not duplicated; eGFR + BP are new
    assert [x["name"] for x in p["observations"]] == ["eGFR", "Systolic blood pressure", "Diastolic blood pressure"]
    egfr = p["observations"][0]
    assert egfr["effective_time"] == "2026-08-19T00:00:00-07:00" and egfr["unit"] == "mL/min/{1.73_m2}"
    assert egfr["provenance"] == {"source": "nlp_extraction", "note_id": "note_demo_002", "quote": "eGFR 15.6",
                                  "model": "extractor-v1/claude-test", "confidence": 0.95}
    assert p["observations"][1]["effective_time"] == note["time"]  # no date -> note time
    assert "already in chart" in batch["review_hints"]["obs_00001"]

    reasons = [r["reason"] for r in batch["rejected"]]
    assert any("9999-9" in r for r in reasons)
    assert any("not found verbatim" in r for r in reasons)
    assert any("does not resolve" in r for r in reasons)

    assert [m["name"] for m in p["medications"]] == ["Naproxen"]
    nap = p["medications"][0]
    assert nap["segments"] == [{"start": "2026-04-01", "end": None, "dose": "500 mg", "route": "PO", "frequency": "twice daily"}]
    assert batch["confirmed_medications"][0]["med_id"] == "med_metformin"
    assert batch["medication_changes"][0] | {"provenance": None} == {
        "med_id": "med_hctz", "change": "stop", "effective": "2026-09-11", "dose": None, "route": None,
        "frequency": None, "status": "proposed", "provenance": None}

    kinds = {(l["from"], l["to"], l["type"]) for l in p["links"]}
    assert ("obs_00001", "prob_ckd3", "relevant_to") in kinds            # existing obs linked to existing problem
    assert ("obs_00001", p["problems"][0]["id"], "relevant_to") in kinds  # ... and to the new stage-4 problem
    assert ("note_demo_002", "prob_chf", "evidence_for") in kinds
    assert (nap["id"], p["problems"][1]["id"], "treats") in kinds
    assert (nap["id"], "LOINC:38483-4", "suspected_cause") in kinds
    ids = [l["id"] for l in p["links"]]
    assert len(ids) == len(set(ids)) and all(i.startswith("lnk_demo_002_") for i in ids)
    for l in p["links"]:
        assert l["status"] == "proposed" and l["provenance"]["source"] == "nlp_extraction" and l["provenance"]["quote"]
        assert l["type"] in {"relevant_to", "treats", "evidence_for", "suspected_cause"}


def test_fuzzy_dedupe_and_stop_by_name(patient, note):
    raw = {"problems": [], "findings": [], "suspected_causes": [],
           "observations": [
               # same value as the charted whole-blood creatinine, but coded serum and dated 3 days off
               {"quote": "creatinine 5.7", "loinc": "2160-0", "value": 5.7, "unit": None, "date": "2026-08-22", "problem_refs": ["prob_ckd3"], "confidence": 0.9},
               # a genuinely new value
               {"quote": "eGFR 15.6", "loinc": "33914-3", "value": 15.6, "unit": None, "date": "2026-08-19", "problem_refs": [], "confidence": 0.9}],
           "medications": [
               {"ref": "new_1", "quote": "taking naproxen 500 mg twice a day most days since around April", "name": "Naproxen", "dose": "500 mg", "route": "PO",
                "frequency": "bid", "start": "2026-04-01", "end": None, "existing_med_id": None, "change": "new", "treats_problem_refs": [], "confidence": 0.9},
               {"ref": "new_2", "quote": "Hold HCTZ starting today", "name": "naproxen", "dose": None, "route": None, "frequency": None, "start": None,
                "end": None, "existing_med_id": None, "change": "stop", "treats_problem_refs": [], "confidence": 0.8}]}
    batch = validate(patient, note, raw, "claude-test")
    p = batch["proposed"]
    assert [o["name"] for o in p["observations"]] == ["eGFR"]                      # creatinine reused obs_00001
    assert any(l["from"] == "obs_00001" and l["to"] == "prob_ckd3" for l in p["links"])
    assert batch["rejected"] == []
    assert p["medications"][0]["segments"][-1]["end"] == "2026-09-11"          # stop applied to the new course
    assert "closed 2026-09-11" in batch["review_hints"][p["medications"][0]["id"]]


def test_dose_change_without_value_keeps_instruction(patient, note):
    raw = {"problems": [], "findings": [], "suspected_causes": [], "observations": [],
           "medications": [{"ref": "c1", "quote": "Still on metformin 500 mg twice daily", "name": "Metformin", "dose": None, "route": None,
                            "frequency": None, "start": None, "end": None, "existing_med_id": "med_metformin", "change": "dose_change",
                            "treats_problem_refs": [], "confidence": 0.8}]}
    batch = validate(patient, note, raw, "claude-test")
    ch = batch["medication_changes"][0]
    assert ch["dose"] == "Still on metformin 500 mg twice daily" and "numeric dose" in ch["hint"]
    assert batch["rejected"] == []


def test_record_response_keeps_timestamped_copy(tmp_path):
    from ehr.extract import record_response
    qp = tmp_path / "pt_x" / "note_1.json"
    qp.parent.mkdir()
    a = record_response(qp, {"parsed": {"v": 1}})
    b = record_response(qp, {"parsed": {"v": 2}})
    assert a.exists() and a.name.startswith("note_1.") and a.name.endswith(".raw.json")
    assert json.loads((qp.with_suffix(".raw.json")).read_text())["parsed"]["v"] == 2   # latest pointer
    assert a != b or json.loads(a.read_text())["parsed"]["v"] in (1, 2)                 # same-second collision tolerated


def test_accept_all_skips_links_into_rejected_items(patient, note, raw, tmp_path):
    from ehr.review import apply_review
    (tmp_path / "patients").mkdir(); (tmp_path / "proposed" / "pt_t").mkdir(parents=True)
    ingest(patient, note, None)  # the note is on the chart, as it would be after ingest
    (tmp_path / "patients" / "pt_t.json").write_text(json.dumps(patient))
    batch = validate(patient, note, raw, "claude-test")
    (tmp_path / "proposed" / "pt_t" / "note_demo_002.json").write_text(json.dumps(batch))
    knee = batch["proposed"]["problems"][1]["id"]
    apply_review("pt_t", "note_demo_002", reject=[knee], reason_code="not_relevant", data_dir=tmp_path / "patients")
    done = apply_review("pt_t", "note_demo_002", accept_all=True, accept_changes=True, data_dir=tmp_path / "patients")
    skipped = [d for d in done if d.startswith("skipped")]
    assert skipped and all(knee in d for d in skipped)          # the treats link into the rejected problem
    chart = json.loads((tmp_path / "patients" / "pt_t.json").read_text())
    assert not any(l["to"] == knee for l in chart["links"])
    assert any(m["name"] == "Naproxen" for m in chart["medications"])  # everything else signed


def test_undo_review_returns_item_and_its_links_to_proposed(patient, note, raw, tmp_path):
    from ehr.review import apply_review, undo_review
    (tmp_path / "patients").mkdir(); (tmp_path / "proposed" / "pt_t").mkdir(parents=True)
    ingest(patient, note, None)
    (tmp_path / "patients" / "pt_t.json").write_text(json.dumps(patient))
    batch = validate(patient, note, raw, "claude-test")
    (tmp_path / "proposed" / "pt_t" / "note_demo_002.json").write_text(json.dumps(batch))
    nap = batch["proposed"]["medications"][0]["id"]
    treats = next(l for l in batch["proposed"]["links"] if l["from"] == nap and l["type"] == "treats")
    apply_review("pt_t", "note_demo_002", accept=[treats["id"]], data_dir=tmp_path / "patients")   # signs naproxen + knee problem too
    chart = json.loads((tmp_path / "patients" / "pt_t.json").read_text())
    assert any(m["id"] == nap for m in chart["medications"]) and any(l["id"] == treats["id"] for l in chart["links"])
    done = undo_review("pt_t", "note_demo_002", [nap], data_dir=tmp_path / "patients")
    assert any(d.startswith(f"medication {nap} unsigned") for d in done) and any(treats["id"] in d for d in done)
    chart = json.loads((tmp_path / "patients" / "pt_t.json").read_text())
    assert not any(m["id"] == nap for m in chart["medications"]) and not any(l["id"] == treats["id"] for l in chart["links"])
    q = json.loads((tmp_path / "proposed" / "pt_t" / "note_demo_002.json").read_text())
    assert next(m for m in q["proposed"]["medications"] if m["id"] == nap)["status"] == "proposed"
    assert next(l for l in q["proposed"]["links"] if l["id"] == treats["id"])["status"] == "proposed"


def test_ingest_is_idempotent(patient, note):
    enc = {"id": "enc_0002", "patient_id": "pt_t", "time": "2026-09-12T09:00:00-07:00", "type": "office visit", "summary": "x"}
    n2 = dict(note, id="note_x", encounter_id="enc_0002")
    assert ingest(patient, n2, enc) == ["encounter enc_0002 added", "note note_x added"]
    assert ingest(patient, n2, enc) == []
    assert len(patient["notes"]) == 1 and len(patient["encounters"]) == 2
    with pytest.raises(ValueError):
        ingest(patient, dict(note, id="note_y", encounter_id="enc_missing"), None)


def test_prompt_contains_chart_ids_and_note(patient, note):
    system_blocks, messages = build_messages(patient, note)
    text = "\n".join(b["text"] for b in system_blocks)
    assert "prob_ckd3" in text and "med_metformin" in text and "38483-4" in text
    assert system_blocks[-1]["cache_control"] == {"type": "ephemeral"}
    assert NOTE_TEXT in messages[0]["content"] and "note_demo_002" in messages[0]["content"]
    assert set(chart_context(patient)) == {"patient", "problems", "medications"}
    json.dumps(OUTPUT_SCHEMA)  # serializable


def test_review_accept_and_reject(patient, note, raw):
    batch = validate(patient, note, raw, "claude-test")
    chart = copy.deepcopy(patient)
    link = next(l for l in batch["proposed"]["links"] if l["type"] == "suspected_cause")
    done = accept_item(chart, batch, link["id"])
    # accepting the link pulled in the proposed naproxen course
    assert any(d.startswith("medication med_demo_002_") for d in done) and any(d.startswith("link") for d in done)
    nap = next(m for m in chart["medications"] if m["name"] == "Naproxen")
    assert nap["status"] == "accepted" and nap["provenance"]["source"] == "nlp_extraction"
    assert any(l["id"] == link["id"] and l["status"] == "accepted" for l in chart["links"])
    assert accept_item(chart, batch, link["id"]) == []  # idempotent

    prob = batch["proposed"]["problems"][1]
    assert reject_item(batch, prob["id"]).endswith("rejected")
    with pytest.raises(ValueError):
        accept_item(chart, batch, prob["id"])
    assert not any(p["id"] == prob["id"] for p in chart["problems"])
    # a link into the rejected problem cannot be signed either (no dangling links on the chart)
    treats = next(l for l in batch["proposed"]["links"] if l["type"] == "treats" and l["to"] == prob["id"])
    with pytest.raises(ValueError):
        accept_item(chart, batch, treats["id"])
    assert not any(l["id"] == treats["id"] for l in chart["links"])

    msg = accept_medication_change(chart, batch["medication_changes"][0])
    hctz = next(m for m in chart["medications"] if m["id"] == "med_hctz")
    assert hctz["segments"][-1]["end"] == "2026-09-11" and "stopped" in msg


def test_stop_of_a_course_the_chart_never_held_opens_it_with_its_end(patient, note):
    raw = {"problems": [], "findings": [], "observations": [], "plans": [],
           "medications": [
               {"ref": "med_2", "quote": "taking naproxen 500 mg twice a day most days since around April", "name": "Ibuprofen", "dose": "400 mg",
                "route": "PO", "frequency": "bid", "start": "2026-05-01", "end": None, "existing_med_id": None, "change": "stop",
                "treats_problem_refs": [], "confidence": 0.87}],
           "suspected_causes": [
               {"quote": "Hold HCTZ starting today", "cause_ref": "med_2", "effect_ref": "prob_htn", "rationale": "NSAID", "confidence": 0.85}]}
    batch = validate(patient, note, raw, "claude-test")
    p = batch["proposed"]
    assert batch["rejected"] == []
    course = p["medications"][0]
    assert course["name"] == "Ibuprofen" and course["segments"] == [{"start": "2026-05-01", "end": "2026-09-11", "dose": "400 mg", "route": "PO", "frequency": "bid"}]
    assert "never held" in batch["review_hints"][course["id"]]
    assert any(l["from"] == course["id"] and l["to"] == "prob_htn" and l["type"] == "suspected_cause" for l in p["links"])  # the ref resolves


def test_undated_earlier_half_of_a_comparison_attaches_or_drops(patient, note):
    patient = copy.deepcopy(patient)
    patient["observations"].append({"id": "obs_may", "patient_id": "pt_t", "code": {"system": "LOINC", "value": "38483-4"}, "name": "Creatinine (whole blood)",
                                    "value": 3.69, "unit": "mg/dL", "reference_range": None, "effective_time": "2026-05-20T10:00:00-07:00",
                                    "status": "accepted", "provenance": {"source": "fhir_import"}})
    note = {**note, "text": note["text"] + "\nK 4.2, up from 3.8."}
    raw = {"problems": [], "findings": [], "suspected_causes": [], "medications": [], "plans": [],
           "observations": [
               # the earlier half of a comparison, undated: it is the charted May value, not a new result on the note date
               {"quote": "up from 3.69 in May", "loinc": "2160-0", "value": 3.69, "unit": None, "date": None, "problem_refs": ["prob_ckd3"], "confidence": 0.6},
               # an undated comparison value the chart never saw: dropped rather than charted today
               {"quote": "up from 3.8", "loinc": "6298-4", "value": 3.8, "unit": None, "date": None, "problem_refs": ["prob_ckd3"], "confidence": 0.6},
               # this visit's value quoted with its comparison: new data, kept
               {"quote": "creatinine 5.7, up from 3.69 in May", "loinc": "2160-0", "value": 5.7, "unit": None, "date": None, "problem_refs": ["prob_ckd3"], "confidence": 0.9}]}
    batch = validate(patient, note, raw, "claude-test")
    p = batch["proposed"]
    assert [o["value"] for o in p["observations"]] == [5.7]
    assert any(l["from"] == "obs_may" and l["to"] == "prob_ckd3" for l in p["links"])
    assert [r["reason"] for r in batch["rejected"]] == ["earlier value of a comparison, undated and not on the chart"]
