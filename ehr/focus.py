"""Clinical focus helpers shared by the card, the overview and the care view.

A cluster is the view-level answer to Synthea's one-problem-per-condition import: active problems
that monitor exactly the same series read as one concern, represented by the newest entry. The
merge itself stays a steward's decision (PRD-03); nothing here writes.
"""

from __future__ import annotations

from ehr.reason import _accepted, monitored_codes


def clusters(patient: dict) -> list[dict]:
    """Active problems grouped by identical monitored-series sets; the newest entry represents the group."""
    groups: dict[str, list[dict]] = {}
    codes_of: dict[str, list[str]] = {}
    for p in patient["problems"]:
        if p["status"] != "active":
            continue
        codes = sorted(monitored_codes(patient, p["id"]))
        key = ",".join(codes) if codes else p["id"]
        groups.setdefault(key, []).append(p)
        codes_of[key] = codes
    out = []
    for key, members in groups.items():
        members.sort(key=lambda p: p.get("onset_date") or "", reverse=True)
        out.append({"problem": members[0], "members": members[1:], "codes": codes_of[key]})
    return out


def cluster_of(patient: dict, problem_id: str) -> dict | None:
    for cl in clusters(patient):
        if cl["problem"]["id"] == problem_id or any(m["id"] == problem_id for m in cl["members"]):
            return cl
    return None


def focus_ids(patient: dict, problem_id: str) -> set[str]:
    """Every id that counts as 'about this problem': the problem and its cluster, its monitored series (as
    LOINC targets and as observation ids), the courses linked to it, and the links themselves."""
    cl = cluster_of(patient, problem_id)
    ids = {problem_id} | ({cl["problem"]["id"]} | {m["id"] for m in cl["members"]} if cl else set())
    codes = set(cl["codes"]) if cl else set(monitored_codes(patient, problem_id))
    ids |= {f"LOINC:{c}" for c in codes}
    ids |= {o["id"] for o in patient.get("observations", []) if o["code"]["value"] in codes}
    for l in _accepted(patient.get("links", [])):
        if l["to"] in ids or l["from"] in ids:
            ids |= {l["id"], l["from"], l["to"]}
    for k in ("plans", "orders", "insights", "documents"):
        ids |= {x["id"] for x in patient.get(k, []) if x.get("problem_id") in ids}
    return ids
