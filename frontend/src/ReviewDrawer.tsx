import { useEffect, useState } from "react";
import { labelOf } from "./labels";
import type { ReviewBody } from "./api";
import type { Group } from "./Inbox";
import type { Link, Medication, Observation, Problem, QueueBatch } from "./types";
import { REASON_CODES } from "./types";

export type MedChange = NonNullable<QueueBatch["medication_changes"]>[number];
/** What the drawer reviews: a proposal group (a problem, a course, a result, a finding with its links) or a medication change. */
export type Reviewable = { g: Group; b: QueueBatch } | { c: MedChange; b: QueueBatch };

type Props = {
  item: Reviewable;
  labels: Record<string, string>;
  problems: Problem[];
  onReview: (stem: string, body: ReviewBody) => Promise<void>;
  onClose: () => void;
  busy: string | null;
};

const band = (c: number | null) => (c == null ? "unknown" : c >= 0.85 ? "high" : c >= 0.6 ? "moderate" : "low");
const LINK_WORD: Record<string, string> = { relevant_to: "bears on", evidence_for: "is evidence for", treats: "treats", suspected_cause: "is a suspected cause of", monitors: "monitors" };

/** The consequential review, one proposal at a time: what the system saw, what it concluded, how sure it is, each part
 *  separately signable; what changes on the chart if you sign; why it needs a signature; sign, or reject with a reason. */
