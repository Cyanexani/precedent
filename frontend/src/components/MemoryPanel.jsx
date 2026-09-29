import { useState } from "react";
import { api, day, money } from "../api.js";
import { ACTION_LABEL, Chip } from "./ui.jsx";

const STATUS_TEXT = {
  none: "No relevant precedent in memory",
  single: "1 precedent recalled",
  multiple: (n) => `${n} precedents recalled`,
};

function CaseCard({ c }) {
  return (
    <div className="case-card">
      <div className="case-top">
        <span className="mono case-id">{c.case_id}</span>
        <Chip tone={c.relation === "same_vendor_same_issue" ? "memory" : "memory-soft"}>{c.relation_label}</Chip>
      </div>
      <p className="case-line">
        <strong>{c.vendor_name}</strong>, invoice <span className="mono">{c.invoice_no}</span>
        {c.total ? <> for {money(c.total)}</> : null}
      </p>
      <p className="case-line small">
        Decision <Chip tone={c.decision === "reject" ? "bad" : c.decision === "hold" ? "warn" : "ok"}>{ACTION_LABEL[c.decision] || c.decision}</Chip>{" "}
        by {c.reviewer} on {day(c.resolved_on)}
      </p>
      <ul className="facts">
        {c.facts.slice(0, 4).map((f, i) => <li key={i}>{f}</li>)}
      </ul>
      <p className="muted tiny">Matched by {c.matched_by.join(" and ")} tag. Shared exceptions: {c.shared_codes?.join(", ") || "none"}.</p>
    </div>
  );
}

export default function MemoryPanel({ memory, vendorId, loading }) {
  const [showRaw, setShowRaw] = useState(false);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState(null);

  async function ask(e) {
    e.preventDefault();
    if (question.trim().length < 5) return;
    setAsking(true);
    setAskError(null);
    try {
      setAnswer(await api.ask(question.trim(), vendorId));
    } catch (err) {
      setAskError(err.message);
    } finally {
      setAsking(false);
    }
  }

  let body;
  if (loading) {
    body = <p className="muted">Searching Hindsight for similar resolved cases…</p>;
  } else if (!memory) {
    body = <p className="muted">Run an analysis to search the team's memory for similar cases.</p>;
  } else if (!memory.enabled) {
    body = <p className="muted">Memory was switched off for this run. The agent saw no past cases.</p>;
  } else if (memory.status === "error") {
    body = <p className="error-text">Hindsight recall failed: {memory.error}</p>;
  } else {
    body = (
      <>
        {memory.precedents.length === 0 && (
          <p className="no-precedent">
            Hindsight returned {memory.raw_result_count} memor{memory.raw_result_count === 1 ? "y" : "ies"}, none of which is a
            resolved case for this vendor or these exception types. The agent was told there is no precedent.
          </p>
        )}
        {memory.precedents.map((c) => <CaseCard key={c.case_id} c={c} />)}
        {memory.vendor_context.length > 0 && (
          <>
            <p className="eyebrow mt">Same vendor, other exceptions</p>
            {memory.vendor_context.map((c) => <CaseCard key={c.case_id} c={c} />)}
          </>
        )}
        {memory.patterns.length > 0 && (
          <>
            <p className="eyebrow mt">Patterns Hindsight has consolidated</p>
            <ul className="facts">{memory.patterns.map((p) => <li key={p.id}>{p.text}</li>)}</ul>
          </>
        )}
        <button className="link-btn" onClick={() => setShowRaw(!showRaw)}>
          {showRaw ? "Hide" : "Show"} what was sent to Hindsight
        </button>
        {showRaw && (
          <div className="raw">
            <p><strong>Query:</strong> {memory.query}</p>
            <p><strong>Passes:</strong> {memory.passes.map((p) => `${p.name} [${p.tags.join(", ")}]`).join("; ")}</p>
            <p><strong>Retrieved:</strong> {memory.raw_result_count} memory units in {memory.elapsed_ms} ms, bank <span className="mono">{memory.bank_id}</span></p>
            {memory.gated_out.length > 0 && (
              <p><strong>Filtered out:</strong> {memory.gated_out.map((g) => `${g.case_id} (${g.gate_reason})`).join("; ")}</p>
            )}
          </div>
        )}
      </>
    );
  }

  const badge = memory?.enabled && memory.status !== "error" && !loading
    ? memory.status === "multiple" ? STATUS_TEXT.multiple(memory.precedent_count) : STATUS_TEXT[memory.status]
    : null;

  return (
    <section className="card memory-card">
      <header className="card-head">
        <div>
          <p className="memory-kicker">Recalled from Hindsight</p>
          <h3>Team memory</h3>
        </div>
        {badge && <Chip tone={memory.status === "none" ? "neutral" : "memory"}>{badge}</Chip>}
      </header>
      {body}
      <form className="ask" onSubmit={ask}>
        <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask the team memory, e.g. what do we know about this vendor?" maxLength={500} />
        <button className="btn btn-memory btn-sm" disabled={asking || question.trim().length < 5}>{asking ? "Thinking…" : "Ask"}</button>
      </form>
      {askError && <p className="error-text small">{askError}</p>}
      {answer && <div className="reflect-answer"><p className="eyebrow">Hindsight reflect</p><p>{answer.answer}</p></div>}
    </section>
  );
}
