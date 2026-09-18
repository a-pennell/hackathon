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