export default function ReviewDrawer({ item, labels, problems, onReview, onClose, busy }: Props) {
  const name = (id: string) => labelOf(labels, id);
  const [obsPart, setObsPart] = useState(true);
  const [attrPart, setAttrPart] = useState(true);
  const [rejecting, setRejecting] = useState(false);
  const [code, setCode] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const isChange = "c" in item;
  const b = item.b;
  const g = isChange ? null : item.g;
  const c = isChange ? item.c : null;
  const subject = g?.subject ?? null;
  const links = g?.links ?? [];
  const prov = (subject?.provenance ?? links[0]?.provenance ?? c?.provenance) as { quote?: string; confidence?: number; model?: string; note_id?: string } | undefined;
  const hint = g?.subject ? b.review_hints?.[g.subject.id] : g ? b.review_hints?.[g.links[0]?.id ?? ""] : c?.hint;  // a link-only group carries its rationale on the link
  const confidence = g?.confidence ?? c?.provenance.confidence ?? null;

  // Title and the three parts.
  let kind = "", title = "", observation = "", attribution = "";
  const changes: { k: string; v: string; strike?: boolean }[] = [];
  const supersedes = g?.kind === "problem" ? problems.find((p) => (b.review_hints?.[g.subjectId] ?? "").includes(p.id)) : undefined;
  if (c) {
    kind = c.change === "stop" ? "course stopped" : c.change.replace("_", " ");
    title = `${name(c.med_id)}: ${c.change.replace("_", " ")} effective ${c.effective}`;
    observation = `The note says: “${c.provenance.quote}”`;
    attribution = c.change === "stop" ? `The course of ${name(c.med_id)} ends on ${c.effective}; its history stays on the chart.`
      : `The current segment of ${name(c.med_id)} closes on ${c.effective} and a new one opens${c.dose ? ` at ${c.dose}` : ""}.`;
    changes.push({ k: "Course", v: name(c.med_id) });
    changes.push({ k: c.change === "stop" ? "Segment closed" : "New segment from", v: c.effective });
    if (c.dose && c.change === "dose_change") changes.push({ k: "Dose", v: c.dose });
    changes.push({ k: "Timeline", v: "the band ends or changes on the trajectory of every problem this course is linked to" });
  } else if (g) {
    const s = subject as (Problem | Medication | Observation | null);
    if (g.kind === "problem" && s) {
      kind = supersedes ? "problem restaged" : "new problem";
      title = supersedes ? `${(s as Problem).name} in place of ${supersedes.name}` : `Raise ${(s as Problem).name}`;
      observation = `The note says: “${g.quote ?? ""}”`;
      attribution = supersedes ? `The condition has progressed: ${supersedes.name} no longer describes it, and ${(s as Problem).name} does.` : `${(s as Problem).name} belongs on the problem list as its own concern.`;
      changes.push({ k: "Problem list gains", v: (s as Problem).name });
      if (supersedes) changes.push({ k: "Stays until you resolve it", v: supersedes.name, strike: false });
      changes.push({ k: "Evidence links carried", v: `${links.length}` });
      changes.push({ k: "Steward", v: "Dr. Chen (PCP)" });
    } else if (g.kind === "medication" && s) {
      const seg = (s as Medication).segments[0];
      kind = "course opened";
      title = `${(s as Medication).name} ${seg.dose ?? ""}: a course to open`;
      observation = `The note says: “${g.quote ?? ""}”`;
      const causes = links.filter((l) => l.type === "suspected_cause");
      attribution = causes.length ? `${(s as Medication).name} is a suspected cause of ${causes.map((l) => name(l.to)).join(", ")}.` : `${(s as Medication).name} is on board from ${seg.start ?? "an unknown date"}.`;
      changes.push({ k: "Medication list gains", v: `${(s as Medication).name} ${seg.dose ?? ""} ${seg.frequency ?? ""}`.trim() });
      changes.push({ k: "Course runs", v: `${seg.start ?? "?"} → ${seg.end ?? "ongoing"}` });
      for (const l of links) changes.push({ k: l.type === "suspected_cause" ? "Cause edge asserted" : "Link asserted", v: `${name(l.from)} ${LINK_WORD[l.type] ?? l.type} ${name(l.to)}` });
    } else if (g.kind === "result" && s) {
      kind = "result";
      title = `${(s as Observation).name} ${(s as Observation).value} ${(s as Observation).unit ?? ""}`;
      observation = `The note says: “${g.quote ?? ""}”`;
      attribution = `This value belongs on the chart as a result on ${(s as Observation).effective_time.slice(0, 10)}${links.length ? `, relevant to ${links.map((l) => name(l.to)).join(", ")}` : ""}.`;
      changes.push({ k: "Result recorded", v: `${(s as Observation).name} ${(s as Observation).value} ${(s as Observation).unit ?? ""} · ${(s as Observation).effective_time.slice(0, 10)}` });
      for (const l of links) changes.push({ k: "Link asserted", v: `${name(l.from)} ${LINK_WORD[l.type] ?? l.type} ${name(l.to)}` });
    } else {
      kind = links.some((l) => l.type === "suspected_cause") ? "suspected cause" : "finding";
      title = `${name(g.subjectId)}`;
      observation = `The note says: “${g.quote ?? ""}”`;
      attribution = links.map((l) => `${name(l.from)} ${LINK_WORD[l.type] ?? l.type} ${name(l.to)}`).join("; ") + ".";
      for (const l of links) changes.push({ k: l.type === "suspected_cause" ? "Cause edge asserted" : "Link asserted", v: `${name(l.from)} ${LINK_WORD[l.type] ?? l.type} ${name(l.to)}` });
    }
  }

  const subjectIds = subject && subject.status === "proposed" ? [subject.id] : [];
  const linkIds = links.filter((l) => l.status === "proposed").map((l) => l.id);
  const hasTwoParts = subjectIds.length > 0 && linkIds.length > 0;
  const toSign = [...(obsPart || !hasTwoParts ? subjectIds : []), ...(attrPart || !hasTwoParts ? linkIds : [])];
  const sign = async () => {
    if (c) await onReview(b.stem, { accept_changes: true });
    else if (toSign.length) await onReview(b.stem, { accept: toSign });
    onClose();
  };
  const reject = async () => {
    const ids = c ? [] : [...subjectIds, ...linkIds];
    if (ids.length) await onReview(b.stem, { reject: ids, reason_code: code ?? undefined, reason: reason || undefined });
    onClose();
  };

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
        <div className="dhead">
          <span className="eyebrow">Consequential change · individual review required</span>
          <h2 id="drawer-title">{title}</h2>
          <p>{kind} · proposed {b.extracted_at?.slice(0, 16).replace("T", " ") ?? ""} by {prov?.model ?? b.model}{subject ? ` · ${subject.id}` : ""}</p>
          <button className="dclose" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        <div className="dbody">
          <section className="dsect">
            <span className="eyebrow">What the system is claiming</span>
            <div className="anat">
              <div className="arow">
                <span className="lab">Observation</span>
                <div className="val">
                  <span className="serif">{observation}</span>
                  {hasTwoParts && <label className="accept"><input type="checkbox" checked={obsPart} onChange={(e) => setObsPart(e.target.checked)} /> accept this part: the thing itself</label>}
                </div>
              </div>
              <div className="arow">
                <span className="lab">Attribution</span>
                <div className="val">
                  {attribution}
                  {hint && <div className="hint">{hint}</div>}
                  {hasTwoParts && <label className="accept"><input type="checkbox" checked={attrPart} onChange={(e) => setAttrPart(e.target.checked)} /> accept this part: the links it makes</label>}
                </div>
              </div>
              <div className="arow">
                <span className="lab">Confidence</span>
                <div className="val"><span className={`conf ${band(confidence)}`}>{band(confidence)}</span> the system's estimate that you sign this as written{prov?.note_id ? ` · from ${name(prov.note_id)}` : ""}</div>
              </div>
            </div>
          </section>

          <section className="dsect">
            <span className="eyebrow">What changes if you sign</span>
            <div className="res">
              {changes.map((x, i) => <div key={i} className="kv"><span className="k">{x.k}</span><span className={`v ${x.strike ? "strike" : ""}`}>{x.v}</span></div>)}
              <div className="kv"><span className="k">Recorded as</span><span className="v">your signature, with the proposal and its provenance kept beside it</span></div>
            </div>
          </section>

          <section className="dsect">
            <p className="guard"><b>Why this needs your signature.</b> {g?.kind === "problem" ? "A problem raised or restaged changes what every later reader believes about this patient, and a wrong one is the error the system cannot catch later." : c ? "A course change rewrites the medication history every problem is read against." : "A cause asserted on the record shapes every later explanation, and a wrong one is hard to unlearn."} Both the proposal and your decision stay on the record either way.</p>
          </section>

          <section className="dsect">
            <div className="dactions">
              <button className="btn primary" disabled={!!busy || (!c && toSign.length === 0)} onClick={sign}>Sign{!c && hasTwoParts && toSign.length < subjectIds.length + linkIds.length ? " the checked parts" : ""}</button>
              {!c && <button className="btn quiet" disabled={!!busy} onClick={() => setRejecting((v) => !v)}>{rejecting ? "Cancel rejection" : "Reject…"}</button>}
              <button className="btn ghost" onClick={onClose}>Not now</button>
            </div>
            {rejecting && (
              <div className="reason">
                <div className="codes">
                  {REASON_CODES.map((r) => <button key={r.code} className={`code ${code === r.code ? "on" : ""}`} onClick={() => setCode(code === r.code ? null : r.code)}>{r.label}</button>)}
                </div>
                <input autoFocus placeholder="What did the system get wrong? One line, in your words." value={reason} onChange={(e) => setReason(e.target.value)} onKeyDown={(e) => e.key === "Enter" && reject()} />
                <div className="row"><span className="spacer" /><button className="btn small" disabled={!!busy} onClick={reject}>Reject and record the reason</button></div>
              </div>
            )}
          </section>
        </div>
      </aside>
    </>
  );
}

export const isConsequential = (g: Group) => g.kind === "problem" || (g.kind === "medication" && !!g.subject) || g.links.some((l: Link) => l.type === "suspected_cause");
