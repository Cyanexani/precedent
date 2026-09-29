import { useState } from "react";
import { ActionChip, Card, Chip, PRECEDENT_LABEL } from "./ui.jsx";

const PRECEDENT_TONE = { none: "neutral", applies: "memory", partially_applies: "memory-soft", does_not_apply: "warn", mixed: "memory-soft" };

export default function AgentPanel({ result }) {
  const [showTrace, setShowTrace] = useState(false);
  const [checked, setChecked] = useState({});
  if (!result) return null;
  const a = result.agent;
  const usedMemory = result.use_memory && result.memory?.precedent_count > 0;

  return (
    <Card title="Agent analysis" subtitle={`${result.llm.model}, ${(result.elapsed_ms / 1000).toFixed(1)} s${result.use_memory ? "" : ", memory off"}`}
      right={<ActionChip action={a.recommendation?.action} big />}>
      <p className="headline">{a.headline}</p>
      <p>{a.explanation}</p>

      <div className={`precedent-box ${usedMemory ? "precedent-used" : ""}`}>
        <div className="finding-top">
          <Chip tone={PRECEDENT_TONE[a.precedent?.status] || "neutral"}>{PRECEDENT_LABEL[a.precedent?.status] || a.precedent?.status}</Chip>
          {usedMemory && <span className="memory-kicker">Hindsight influenced this answer</span>}
        </div>
        <p>{a.precedent?.summary}</p>
        {a.precedent?.cases?.map((c) => (
          <p key={c.case_id} className="small">
            <span className="mono">{c.case_id}</span> <Chip tone={c.applies ? "ok" : "warn"}>{c.applies ? "applies" : "does not apply"}</Chip> {c.why}
          </p>
        ))}
      </div>

      <div className="rec-box">
        <p className="eyebrow">Recommendation</p>
        <p>{a.recommendation?.rationale}</p>
        {a.recommendation?.conditions?.length > 0 && (
          <ul className="plain-list">{a.recommendation.conditions.map((c, i) => <li key={i}>{c}</li>)}</ul>
        )}
      </div>

      {a.checklist?.length > 0 && (
        <>
          <p className="eyebrow mt">Verification checklist</p>
          <ul className="checklist">
            {a.checklist.map((c, i) => (
              <li key={i}>
                <label>
                  <input type="checkbox" checked={!!checked[i]} onChange={() => setChecked({ ...checked, [i]: !checked[i] })} /> {c}
                </label>
              </li>
            ))}
          </ul>
        </>
      )}

      <p className={`influence ${usedMemory ? "influence-on" : ""}`}>{a.memory_influence}</p>

      {result.guardrail_warnings?.length > 0 && (
        <div className="guardrail">
          <strong>Guardrail:</strong> {result.guardrail_warnings.join(" ")}
        </div>
      )}
      {result.llm.fallback && <div className="guardrail"><strong>Fallback:</strong> {result.llm.fallback}</div>}

      <button className="link-btn" onClick={() => setShowTrace(!showTrace)}>{showTrace ? "Hide" : "Show"} tool calls ({result.trace.length})</button>
      {showTrace && (
        <ol className="trace">
          {result.trace.map((t, i) => (
            <li key={i}>
              <span className="mono">{t.tool}</span> <Chip tone={t.by === "llm" ? "info" : "neutral"}>{t.by === "llm" ? "called by agent" : "pipeline"}</Chip>
              <span className="muted small"> {t.summary}</span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

export function CompareView({ data }) {
  if (!data) return null;
  const cols = [
    { key: "without_memory", label: "Without memory", r: data.without_memory },
    { key: "with_memory", label: "With Hindsight memory", r: data.with_memory },
  ];
  return (
    <section className="compare">
      {cols.map(({ key, label, r }) => (
        <div key={key} className={`card compare-col ${key === "with_memory" ? "memory-card" : ""}`}>
          <p className={key === "with_memory" ? "memory-kicker" : "eyebrow"}>{label}</p>
          <ActionChip action={r.agent.recommendation?.action} big />
          <p className="headline">{r.agent.headline}</p>
          <p className="small"><strong>{PRECEDENT_LABEL[r.agent.precedent?.status]}.</strong> {r.agent.precedent?.summary}</p>
          <p className="small">{r.agent.recommendation?.rationale}</p>
          <p className="muted small">
            {r.use_memory ? `${r.memory.precedent_count} precedent(s) recalled from ${r.memory.raw_result_count} memories.` : "No memory lookup."}
          </p>
        </div>
      ))}
    </section>
  );
}
