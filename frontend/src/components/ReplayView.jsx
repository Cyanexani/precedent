import { useCallback, useEffect, useRef, useState } from "react";
import { api, day, money } from "../api.js";
import { ACTION_LABEL, Card, Chip, ErrorBox, Spinner } from "./ui.jsx";

const fmt = (v) => (v == null ? "n/a" : `${Math.round(v)}%`);

function Verdict({ arm }) {
  return (
    <span className={`verdict ${arm.agreed ? "verdict-hit" : "verdict-miss"}`}>
      <span aria-hidden="true">{arm.agreed ? "✓" : "✕"}</span>
      {arm.agreed ? "Match" : "Miss"}: {ACTION_LABEL[arm.action] || arm.action}
    </span>
  );
}

function AgreementChart({ steps, cumulative }) {
  const [hover, setHover] = useState(null);
  const wrap = useRef(null);
  const W = 720, H = 280, L = 44, R = 132, T = 24, B = 40;
  const n = cumulative.length;
  if (n === 0) return <p className="muted small">The chart fills in as the replay runs.</p>;
  const x = (i) => L + (n === 1 ? 0 : (i / (n - 1)) * (W - L - R));
  const y = (v) => T + (1 - v / 100) * (H - T - B);
  const path = (key) => cumulative.map((c, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(c[key]).toFixed(1)}`).join(" ");
  const last = cumulative[n - 1];
  const half = Math.floor(steps.length / 2);
  const series = [
    { key: "with_memory", label: "With memory", color: "var(--series-memory)" },
    { key: "without_memory", label: "Without memory", color: "var(--series-baseline)" },
  ];
  // keep the two end labels from colliding
  let yOn = y(last.with_memory), yOff = y(last.without_memory);
  if (Math.abs(yOn - yOff) < 18) {
    const mid = (yOn + yOff) / 2;
    [yOn, yOff] = last.with_memory >= last.without_memory ? [mid - 9, mid + 9] : [mid + 9, mid - 9];
  }
  const colW = n > 1 ? (W - L - R) / (n - 1) : 40;

  return (
    <div className="chart-wrap" ref={wrap}>
      <div className="legend">
        {series.map((s) => (
          <span key={s.key} className="legend-item"><span className="swatch" style={{ background: s.color }} />{s.label}</span>
        ))}
      </div>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label={`Cumulative agreement with the reviewer over ${n} invoices. With memory ends at ${fmt(last.with_memory)}, without memory at ${fmt(last.without_memory)}.`}>
        {half > 0 && n > half && (
          <g>
            <rect x={x(half) - colW / 2} y={T - 16} width={x(n - 1) - x(half) + colW / 2} height={H - T - B + 16} fill="var(--memory-50)" rx="8" />
            <text x={x(half) - colW / 2 + 8} y={T - 4} className="axis-text">Second half of the quarter</text>
          </g>
        )}
        {[0, 25, 50, 75, 100].map((v) => (
          <g key={v}>
            <line className="grid-line" x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
            <text className="axis-text" x={L - 8} y={y(v) + 4} textAnchor="end">{v}%</text>
          </g>
        ))}
        {cumulative.map((c, i) => (
          <text key={i} className="axis-text" x={x(i)} y={H - B + 18} textAnchor="middle">{i + 1}</text>
        ))}
        <text className="axis-text" x={L} y={H - 4}>Invoice number in arrival order</text>
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} stroke="var(--gray-400)" strokeWidth="1" />}
        {series.map((s) => (
          <g key={s.key}>
            <path d={path(s.key)} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
            {cumulative.map((c, i) => (
              <circle key={i} cx={x(i)} cy={y(c[s.key])} r={hover === i ? 6 : 4} fill={s.color} stroke="var(--white)" strokeWidth="2" />
            ))}
          </g>
        ))}
        <g>
          <circle cx={W - R + 12} cy={yOn} r="4" fill="var(--series-memory)" />
          <text className="end-label" x={W - R + 22} y={yOn + 4} fill="var(--gray-900)">With memory {fmt(last.with_memory)}</text>
          <circle cx={W - R + 12} cy={yOff} r="4" fill="var(--series-baseline)" />
          <text className="end-label" x={W - R + 22} y={yOff + 4} fill="var(--gray-900)">Without {fmt(last.without_memory)}</text>
        </g>
        {cumulative.map((c, i) => (
          <rect key={i} x={x(i) - colW / 2} y={T} width={colW} height={H - T - B} fill="transparent"
            onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
        ))}
      </svg>
      {hover != null && steps[hover] && (
        <div className="chart-tip" style={{ left: `min(calc(${(x(hover) / W) * 100}% + 12px), calc(100% - 240px))`, top: 40 }}>
          <strong>#{hover + 1} {steps[hover].invoice_no}</strong>
          <div className="muted">{steps[hover].vendor_name}, {day(steps[hover].arrived_on)}</div>
          <div>Reviewer decided: <strong>{ACTION_LABEL[steps[hover].recorded.decision]}</strong></div>
          <div>With memory: {ACTION_LABEL[steps[hover].with_memory.action]} {steps[hover].with_memory.agreed ? "✓" : "✕"}</div>
          <div>Without memory: {ACTION_LABEL[steps[hover].without_memory.action]} {steps[hover].without_memory.agreed ? "✓" : "✕"}</div>
          <div className="muted">Running agreement {fmt(cumulative[hover].with_memory)} vs {fmt(cumulative[hover].without_memory)}</div>
        </div>
      )}
    </div>
  );
}

export default function ReplayView({ onFinished, publicDemo }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [starting, setStarting] = useState(false);
  const wasRunning = useRef(false);

  const load = useCallback(() => {
    api.replay().then((d) => {
      setData(d);
      setError(null);
      if (wasRunning.current && d.status !== "running") onFinished?.();
      wasRunning.current = d.status === "running";
    }).catch((e) => setError(e.message));
  }, [onFinished]);

  useEffect(load, [load]);
  useEffect(() => {
    if (data?.status !== "running") return undefined;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [data?.status, load]);

  async function start() {
    setStarting(true);
    try {
      setData(await api.startReplay());
      wasRunning.current = true;
      setTimeout(load, 800);
    } catch (e) {
      setError(e.message);
    } finally {
      setStarting(false);
    }
  }

  if (error && !data) return <ErrorBox error={error} onRetry={load} />;
  if (!data) return <Spinner label="Loading the replay" />;

  const s = data.summary;
  const running = data.status === "running";
  const steps = data.steps || [];
  const pct = data.total ? Math.round((steps.length / data.total) * 100) : 0;

  return (
    <div className="layout-single">
      <section className="card replay-hero">
        <div>
          <p className="memory-kicker">Measured on live Hindsight and live model calls</p>
          <h2>Does the agent get better as memory fills up?</h2>
          <p className="muted small">
            {data.total} exceptions from July to September arrive one at a time. Before seeing each decision, the agent predicts it twice: once with
            what Hindsight has learned so far and once with no memory. Then the reviewer's recorded decision is retained, and the next invoice arrives.
          </p>
          {running ? (
            <>
              <p className="small"><Spinner label={`Replaying invoice ${Math.min(steps.length + 1, data.total)} of ${data.total}${data.current ? `, ${data.current.invoice_no}` : ""}`} /></p>
              <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${pct}%` }} /></div>
            </>
          ) : (
            <p className="tiny">
              {data.status === "done" && data.finished_at ? `Last run finished ${day(data.finished_at)} ${new Date(data.finished_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}. ` : ""}
              {data.status === "interrupted" ? "The last run was interrupted by a server restart. " : ""}
              {data.status === "error" ? `The last run failed: ${data.error}. ` : ""}
              {data.model ? `Model ${data.model}, bank ${data.bank_id}.` : "No run yet."}
            </p>
          )}
          {publicDemo ? (
            <p className="tiny">
              {data.source === "saved sample" ? "This is a saved run. " : ""}New runs are turned off on the public demo because each run makes 28 model calls. Run the app locally to replay again.
            </p>
          ) : (
            <button className="btn btn-memory mt" disabled={running || starting} onClick={start}>
              {running ? "Replay running" : starting ? "Starting" : steps.length ? "Run the replay again" : "Run the replay"}
            </button>
          )}
          <ErrorBox error={error} />
        </div>
        {s.steps_done > 0 && (
          <div className="stat stat-memory" aria-live="polite">
            <span className="small">Second half of the quarter</span>
            <span className="hero-num">{fmt(s.second_half.with_memory)}</span>
            <span className="small">agreement with memory, against {fmt(s.second_half.without_memory)} without</span>
          </div>
        )}
      </section>

      {s.steps_done > 0 && (
        <div className="stat-grid">
          <div className="stat"><span className="stat-num">{fmt(s.agreement_with_memory)}</span><span className="muted">agreed with the reviewer over the whole quarter, memory on</span></div>
          <div className="stat"><span className="stat-num">{fmt(s.agreement_without_memory)}</span><span className="muted">agreed over the whole quarter, memory off</span></div>
          <div className="stat"><span className="stat-num">{fmt(s.first_half.with_memory)} vs {fmt(s.first_half.without_memory)}</span><span className="muted">first half, when memory was nearly empty</span></div>
          <div className="stat"><span className="stat-num">{s.memory_fixed} fixed, {s.memory_broke} broken</span><span className="muted">decisions memory turned from a miss into a match, and the reverse</span></div>
          <div className="stat"><span className="stat-num">{s.steps_with_precedent} of {s.steps_done}</span><span className="muted">invoices where Hindsight returned a precedent</span></div>
        </div>
      )}

      <Card title="Agreement with the reviewer, invoice by invoice" subtitle="Running share of predictions that matched the recorded decision. Approve and approve with conditions count as the same call.">
        <AgreementChart steps={steps} cumulative={s.cumulative} />
      </Card>

      <Card title="Every prediction in the replay" subtitle="Rows in violet are where memory changed a miss into a match.">
        {steps.length === 0 ? <p className="muted">Run the replay to fill this table.</p> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>#</th><th>Arrived</th><th>Invoice</th><th>Exceptions</th><th>Reviewer decided</th><th>Without memory</th><th>With memory</th><th>Recalled from Hindsight</th></tr>
              </thead>
              <tbody>
                {steps.map((st) => (
                  <tr key={st.n} className={st.with_memory.agreed && !st.without_memory.agreed ? "step-row-fixed" : ""}>
                    <td>{st.n}</td>
                    <td style={{ whiteSpace: "nowrap" }}>{day(st.arrived_on)}</td>
                    <td><span className="mono">{st.invoice_no}</span><div className="muted small">{st.vendor_name}, {money(st.total)}</div></td>
                    <td>{st.exception_codes.map((c) => <Chip key={c} tone="neutral">{c}</Chip>)}</td>
                    <td><strong>{ACTION_LABEL[st.recorded.decision]}</strong><div className="replay-reason">{st.recorded.reviewer}: {st.recorded.reason}</div></td>
                    <td><Verdict arm={st.without_memory} /><div className="replay-reason">{st.without_memory.reason}</div></td>
                    <td><Verdict arm={st.with_memory} /><div className="replay-reason">{st.with_memory.reason}</div></td>
                    <td>
                      {st.memory.precedents.length === 0 ? <span className="muted small">Nothing yet</span> :
                        st.memory.precedents.map((p) => <div key={p.case_id} className="small"><span className="mono">{p.case_id}</span> <span className="muted">{p.relation}</span></div>)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
