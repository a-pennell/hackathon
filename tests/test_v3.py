"""v3: the visit as one surface. The claims worth holding are that the reading is placed in the transcript, that what
was dictated is separated from what was inferred, that reading the note before signing writes nothing, and that what
the clinician read is exactly what the signature writes."""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from ehr.extract import run_extraction  # noqa: E402
from ehr.trend import DATA_DIR  # noqa: E402

import v2.api as v2api  # noqa: E402
import v3.api as v3api  # noqa: E402

INFERRED_CAUSE = "lnk_demo_102_20"   # metformin as a cause of the diabetes: the passage says "adherence the main driver"
STATED_CAUSE = "med_demo_102_01"     # the ibuprofen course, whose cause links the passage does state ("likely contributing")


@pytest.fixture
def visit(tmp_path, monkeypatch):
    """A scratch copy of the golden data with the visit's dictation read, and v3 pointed at it. The endpoints write
    through module-level directories, so they are redirected here rather than at the golden copy the suite shares."""
    data = tmp_path / "data"
    shutil.copytree(DATA_DIR, data / "patients")  # the clean copy built by conftest.py
    (data / "proposed" / "pt_002").mkdir(parents=True)
    for f in (DATA_DIR.parent / "proposed" / "pt_002").glob("*.raw.json"):
        shutil.copy(f, data / "proposed" / "pt_002" / f.name)
    for mod, name, value in ((v3api, "DATA_DIR", data / "patients"), (v3api, "PROPOSED_DIR", data / "proposed"),
                             (v2api, "DATA_DIR", data / "patients"), (v2api, "PROPOSED_DIR", data / "proposed")):
        monkeypatch.setattr(mod, name, value)
    run_extraction("pt_002", ROOT / "data" / "notes" / "note_demo_102.json",
                   replay=data / "proposed" / "pt_002" / "note_demo_102.raw.json", data_dir=data / "patients")
    return data


def _snapshot(data: Path) -> tuple:
    return ((data / "patients" / "pt_002.json").read_bytes(),
            sorted((f.name, f.read_bytes()) for f in (data / "proposed" / "pt_002").glob("*.json")))


def test_every_finding_is_placed_in_the_transcript_and_marked_stated_or_inferred(visit):
    v = v3api.visit("pt_002")
    assert v["note"]["read"] and v["utterances"] and v["proposals"]
    text = v["text"]
    for p in v["proposals"]:
        if p["quote"]:
            assert p["offset"] is not None, f"{p['id']} quotes the note but was not placed in it"
            assert text[p["offset"]:p["offset"] + len(p["quote"])] == p["quote"]
    by = {p["id"]: p for p in v["proposals"]}
    # the dictation states the NSAID as contributing; metformin as a cause is the reading going beyond the passage
    assert by[STATED_CAUSE]["origin"] == "stated" and by[STATED_CAUSE]["cause_link_ids"] == ["lnk_demo_102_18", "lnk_demo_102_19"]
    assert by[INFERRED_CAUSE]["origin"] == "inferred"
    assert by[INFERRED_CAUSE]["decision"] is True and by[STATED_CAUSE]["decision"] is False
    # a stated finding takes no click; only what was inferred is put to the clinician
    assert sum(1 for p in v["proposals"] if p["origin"] == "inferred") == 1
    assert sum(1 for p in v["proposals"] if p["origin"] == "stated") > 20


def test_reading_the_note_before_signing_writes_nothing(visit):
    before = _snapshot(visit)
    out = v3api.preview_visit_note("pt_002", v3api.VisitSignBody(
        decisions={INFERRED_CAUSE: "reject"}, reasons={INFERRED_CAUSE: "Non-adherence is the cause, not the drug."},
        authored="Discussed the cost of the switch."))
    assert out["preview"] is True and out["document"]["sections"] and out["manifest"]
    assert _snapshot(visit) == before, "the preview changed the chart or the queue"
    # and it is repeatable: the throwaway copy leaves nothing behind for the next read to pick up
    again = v3api.preview_visit_note("pt_002", v3api.VisitSignBody(
        decisions={INFERRED_CAUSE: "reject"}, reasons={INFERRED_CAUSE: "Non-adherence is the cause, not the drug."},
        authored="Discussed the cost of the switch."))
    assert again["document"]["sections"] == out["document"]["sections"] and again["manifest"] == out["manifest"]
    assert _snapshot(visit) == before


