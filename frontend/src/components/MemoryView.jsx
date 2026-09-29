import { useCallback, useEffect, useState } from "react";
import { api, day } from "../api.js";
import { ACTION_LABEL, Card, Chip, ErrorBox, Spinner } from "./ui.jsx";

function Markdownish({ text }) {
  if (!text) return <p className="muted">Hindsight has not written this yet.</p>;
  const inline = (line) =>
    line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part
    );
  const out = [];
  let list = [];
  const flush = () => {
    if (list.length) out.push(<ul key={`ul${out.length}`} className="plain-list">{list}</ul>);
    list = [];
  };
  text.split("\n").forEach((raw, i) => {
    const line = raw.trim();
    if (!line) return flush();
    if (/^#{1,6}\s/.test(line)) {
      flush();
      const level = line.match(/^#+/)[0].length;
      out.push(level <= 2 ? <h4 key={i} className="md-h">{inline(line.replace(/^#+\s/, ""))}</h4>
        : <h5 key={i} className="md-h5">{inline(line.replace(/^#+\s/, ""))}</h5>);
    } else if (/^([-*]|\d+\.)\s/.test(line)) {
      list.push(<li key={i}>{inline(line.replace(/^([-*]|\d+\.)\s/, ""))}</li>);
    } else if (/^\|/.test(line)) {
      flush();
      if (!/^\|[\s:-]+\|/.test(line)) out.push(<p key={i} className="md-row">{inline(line.replace(/^\||\|$/g, "").split("|").map((c) => c.trim()).join("  •  "))}</p>);
    } else {
      flush();
      out.push(<p key={i}>{inline(line)}</p>);
    }
  });
  flush();
  return <div className="md">{out}</div>;
}

function Metrics({ metrics }) {
  if (!metrics) return null;
  const tl = metrics.timeline;
  const max = Math.max(1, ...tl.map((t) => t.precedent_count + t.notes_count));
  const pct = (v) => (v == null ? "n/a" : `${v}%`);
  return (
    <Card title="Is the agent getting better?" subtitle="Live counters from this server session. Nothing here is estimated.">
      <div className="stat-grid">
        <div className="stat"><span className="stat-num">{metrics.analyses}</span><span className="muted small">analyses run</span></div>
        <div className="stat"><span className="stat-num">{metrics.runs_with_precedent} of {metrics.memory_runs}</span><span className="muted small">memory runs found a precedent</span></div>
        <div className="stat"><span className="stat-num">{metrics.precedents_ruled_out}</span><span className="muted small">precedents ruled out as not applicable</span></div>
        <div className="stat"><span className="stat-num">{metrics.resolutions_retained}</span><span className="muted small">human resolutions retained</span></div>
        <div className="stat stat-memory">
          <span className="stat-num">{pct(metrics.agreement_with_memory)}</span>
          <span className="small">reviewer agreed with the agent, memory on ({metrics.agreement_samples.with_memory} decisions)</span>
        </div>
        <div className="stat">
          <span className="stat-num">{pct(metrics.agreement_without_memory)}</span>
          <span className="muted small">reviewer agreed with the agent, memory off ({metrics.agreement_samples.without_memory} decisions)</span>
        </div>
      </div>
      <p className="eyebrow mt">Memories used per analysis, in order</p>
      {tl.length === 0 ? (
        <p className="muted small">Run a few analyses on the desk to see this fill in.</p>
      ) : (
        <div className="timeline" role="img" aria-label="Memories recalled per analysis over time">
          {tl.map((t) => (
            <div key={t.n} className="tl-col" title={`#${t.n} ${t.invoice_id}: ${t.precedent_count} precedents, ${t.notes_count} notes${t.use_memory ? "" : " (memory off)"}`}>
              <div className={`tl-bar ${t.use_memory ? "" : "tl-off"}`} style={{ height: `${Math.max(4, ((t.precedent_count + t.notes_count) / max) * 100)}%` }} />
            </div>
          ))}
        </div>
      )}
      <p className="muted tiny">Violet bars are memory-on runs, grey bars are memory-off runs. Taller means more relevant memories were recalled.</p>
    </Card>
  );
}

function Playbook() {
  const [models, setModels] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState("ap-playbook");

  const load = useCallback(() => {
    setError(null);
    api.playbook().then(setModels).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  async function refresh() {
    setBusy(true);
    try {
      await api.refreshPlaybook();
      setTimeout(load, 6000);
      setTimeout(() => setBusy(false), 6000);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <Card title="Playbook written by Hindsight" subtitle="Hindsight mental models. They rewrite themselves after new resolutions are consolidated."
      right={<button className="btn btn-ghost btn-sm" disabled={busy} onClick={refresh}>{busy ? "Refreshing" : "Refresh now"}</button>}
      className="memory-card">
      <ErrorBox error={error} onRetry={load} />
      {!models && !error && <Spinner label="Loading mental models" />}
      {models?.map((m) => (
        <div key={m.id} className="mm">
          <button className="mm-head" onClick={() => setOpen(open === m.id ? null : m.id)}>
            <strong>{m.name}</strong>
            <span className="muted small">{m.last_refreshed_at ? `updated ${day(m.last_refreshed_at)} ${new Date(m.last_refreshed_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}` : "not generated yet"}</span>
          </button>
          {open === m.id && <Markdownish text={m.content} />}
        </div>
      ))}
    </Card>
  );
}

function TeachMemory({ vendors, reviewer, onSaved }) {
  const [kind, setKind] = useState("vendor_note");
  const [vendorId, setVendorId] = useState("");
  const [forReviewer, setForReviewer] = useState(reviewer || "");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(null);

  useEffect(() => setForReviewer(reviewer || ""), [reviewer]);

  const valid = text.trim().length >= 15 && (kind !== "vendor_note" || vendorId) && (kind !== "reviewer_preference" || forReviewer.trim());

  async function submit(e) {
    e.preventDefault();
    if (!valid) return;
    setSaving(true);
    setError(null);
    try {
      const r = await api.addNote({ kind, text: text.trim(), author: reviewer || "AP team", vendor_id: vendorId || null, reviewer: forReviewer || null });
      setSaved(r);
      setText("");
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="Teach the memory" subtitle="Vendor emails, reviewer habits and team policies. The agent recalls them next to past cases.">
      <form className="resolve-form" onSubmit={submit}>
        <div className="decisions">
          {[["vendor_note", "Vendor communication"], ["reviewer_preference", "Reviewer preference"], ["policy", "Team policy"]].map(([k, l]) => (
            <button type="button" key={k} className={`decision ${kind === k ? "active decision-memory" : ""}`} onClick={() => setKind(k)}>{l}</button>
          ))}
        </div>
        {kind === "vendor_note" && (
          <label>Vendor
            <select value={vendorId} onChange={(e) => setVendorId(e.target.value)}>
              <option value="">Choose a vendor</option>
              {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </label>
        )}
        {kind === "reviewer_preference" && (
          <label>Reviewer<input value={forReviewer} onChange={(e) => setForReviewer(e.target.value)} maxLength={60} /></label>
        )}
        <label>What should the agent remember?
          <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} maxLength={2000}
            placeholder={kind === "vendor_note" ? "e.g. Vendor emailed that freight will be billed on a separate invoice from October."
              : kind === "reviewer_preference" ? "e.g. Always quote the GRN number in approval notes."
                : "e.g. Invoices above Rs 5 lakh go into the weekly CFO batch."} />
        </label>
        {error && <p className="error-text">{error}</p>}
        <button className="btn btn-memory" disabled={saving || !valid}>{saving ? "Saving to Hindsight" : "Save to memory"}</button>
        {saved && <p className="small memory-kicker">Saved as {saved.note_id} in {(saved.elapsed_ms / 1000).toFixed(1)} s.</p>}
      </form>
    </Card>
  );
}

function Ledger({ rows, onForget, loading, error, onRetry, canForget }) {
  return (
    <Card title="What the agent remembers" subtitle="Every document in the Hindsight bank. Forgetting one deletes it and every fact extracted from it.">
      <ErrorBox error={error} onRetry={onRetry} />
      {loading && <Spinner label="Reading the bank" />}
      {rows && rows.length === 0 && <p className="muted">The bank is empty. Resolve an invoice or load team history.</p>}
      {rows && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Memory</th><th>Type</th><th>Vendor</th><th>Decision</th><th>Reviewer</th><th className="num">Facts</th><th>Updated</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="mono small">{r.id}</td>
                  <td><Chip tone={r.kind === "case" ? "memory-soft" : "info"}>{r.kind_label}</Chip></td>
                  <td className="small">{r.vendor_id || ""}</td>
                  <td className="small">{r.decision ? ACTION_LABEL[r.decision] || r.decision : ""}</td>
                  <td className="small">{r.reviewer ? r.reviewer.replace(/-/g, " ") : ""}</td>
                  <td className="num">{r.memory_units}</td>
                  <td className="small">{day(r.updated_at)}</td>
                  <td>{canForget && <button className="link-btn danger" onClick={() => onForget(r.id)}>Forget</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export default function MemoryView({ reviewer, vendors, onMemoryChanged, publicDemo }) {
  const [metrics, setMetrics] = useState(null);
  const [rows, setRows] = useState(null);
  const [ledgerError, setLedgerError] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadAll = useCallback(() => {
    setLoading(true);
    setLedgerError(null);
    api.metrics().then(setMetrics).catch(() => {});
    api.ledger().then(setRows).catch((e) => setLedgerError(e.message)).finally(() => setLoading(false));
  }, []);
  useEffect(loadAll, [loadAll]);

  async function forget(id) {
    if (!window.confirm(`Forget ${id}? Hindsight deletes the document and every fact extracted from it.`)) return;
    try {
      await api.forget(id);
      loadAll();
      onMemoryChanged();
    } catch (e) {
      setLedgerError(e.message);
    }
  }

  return (
    <div className="memory-view">
      <Metrics metrics={metrics} />
      <div className="grid">
        <div className="col">
          <Playbook />
          <TeachMemory vendors={vendors} reviewer={reviewer} onSaved={() => { loadAll(); onMemoryChanged(); }} />
        </div>
        <div className="col">
          <Ledger rows={rows} onForget={forget} loading={loading && !rows} error={ledgerError} onRetry={loadAll} canForget={!publicDemo} />
        </div>
      </div>
    </div>
  );
}
