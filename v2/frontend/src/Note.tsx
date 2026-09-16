import { useEffect, useState } from "react";
import { api } from "./api";
import type { Ctx } from "./App";
import type { NoteView } from "./v2types";

const dmy = (iso: string) => { const d = new Date(iso.slice(0, 10) + "T00:00:00"); return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })} ${d.getFullYear()}`; };

/** The visit note, assembled. Sections compiled from what was decided at this visit, each citing the record; the
 *  dictated history verbatim; a box for anything the clinician wants to add in their own words. Sign to freeze it. */
export default function Note({ pid, listing, busy, run, refreshKey }: Ctx) {
  const [n, setN] = useState<NoteView | null>(null);
  const [text, setText] = useState<Record<number, string>>({});
  const [authored, setAuthored] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.note(pid).then(setN).catch((e) => setErr(String(e.message))); }, [pid, refreshKey]);
  if (err) return <div className="lede">{err}</div>;
  if (!n) return <div className="lede">Assembling the visit note…</div>;
  const doc = n.signed ?? n.compiled;  // the record is the draft; edits travel with the signature
  const signed = !!n.signed;
  const val = (i: number) => text[i] ?? doc.sections[i].text;
  const here = listing.here_for.note;
  const ready = here?.status === "signed";
  return (
    <div>
      <h1>{doc.title}</h1>
      <p className="lede">{signed ? `Signed by ${n.signed!.review?.by} on ${dmy(n.signed!.review?.at ?? "")}. Everything below was attested by that signature.` : ready ? "This is the one signature of the visit. It attests everything you accepted, agreed, noted and added; the list says exactly what, and the text is compiled from that list. Edit anything, add your own words, then sign." : "Close the review of the dictated note first; the button in the header takes you there."}</p>
      {n.manifest.length > 0 && (
        <section className="manifest">
          <h2>{signed ? "What the signature attested" : "What you are signing"}</h2>
          <div className="mgrid">
            {n.manifest.map((g) => (
              <details key={g.kind} className="mgrp">
                <summary><b>{g.count}</b> {g.label}{g.items.some((i) => i.attested === true) ? <span className="pill ok">attested</span> : null}</summary>
                <ul>{g.items.map((it) => <li key={it.id + it.text}>{it.text}</li>)}</ul>
              </details>
            ))}
          </div>
        </section>
      )}
      {doc.sections.map((s, i) => (
        <section key={i} className={`note-sec ${s.source ?? "compiled"}`}>
          <h2>{s.heading} <span className="pill">{s.source === "transcript" ? "as dictated" : s.source === "authored" ? "your words" : s.edited ? "compiled · edited" : "compiled from the record"}</span></h2>
          {signed || s.collapsed ? <p className="ro">{s.text}</p> : <textarea value={val(i)} rows={Math.max(2, Math.ceil(val(i).length / 90) + (val(i).match(/\n/g)?.length ?? 0))} onChange={(e) => setText((t) => ({ ...t, [i]: e.target.value }))} aria-label={s.heading} />}
          {s.cites.length > 0 && <div className="cites">{s.cites.slice(0, 12).map((c) => <span key={c} className="cite" title={c}>{c}</span>)}{s.cites.length > 12 && <span className="cite">+{s.cites.length - 12}</span>}</div>}
        </section>
      ))}
      {!signed && ready && (
        <section className="note-sec authored">
          <h2>In your own words <span className="pill">optional</span></h2>
          <textarea value={authored} rows={3} placeholder="Anything the record does not know: the history as you heard it, your judgment, what you told the patient." onChange={(e) => setAuthored(e.target.value)} aria-label="Your own words" />
        </section>
      )}
      {!signed && ready && <div className="addplan"><button className="btn primary" disabled={!!busy} onClick={() => run("sign", () => api.signVisitNote(pid, doc.sections.map((s, i) => ({ heading: s.heading, text: val(i) })), authored), "Visit note signed")}>Sign the visit note</button><span className="pill">one signature, on the note, attests everything in the list above</span></div>}
    </div>
  );
}