def test_what_the_preview_shows_is_what_the_signature_writes(visit):
    """The point of reading first: the compiled note, the clinician's edit, their own words and the rejection they
    gave a reason for all appear in the preview exactly as the signature will write them."""
    body = v3api.VisitSignBody(
        decisions={INFERRED_CAUSE: "reject"}, reasons={INFERRED_CAUSE: "Non-adherence is the cause, not the drug."},
        sections=[{"heading": "Plan · Albuminuria", "text": "Ibuprofen stopped. Lisinopril started. BMP in two weeks."}],
        authored="Discussed the cost of the switch.")
    preview = v3api.preview_visit_note("pt_002", body)
    shown = preview["document"]["sections"]
    dm = next(s for s in shown if s["heading"] == "Assessment · Diabetes mellitus type 2")
    assert "rejected: Non-adherence is the cause, not the drug." in dm["text"]  # the compiler reads the rejection, not the queue on disk
    edited = next(s for s in shown if s["heading"] == "Plan · Albuminuria")
    assert edited["text"].startswith("Ibuprofen stopped.") and edited["edited"]
    assert shown[-1]["heading"] == "In the clinician's words" and shown[-1]["source"] == "authored"
    counts = {g["kind"]: g["count"] for g in preview["manifest"]}
    assert counts.get("rejected") == 1 and counts.get("problems") == 2  # what the signature attests, listed before it is given
    assert "set_aside" not in counts  # this one was answered, so it is not credited as merely unanswered

    out = v3api.sign_visit("pt_002", body)
    chart = json.loads((visit / "patients" / "pt_002.json").read_text())
    signed = next(d for d in chart["documents"] if d["id"] == out["document_id"])
    # the equality is the point: reading and signing run the same code against different copies of the chart
    assert [(s["heading"], s["text"], s.get("cites")) for s in signed["sections"]] == [(s["heading"], s["text"], s.get("cites")) for s in shown]
    assert out["attested"] > 0 and signed["review"]["encounter_id"] == "enc_c002"


def test_saying_nothing_is_reported_as_set_aside_not_as_a_reasoned_rejection(visit):
    """The manifest is the answer to 'what am I signing'. An inferred finding left unanswered is kept out of the note,
    but the clinician gave no reason for that and the list must not say they did."""
    preview = v3api.preview_visit_note("pt_002", v3api.VisitSignBody())  # nothing answered
    groups = {g["kind"]: g for g in preview["manifest"]}
    assert "rejected" not in groups
    assert groups["set_aside"]["count"] == 1 and groups["set_aside"]["label"] == "set aside, unanswered"
    assert "unanswered" in groups["set_aside"]["items"][0]["text"]


def test_a_visit_is_signed_once(visit):
    v3api.sign_visit("pt_002", v3api.VisitSignBody())
    with pytest.raises(Exception, match="already signed"):
        v3api.sign_visit("pt_002", v3api.VisitSignBody())


def test_signing_hands_off_to_what_the_chart_is_now_waiting_for(visit):
    """The signature is not the end of the visit. It leaves promises with dates — values the plan is expected to move,
    what the plan said it would do and when, and what was left unanswered — and the follow-up answers them."""
    from ehr.extract import save_patient
    from ehr.trend import load_patient
    v3api.sign_visit("pt_002", v3api.VisitSignBody())
    c = v3api.commitments("pt_002", as_of="2026-09-17")
    kinds = {w["kind"] for w in c["watching"]}
    assert {"expectation", "projection", "plan", "set_aside"} <= kinds
    assert c["signed"]["title"].startswith("Visit note")
    assert all(w["status"] == "waiting" for w in c["watching"] if w["kind"] != "set_aside")
    assert c["next_date"] == "2026-09-29" and c["open"] == len([w for w in c["watching"] if w["status"] == "waiting"])
    cr = next(w for w in c["watching"] if w["text"].startswith("Creatinine"))
    assert cr["tested_by"] == "BMP in 2 weeks" and cr["by"] == "2026-10-13"
    assert next(w for w in c["watching"] if w["kind"] == "set_aside")["by"] is None  # nothing is waiting on it; it is just open
    # the promise is dated from the visit, not from today
    assert next(w for w in c["watching"] if w["text"] == "BMP in 2 weeks")["by"] == "2026-09-29"

    # two weeks later the basic metabolic panel lands, and the promises answer themselves
    p = load_patient("pt_002", visit / "patients")
    for oid, code, name, val, unit, rng in (("obs_f001", "38483-4", "Creatinine (whole blood)", 0.9, "mg/dL", {"low": 0.6, "high": 1.2}),
                                            ("obs_f002", "6298-4", "Potassium", 4.4, "mmol/L", {"low": 3.5, "high": 5.1})):
        p["observations"].append({"id": oid, "patient_id": "pt_002", "name": name, "code": {"system": "LOINC", "value": code},
                                  "value": val, "unit": unit, "effective_time": "2026-09-29T09:15:00-05:00", "reference_range": rng,
                                  "status": "accepted", "provenance": {"source": "curated", "followup": True}})
    save_patient(p, visit / "patients")
    after = v3api.commitments("pt_002", as_of="2026-09-30")
    by_text = {w["text"]: w for w in after["watching"]}
    assert by_text["BMP in 2 weeks"]["status"] == "resulted"          # the promise is kept, not still owed
    assert next(w for w in after["watching"] if w["text"].startswith("Creatinine"))["observed"]["status"] == "within"
    assert next(w for w in after["watching"] if w["text"].startswith("Potassium"))["observed"]["status"] == "within"
    assert after["open"] < c["open"]


