type Props = { onClose: () => void };

/** The record explained once, in one place: four layers, one write path, the rules that cannot be turned off.
 *  Content follows the CPOR architecture page in the NDE documentation set. */
export default function About({ onClose }: Props) {
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal wide about" onClick={(e) => e.stopPropagation()}>
        <h3>The compiled problem-oriented record</h3>
        <div className="meta">Facts are recorded. Clinical state is maintained and signed. Context and documents are compiled. Actions pass through explicit authority.</div>

        <div className="layer">
          <div className="lh"><span className="tag">Capture</span><span className="lt">Where information arrives</span></div>
          <p>Labs and vitals, orders and medications, outside records, typed entry, and the visit note or transcript. Every source does one job, faithful translation into a dated fact. Interpretation happens strictly downstream. In this demo the note is the source that arrives live; everything else was imported.</p>
        </div>
        <div className="flow">↓ every source writes to one place</div>
        <div className="layer">
          <div className="lh"><span className="tag">Layer 1</span><span className="lt">The record of what happened</span></div>
          <p>Append-only, signed, with provenance on every entry: which note, which quote, which model, who signed and when. Nothing is edited; a correction is a new entry. The <b>record</b> under a note is this layer read back for that note. The full event ledger with two dates per entry is the next substrate step (PRD-01); today its content is folded from the stamps every item already carries.</p>
        </div>
        <div className="flow">↓ maintained incrementally · rebuilt whenever interpretation changes</div>
        <div className="layer open">
          <div className="lh"><span className="tag">Layer 2</span><span className="lt">The problem graph: what we currently believe</span></div>
          <p>Problems and concerns with a lifecycle state, a certainty, one responsible clinician, linked findings, a monitoring plan and a summary at three depths. Relationships are data: <i>treats</i>, <i>suspected cause of</i>, <i>evidence for</i>, <i>monitors</i>. The system proposes every change to this layer; a clinician signs it. That is the <b>clinical diff</b>: what the system saw, what it concluded, how sure it is, each part separately acceptable. Merges are never automatic.</p>
        </div>
        <div className="flow">↓ compiled on demand, per reader and per purpose</div>
        <div className="layer">
          <div className="lh"><span className="tag">Layer 3</span><span className="lt">Compiled views and documents</span></div>
          <p>Nobody has to write documents; they are compiled from signed state and cite every line: the overview, the problem card, the referral letter, the orders, the visit coding. A compiled view holds no state of its own and can be thrown away and rebuilt. <b>The compiled summary is not the patient model.</b> Authored narrative stays a first-class input: the assessment you write is a fact about the patient, not a gap in the model.</p>
        </div>

        <h4>Rules that cannot be turned off</h4>
        <ol className="rules">
          <li>Merges are never automatic. A wrong merge is the one mistake the system cannot catch on its own.</li>
          <li>When the system cannot tell where something belongs, it files it separately and asks rather than guessing quietly.</li>
          <li>Nothing unsigned can support a bill or a referral.</li>
          <li>A summary sentence that cannot be traced to a dated finding is rejected and never saved.</li>
          <li>When review queues run long, the system suggests less. The queue is never allowed to simply grow.</li>
          <li>You write the assessment yourself at new problems, changed diagnoses and closures.</li>
          <li>Nothing writes except an authority-scoped verb, whoever or whatever is calling it. Reasoning proposes; only authority acts.</li>
          <li>External evidence never becomes patient truth. A guideline can be cited by a belief; it cannot be stored as one.</li>
        </ol>

        <h4>How to read the screens</h4>
        <p><b>Pencil</b> (dashed, amber) is proposed and waits for a signature. <b>Ink</b> is on the chart. <b>Mono</b> type is a recorded value. <b>Serif</b> is prose a clinician wrote. <span className="v for">+</span> stands for a finding, <span className="v against">−</span> against, <span className="v unx">○</span> for one the current story cannot explain. The button in the patient header is always the next thing owed; when it says nothing is owed, nothing is.</p>
        <p className="meta">Demo: the Claude calls replay recorded responses unless the Demo menu is set to live. Reset restores the chart to its server-start state.</p>

        <div className="row"><span className="spacer" /><button className="btn ghost" onClick={onClose}>Close</button></div>
      </div>
    </div>
  );
}
