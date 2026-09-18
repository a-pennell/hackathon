"""What a dictation states, and what the reading added on top of it.

A finding marked "stated" is accepted by the visit's signature without a click, so this classifier decides what a
clinician never has to look at. That makes its two kinds of error completely different: calling a stated thing
"inferred" costs one click, while calling an inferred — or denied — thing "stated" attests a claim the clinician did
not make. Every case below is written as dictation and judged on what the passage does, not on what the code does.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from v3.api import _origin  # noqa: E402

ASSERTS_A_CAUSE = [
    ("Daily NSAID use since May, likely contributing.", "Ibuprofen"),
    ("Albuminuria, probably secondary to the ibuprofen.", "Ibuprofen"),
    ("Pressure is up because of the ibuprofen she has been taking.", "Ibuprofen"),
    ("Her cough is due to the lisinopril.", "Lisinopril"),
    ("The ibuprofen explains the rise in her creatinine.", "Ibuprofen"),
    ("Hypertension aggravated by her daily ibuprofen.", "Ibuprofen"),
    ("Pressure rose on the back of the ibuprofen.", "Ibuprofen"),
]

DENIES_OR_OMITS_A_CAUSE = [
    ("I doubt the ibuprofen is contributing.", "Ibuprofen"),
    ("The albuminuria is not due to the ibuprofen.", "Ibuprofen"),
    ("She stopped the ibuprofen in June, so that is not the cause.", "Ibuprofen"),
    ("No reason to think the lisinopril caused this.", "Lisinopril"),
    ("Unlikely to be due to the hydrochlorothiazide.", "Hydrochlorothiazide"),
    ("Not from the metformin, though I checked a B12 anyway.", "Metformin hydrochloride"),
    ("Continue ibuprofen as needed for the back.", "Ibuprofen"),                        # named, nothing asserted
    ("She is on hydrochlorothiazide 25 mg.", "Hydrochlorothiazide"),                    # named, nothing asserted
    ("Type 2 diabetes, uncontrolled, adherence the main driver.", "Metformin hydrochloride"),  # a cause, but not this one
    ("She wondered about the new blood pressure tablet.", "Lisinopril"),                # the patient's idea, not the clinician's
]

DENIES_OR_OMITS_A_PROBLEM = [
    ("No evidence of albuminuria.", "Albuminuria"),
    ("Screening negative for albuminuria.", "Albuminuria"),
    ("Ruled out albuminuria.", "Albuminuria"),
    ("Albuminuria has resolved.", "Albuminuria"),
]


@pytest.mark.parametrize("quote,name", DENIES_OR_OMITS_A_CAUSE)
def test_a_cause_the_passage_does_not_assert_is_never_waved_through(quote, name):
    """The error that must not happen: a denial or a silence read as an assertion and attested by the signature."""
    assert _origin("cause", quote, cause_name=name) == "inferred"


@pytest.mark.parametrize("quote,name", DENIES_OR_OMITS_A_PROBLEM)
def test_a_problem_the_passage_rules_out_is_never_waved_through(quote, name):
    assert _origin("problem", quote, problem_name=name) == "inferred"


@pytest.mark.parametrize("quote,name", ASSERTS_A_CAUSE)
def test_a_plainly_asserted_cause_needs_no_click(quote, name):
    assert _origin("cause", quote, cause_name=name) == "stated"


def test_a_problem_the_passage_names_needs_no_click():
    assert _origin("problem", "Hypertension, above goal on HCTZ alone, with new albuminuria.", problem_name="Albuminuria") == "stated"
    assert _origin("problem", "New peripheral neuropathy, distal and symmetric, almost certainly diabetic.", problem_name="Peripheral neuropathy") == "stated"


def test_results_courses_and_plans_are_the_passage_itself():
    for kind in ("result", "course", "plan", "finding"):
        assert _origin(kind, "BP 134/82 sitting.") == "stated"
    assert _origin("result", None) == "inferred"  # nothing to read means nothing was stated


def test_the_classifier_errs_towards_asking_and_the_misses_are_all_that_direction():
    """A second dictation, four weeks on. It is allowed to miss assertions — that costs a click — but it must not
    manufacture one. These three are known misses, recorded so a change that turns any of them into "stated" without
    also handling the denials above is caught here."""
    hedged_but_asserted = [("I think this is the lisinopril.", "Lisinopril"),
                           ("New peripheral neuropathy, distal and symmetric, almost certainly diabetic.", "Diabetes mellitus type 2")]
    for quote, name in hedged_but_asserted:
        assert _origin("cause", quote, cause_name=name) == "inferred"  # a miss, in the safe direction
    # sentence-level negation is blunt: "no fever" costs the cough a click, and that is the trade we chose
    assert _origin("problem", "Dry cough for about two weeks, worse at night, no fever, no sputum.", problem_name="Cough") == "inferred"


# --- the extractor's own answer (schema §13), which is better evidence than cue words after the fact ---

def test_the_extractors_answer_decides_when_it_gave_one():
    # a cause it says it inferred is put to the clinician, however plainly the sentence reads
    assert _origin("cause", "Daily NSAID use since May, likely contributing.", cause_name="Ibuprofen", asserted=False) == "inferred"
    # and one it says the passage states is taken, even when no cue word in our list appears
    assert _origin("cause", "I think this is the lisinopril.", cause_name="Lisinopril", asserted=True) == "stated"
    assert _origin("cause", "Her albuminuria is likely the ibuprofen's doing.", cause_name="Ibuprofen", asserted=True) == "stated"
    # the same for a new problem the rule's blunt negation guard would have sent back
    assert _origin("problem", "Dry cough for two weeks, no fever, no sputum.", problem_name="Cough", asserted=True) == "stated"


def test_an_outright_denial_is_refused_even_if_the_extractor_says_otherwise():
    """The one veto kept over the extractor. A model that reads 'not due to the ibuprofen' as an assertion would have
    the signature attest the opposite of what was dictated, and no downstream step would catch it."""
    for quote in ("The albuminuria is not due to the ibuprofen.",
                  "I doubt the ibuprofen is contributing.",
                  "No evidence of an NSAID effect.",
                  "Ruled out the ibuprofen as a cause.",
                  "Not from the metformin, though I checked a B12 anyway."):
        assert _origin("cause", quote, cause_name="Ibuprofen", asserted=True) == "inferred", quote


def test_without_the_field_the_rule_still_applies():
    assert _origin("cause", "Daily NSAID use since May, likely contributing.", cause_name="Ibuprofen") == "stated"
    assert _origin("cause", "I doubt the ibuprofen is contributing.", cause_name="Ibuprofen") == "inferred"


def test_the_field_reaches_the_reader_from_a_queue(tmp_path):
    """End to end: an extraction that carries the flag changes what the visit puts to the clinician. The recordings in
    data/proposed predate the field, so this builds a batch the way the extractor now writes one."""
    import json
    import shutil
    import pytest as _pytest
    from ehr.extract import run_extraction
    from ehr.trend import DATA_DIR
    import v2.api as v2api
    import v3.api as v3api

    data = tmp_path / "data"
    shutil.copytree(DATA_DIR, data / "patients")
    (data / "proposed" / "pt_002").mkdir(parents=True)
    for f in (DATA_DIR.parent / "proposed" / "pt_002").glob("*.raw.json"):
        shutil.copy(f, data / "proposed" / "pt_002" / f.name)
    mp = _pytest.MonkeyPatch()
    for mod, name, value in ((v3api, "DATA_DIR", data / "patients"), (v3api, "PROPOSED_DIR", data / "proposed"),
                             (v2api, "DATA_DIR", data / "patients"), (v2api, "PROPOSED_DIR", data / "proposed")):
        mp.setattr(mod, name, value)
    try:
        run_extraction("pt_002", ROOT / "data" / "notes" / "note_demo_102.json",
                       replay=data / "proposed" / "pt_002" / "note_demo_102.raw.json", data_dir=data / "patients")
        qp = data / "proposed" / "pt_002" / "note_demo_102.json"
        batch = json.loads(qp.read_text())
        # the NSAID cause reads as stated today, on the rule alone
        assert next(p for p in v3api.visit("pt_002")["proposals"] if p["id"] == "med_demo_102_01")["origin"] == "stated"
        # the extractor, having read the passage, says it was the one drawing the line
        for l in batch["proposed"]["links"]:
            if l["id"] in ("lnk_demo_102_18", "lnk_demo_102_19"):
                l["provenance"]["asserted"] = False
        qp.write_text(json.dumps(batch, indent=2))
        again = next(p for p in v3api.visit("pt_002")["proposals"] if p["id"] == "med_demo_102_01")
        assert again["origin"] == "inferred" and again["decision"] is True  # so it is now asked, not waved through
    finally:
        mp.undo()