def test_an_edit_lands_on_the_section_it_was_made_in_even_when_two_problems_share_a_name(visit):
    """Sections were addressed by heading, and a heading is not unique — two problems called the same thing give two
    "Plan · ..." sections, and the edit would land on whichever came first."""
    body = v3api.VisitSignBody()
    doc = v3api.preview_visit_note("pt_002", body)["document"]
    keys = [s["key"] for s in doc["sections"]]
    assert len(keys) == len(set(keys)) and all(keys)
    plan = next(s for s in doc["sections"] if s["heading"].startswith("Plan · Albuminuria"))
    assert plan["key"] == f"plan:{plan['problem_id']}"  # the problem id, not the name, is what identifies it

    edited = v3api.preview_visit_note("pt_002", v3api.VisitSignBody(sections=[{"key": plan["key"], "text": "Rewritten by key."}]))["document"]
    hit = [s for s in edited["sections"] if s.get("edited")]
    assert len(hit) == 1 and hit[0]["key"] == plan["key"] and hit[0]["text"] == "Rewritten by key."


def test_the_note_records_what_the_plan_is_expected_to_do_and_what_the_visit_left(visit):
    """A good note records reasoning, not only data. Two steps of it were computed and shown on screen but never written:
    what a drug started today is expected to push the wrong way (so a creatinine of 1.0 next month reads as expected, not
    as harm), and which problems this visit did not touch (so silence does not read as forgetting)."""
    doc = v3api.preview_visit_note("pt_002", v3api.VisitSignBody())["document"]
    by = {s["key"]: s for s in doc["sections"]}
    htn = by["plan:prob_0007"]["text"]
    assert "Expected on lisinopril: creatinine up to 1.04 mg/dL (from 0.8) and potassium under 5.5 mmol/L; the BMP in 2 weeks tests both." in htn
    assert "If creatinine is above 1.04 mg/dL, or still rising after 4 weeks:" in htn
    assert any(c.startswith("plan_") for c in by["plan:prob_0007"]["cites"])       # tied to the plan line that tests it
    # the drug treats two problems; its expectation is written once, not under both
    albuminuria = next(s for s in doc["sections"] if s["heading"] == "Plan · Albuminuria")
    assert "Expected on lisinopril" not in albuminuria["text"]
    closing = by["not_addressed"]
    assert closing["heading"] == "Not addressed at this visit" and closing["text"] == "Hypertriglyceridemia."
    assert closing["cites"] == ["prob_0011"]


def test_the_note_builds_as_the_dictation_goes_and_is_signed_only_whole(visit):
    """The note is written alongside the reasoning, not after it. Part-way through, the preview compiles only what has
    been spoken — the transcript to that point, the findings it has reached — and the closing list reads as what is not
    yet addressed, shrinking as the visit goes. The signature takes the whole visit, and refuses a partial one."""
    v = v3api.visit("pt_002")
    text, utts = v["text"], v["utterances"]
    def upto(i):  # the dictation as far as utterance i, and the findings that have landed by then
        end = utts[i]["end"]
        return v3api.VisitSignBody(heard=[p["id"] for p in v["proposals"] if p["offset"] is not None and p["offset"] < end], upto=end)
    bp = next(u["i"] for u in utts if u["text"].startswith("BP 154/94"))
    s_line = next(u["i"] for u in utts if u["text"] == "S:")
    early, mid, whole = (v3api.preview_visit_note("pt_002", b)["document"] for b in (upto(s_line), upto(bp), v3api.VisitSignBody()))
    sec = lambda d: {s["key"]: s for s in d["sections"]}  # noqa: E731

    first = early["sections"][0]
    assert first["source"] == "transcript" and first["text"].startswith("Jeane Lueilwitz")
    assert "Tired" not in first["text"] and "154/94" not in first["text"]            # nothing past what has been said
    assert sec(early)["not_addressed"]["heading"] == "Not yet addressed"
    assert "Essential hypertension" in sec(early)["not_addressed"]["text"]

    assert "154/94" in mid["sections"][0]["text"] and "A/P" not in mid["sections"][0]["text"]
    assert "Essential hypertension" not in sec(mid).get("not_addressed", {"text": ""})["text"]  # the pressures have landed on it
    assert len(mid["sections"]) > len(early["sections"])

    assert sec(whole)["not_addressed"]["heading"] == "Not addressed at this visit"
    assert sec(whole)["not_addressed"]["text"] == "Hypertriglyceridemia."

    with pytest.raises(Exception, match="signed whole"):
        v3api.sign_visit("pt_002", upto(bp))


