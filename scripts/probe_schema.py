"""Find what the constrained-output grammar actually objects to.

    python3 scripts/probe_schema.py

The extractor's schema is refused with "the compiled grammar is too large", with and without the server-side
fallback, and shrinking it by 84% did not help — so the cost is not what we assumed. This asks the API directly:
each variant below is sent as a real request with max_tokens small enough to cost nothing, and the 400 (or its
absence) arrives during request validation, before any generation. Nothing is written to any chart.

Reads ANTHROPIC_API_KEY from the environment like everything else. It is never printed.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.extract import OUTPUT_SCHEMA  # noqa: E402

SECTIONS = list(OUTPUT_SCHEMA["properties"])


def only(*keep: str) -> dict:
    s = copy.deepcopy(OUTPUT_SCHEMA)
    s["properties"] = {k: v for k, v in s["properties"].items() if k in keep}
    s["required"] = [k for k in s.get("required", []) if k in keep]
    return s


def strip(node, *, drop_additional=False, drop_required=False, drop_desc=False):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if drop_additional and k == "additionalProperties":
                continue
            if drop_required and k == "required":
                continue
            if drop_desc and k == "description":
                continue
            out[k] = strip(v, drop_additional=drop_additional, drop_required=drop_required, drop_desc=drop_desc)
        return out
    if isinstance(node, list):
        return [strip(v, drop_additional=drop_additional, drop_required=drop_required, drop_desc=drop_desc) for v in node]
    return node


def props(schema) -> int:
    n = 0
    if isinstance(schema, dict):
        if schema.get("type") == "object" and "properties" in schema:
            n += len(schema["properties"])
        for v in schema.values():
            n += props(v)
    elif isinstance(schema, list):
        for v in schema:
            n += props(v)
    return n


def main() -> int:
    import anthropic
    client = anthropic.Anthropic()

    def works(schema: dict) -> tuple[bool, str]:
        try:
            client.messages.create(
                model="claude-opus-5", max_tokens=16,
                messages=[{"role": "user", "content": "ok"}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
            return True, ""
        except anthropic.BadRequestError as e:
            msg = str(e)
            short = "grammar too large" if "grammar is too large" in msg else msg[:90]
            return False, short
        except Exception as e:  # noqa: BLE001 — any other failure is worth seeing verbatim
            return False, f"{type(e).__name__}: {str(e)[:90]}"

    cases = [("full schema, as shipped", OUTPUT_SCHEMA)]
    cases += [(f"only {s}", only(s)) for s in SECTIONS]
    cases += [
        ("first three sections", only(*SECTIONS[:3])),
        ("last three sections", only(*SECTIONS[3:])),
        ("full, no additionalProperties", strip(OUTPUT_SCHEMA, drop_additional=True)),
        ("full, no required", strip(OUTPUT_SCHEMA, drop_required=True)),
        ("full, no descriptions", strip(OUTPUT_SCHEMA, drop_desc=True)),
        ("full, none of those three", strip(OUTPUT_SCHEMA, drop_additional=True, drop_required=True, drop_desc=True)),
    ]

    print(f"{'variant':32} {'props':>5} {'bytes':>6}  result")
    print("-" * 78)
    for label, schema in cases:
        ok, why = works(schema)
        print(f"{label:32} {props(schema):5} {len(json.dumps(schema)):6}  {'OK' if ok else 'refused: ' + why}")
    print("\nThe narrowest variant that is refused is what has to change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
