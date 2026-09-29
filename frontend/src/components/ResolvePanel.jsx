import { useEffect, useState } from "react";
import { api } from "../api.js";
import { ACTION_LABEL, Card, Chip } from "./ui.jsx";

const DECISIONS = ["approve", "approve_with_conditions", "hold", "reject"];

const EVIDENCE_BY_CODE = {
  AMOUNT_SPIKE: ["PO amendment verified with procurement", "GRN quantity matches invoice"],
  AMOUNT_LOW: ["Partial delivery confirmed with stores"],
  PRICE_VARIANCE: ["Rate contract clause checked", "Procurement confirmed revised rate"],
  QTY_EXCEEDS_PO: ["Checked PO for amendments", "Asked vendor for revised invoice"],
  QTY_EXCEEDS_RECEIPT: ["Stores confirmed quantity received"],
  DUPLICATE_SUSPECTED: ["Original payment UTR confirmed", "Vendor confirmed resubmission"],
  GST_MISMATCH: ["Place of supply checked", "Credit note requested"],
  MISSING_PO: ["Cost centre owner approved in writing", "Retro PO requested"],
  BANK_DETAILS_CHANGED: ["Called vendor on master phone number", "Email headers checked"],
  NEW_VENDOR: ["Vendor KYC checked"],
  MSME_45_DAY_BREACH: ["Payment scheduled within 45 days"],
  APPROVAL_CFO: ["CFO approval obtained"],
};

export default function ResolvePanel({ invoiceId, checks, onResolved, existing }) {
  const [decision, setDecision] = useState("approve");
  const [reviewer, setReviewer] = useState(() => {
    try { return localStorage.getItem("precedent.reviewer") || ""; } catch { return ""; }
  });
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState([]);
  const [extraEvidence, setExtraEvidence] = useState("");
  const [conditions, setConditions] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(existing || null);

  useEffect(() => {
    setDone(existing || null);
    setReason("");
    setEvidence([]);
    setConditions("");
    setError(null);
  }, [invoiceId]);

  const suggestions = [...new Set(checks.exception_codes.flatMap((c) => EVIDENCE_BY_CODE[c] || []))];
  const reasonOk = reason.trim().length >= 15;
  const reviewerOk = reviewer.trim().length >= 2;

  async function submit(e) {
    e.preventDefault();
    if (!reasonOk || !reviewerOk) return;
    setSaving(true);
    setError(null);
    try {
      try { localStorage.setItem("precedent.reviewer", reviewer.trim()); } catch {}
      const res = await api.resolve(invoiceId, {
        decision,
        reviewer: reviewer.trim(),
        reason: reason.trim(),
        evidence: [...evidence, ...extraEvidence.split("\n")].filter((s) => s.trim()),
        conditions: conditions.split("\n").filter((s) => s.trim()),
      });
      setDone(res);
      onResolved(invoiceId, res);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  if (done) {
    return (
      <Card title="Human resolution" className="memory-card">
        <p className="memory-kicker">Retained in Hindsight</p>
        <p>
          <Chip tone="ok">{ACTION_LABEL[done.decision]}</Chip> by {done.reviewer}. Saved as case <span className="mono">{done.case_id}</span>
          {done.memory?.elapsed_ms ? ` in ${(done.memory.elapsed_ms / 1000).toFixed(1)} s` : ""}.
        </p>
        <p className="muted small">Future invoices with the same vendor or exception type will recall this case.</p>
        {done.memory?.tags && <p className="small">Tags: {done.memory.tags.map((t) => <Chip key={t} tone="memory-soft">{t}</Chip>)}</p>}
        {done.memory?.content && (
          <details className="small">
            <summary>What was sent to Hindsight</summary>
            <pre className="retained">{done.memory.content}</pre>
          </details>
        )}
        <button className="btn btn-ghost btn-sm" onClick={() => setDone(null)}>Record a revised resolution</button>
      </Card>
    );
  }

  return (
    <Card title="Human resolution" subtitle="Your decision is stored in Hindsight so the agent can recall it on similar invoices.">
      <form onSubmit={submit} className="resolve-form">
        <div className="decisions">
          {DECISIONS.map((d) => (
            <button type="button" key={d} className={`decision ${decision === d ? `active decision-${d}` : ""}`} onClick={() => setDecision(d)}>
              {ACTION_LABEL[d]}
            </button>
          ))}
        </div>
        <label>
          Reviewer
          <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Your name" maxLength={60} />
        </label>
        <label>
          Reason
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={4} maxLength={2000}
            placeholder="Why is this invoice legitimate, or why not? Mention the evidence that decided it." />
          {!reasonOk && reason.length > 0 && <span className="hint">At least 15 characters, so the memory is useful later.</span>}
        </label>
        {suggestions.length > 0 && (
          <fieldset>
            <legend>Evidence checked</legend>
            {suggestions.map((s) => (
              <label key={s} className="check">
                <input type="checkbox" checked={evidence.includes(s)}
                  onChange={() => setEvidence(evidence.includes(s) ? evidence.filter((x) => x !== s) : [...evidence, s])} /> {s}
              </label>
            ))}
          </fieldset>
        )}
        <label>
          Other evidence (one per line)
          <textarea value={extraEvidence} onChange={(e) => setExtraEvidence(e.target.value)} rows={2} />
        </label>
        {decision === "approve_with_conditions" && (
          <label>
            Conditions (one per line)
            <textarea value={conditions} onChange={(e) => setConditions(e.target.value)} rows={2} />
          </label>
        )}
        {error && <p className="error-text">{error}</p>}
        <button className="btn btn-primary" disabled={saving || !reasonOk || !reviewerOk}>
          {saving ? "Saving to Hindsight…" : "Resolve and save to memory"}
        </button>
      </form>
    </Card>
  );
}