def test_a_question_left_unanswered_is_not_written_into_the_note_as_a_rejection(visit):
    """The screen says an inferred finding without an answer is left out of the note unless the clinician says yes. The
    signature sets it aside as unconfirmed; the note used to write it up as 'rejected: not confirmed at signing',
    recording a decision the clinician never made. An answered 'no' with a reason is still written, because that is
    reasoning the next reader needs."""
    silent = v3api.preview_visit_note("pt_002", v3api.VisitSignBody())["document"]
    dm = next(s for s in silent["sections"] if s["heading"] == "Assessment · Diabetes mellitus type 2")
    assert "rejected" not in dm["text"] and "not confirmed" not in dm["text"]
    assert INFERRED_CAUSE not in dm["cites"]
    said_no = v3api.preview_visit_note("pt_002", v3api.VisitSignBody(
        decisions={INFERRED_CAUSE: "reject"}, reasons={INFERRED_CAUSE: "Non-adherence is the cause, not the drug."}))["document"]
    dm = next(s for s in said_no["sections"] if s["heading"] == "Assessment · Diabetes mellitus type 2")
    assert "rejected: Non-adherence is the cause, not the drug." in dm["text"]


def test_best_practice_is_checked_against_the_plan_as_it_stands(visit):
    """Deciding is a step of the reasoning and best practice is its checklist, but the rules were evaluated against the
    chart as it was before the visit. Against the draft instead, what the clinician has just dictated reads as covered,
    and what is left open is what they might add before signing. Never written into the note."""
    before = {r["id"]: r["status"] for r in v3api.visit("pt_002")["practice"]}
    after = {r["id"]: r["status"] for r in v3api.preview_visit_note("pt_002", v3api.VisitSignBody())["practice"]}
    for rid in ("htn_second_agent", "htn_home_bp", "dm_acr_acei"):  # lisinopril, the home BP log, an ACE inhibitor
        assert before[rid] == "gap" and after[rid] == "covered", rid
    for rid in ("dm_statin", "dm_acr_confirm", "dm_intensify"):   # not dictated: still open at signing
        assert after[rid] == "gap", rid
    doc = v3api.preview_visit_note("pt_002", v3api.VisitSignBody())["document"]
    assert "statin" not in " ".join(s["text"] for s in doc["sections"]).lower()  # a checklist, not the note


def test_during_the_visit_both_best_practice_lists_read_the_plan_as_dictated(visit):
    """The problem page in the middle column computed best practice and the projected options from the chart as it was
    before the visit - nothing is written until the signature - so while the note column said the ACE inhibitor was
    covered, the middle said it was not on the plan, and offered to add the metformin switch just dictated. The draft
    now reports both against the plan as dictated, and the middle column reads them from there."""
    before = {r["id"]: r["status"] for r in v3api.visit("pt_002")["practice"] if r["problem_id"] == "prob_0009"}
    d = v3api.preview_visit_note("pt_002", v3api.VisitSignBody())
    after = {r["id"]: r["status"] for r in d["practice"] if r["problem_id"] == "prob_0009"}
    assert before["dm_acr_acei"] == "gap" and after["dm_acr_acei"] == "covered"
    assert "metformin_taken" in d["on_plan"]["prob_0009"]         # the extended-release switch, dictated
    assert "add_sglt2" not in d["on_plan"].get("prob_0009", [])    # not dictated, still offered
    assert "add_acei" in d["on_plan"]["prob_0007"]                 # lisinopril, on hypertension
