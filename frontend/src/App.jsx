import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import InvoiceQueue from "./components/InvoiceQueue.jsx";
import { Findings, InvoiceHeader, POComparison, VendorAndApproval } from "./components/ChecksView.jsx";
import MemoryPanel from "./components/MemoryPanel.jsx";
import AgentPanel, { CompareView } from "./components/AgentPanel.jsx";
import ResolvePanel from "./components/ResolvePanel.jsx";
import MemoryView from "./components/MemoryView.jsx";
import ReplayView from "./components/ReplayView.jsx";
import { ErrorBox, Spinner } from "./components/ui.jsx";

const REVIEWERS = ["Priya Nair", "Arjun Menon"];

const VIEWS = {
  desk: { nav: "Exception desk", title: "Exception desk", sub: "Invoices waiting for review. Rule checks run in code, the agent explains them, and Hindsight recalls how the team handled similar cases." },
  replay: { nav: "Quarter replay", title: "Quarter replay", sub: "A measured learning curve: the same agent with and without memory, predicting 14 real decisions in order." },
  memory: { nav: "Memory and learning", title: "Memory and learning", sub: "What the agent remembers, the playbook Hindsight wrote from it, and how this session is going." },
};

function SetupScreen({ config }) {
  return (
    <div className="setup">
      <h1>Precedent needs its keys</h1>
      <p>This deployment has not been configured yet. Keys belong to the deployment, and everyone using it shares one Hindsight memory bank.</p>
      <p>Missing: {config.missing.map((m) => <code key={m}>{m}</code>)}</p>
      <ol>
        <li>Copy <code>.env.example</code> to <code>.env</code> in the project root, or set the same variables in your host's environment settings.</li>
        <li>Add a Groq API key and a Hindsight Cloud API key.</li>
        <li>Restart the backend.</li>
      </ol>
    </div>
  );
}

export default function App() {
  const [config, setConfig] = useState(null);
  const [invoices, setInvoices] = useState([]);
  const [bootError, setBootError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [checks, setChecks] = useState(null);
  const [checksError, setChecksError] = useState(null);
  const [result, setResult] = useState(null);
  const [compare, setCompare] = useState(null);
  const [running, setRunning] = useState(null);
  const [runError, setRunError] = useState(null);
  const [resolutions, setResolutions] = useState({});
  const [stats, setStats] = useState(null);
  const [memBusy, setMemBusy] = useState(null);
  const [memMsg, setMemMsg] = useState(null);
  const [view, setView] = useState(() => {
    const fromHash = window.location.hash.replace("#", "");
    if (VIEWS[fromHash]) return fromHash;
    try { return localStorage.getItem("precedent.view") || "desk"; } catch { return "desk"; }
  });
  const [reviewer, setReviewer] = useState(() => {
    try { return localStorage.getItem("precedent.reviewer") || REVIEWERS[0]; } catch { return REVIEWERS[0]; }
  });
  const [vendors, setVendors] = useState([]);
  const [triage, setTriage] = useState(null);
  const [triaging, setTriaging] = useState(false);
  const [ledgerIds, setLedgerIds] = useState(new Set());
  const [memoryVersion, setMemoryVersion] = useState(0);

  useEffect(() => {
    try { localStorage.setItem("precedent.reviewer", reviewer); } catch {}
  }, [reviewer]);
  useEffect(() => {
    try { localStorage.setItem("precedent.view", view); } catch {}
    if (window.location.hash !== `#${view}`) window.history.replaceState(null, "", `#${view}`);
  }, [view]);

  const refreshStats = useCallback(() => {
    api.memoryStats().then(setStats).catch(() => setStats(null));
  }, []);

  const refreshLedger = useCallback(() => {
    api.ledger().then((rows) => setLedgerIds(new Set(rows.map((r) => r.id)))).catch(() => {});
  }, []);

  const memoryChanged = useCallback(() => {
    refreshStats();
    refreshLedger();
    setTriage(null);
    setMemoryVersion((v) => v + 1);
  }, [refreshStats, refreshLedger]);

  const boot = useCallback(async () => {
    setBootError(null);
    try {
      const cfg = await api.config();
      setConfig(cfg);
      if (!cfg.configured) return;
      const list = await api.invoices();
      setInvoices(list);
      setSelectedId((cur) => cur || list[0]?.id);
      refreshStats();
      refreshLedger();
      api.vendors().then(setVendors).catch(() => {});
    } catch (e) {
      setBootError(e.message);
    }
  }, [refreshStats, refreshLedger]);

  useEffect(() => { boot(); }, [boot]);

  useEffect(() => {
    if (!selectedId) return;
    setChecks(null);
    setChecksError(null);
    setResult(null);
    setCompare(null);
    setRunError(null);
    api.invoice(selectedId).then(setChecks).catch((e) => setChecksError(e.message));
  }, [selectedId]);

  async function runTriage() {
    setTriaging(true);
    try {
      setTriage(await api.triage());
    } catch (e) {
      setMemMsg(e.message);
    } finally {
      setTriaging(false);
    }
  }

  async function run(mode) {
    setRunning(mode);
    setRunError(null);
    setCompare(null);
    try {
      if (mode === "compare") {
        const data = await api.compare(selectedId, reviewer);
        setCompare(data);
        setResult(data.with_memory);
      } else {
        setResult(await api.analyze(selectedId, mode === "memory", reviewer));
      }
    } catch (e) {
      setRunError(e.message);
    } finally {
      setRunning(null);
    }
  }

  function onResolved(id, res) {
    setResolutions((r) => ({ ...r, [id]: res }));
    memoryChanged();
  }

  async function memoryAction(kind) {
    if (kind === "reset" && !window.confirm("Delete every memory in this Hindsight bank? This cannot be undone.")) return;
    setMemBusy(kind);
    setMemMsg(null);
    try {
      if (kind === "seed") {
        const r = await api.seedHistory();
        setMemMsg(`Loaded ${r.retained.length} past cases and team notes into Hindsight in ${(r.elapsed_ms / 1000).toFixed(1)} s.`);
      } else {
        await api.resetMemory();
        setResolutions({});
        setInvoices((list) => list.map((i) => ({ ...i, resolution: null })));
        setResult(null);
        setCompare(null);
        setMemMsg("Memory bank cleared.");
      }
      memoryChanged();
    } catch (e) {
      setMemMsg(e.message);
    } finally {
      setMemBusy(null);
    }
  }

  if (bootError) return <div className="boot"><ErrorBox error={bootError} onRetry={boot} /></div>;
  if (!config) return <div className="boot"><Spinner label="Connecting to the Precedent server" /></div>;
  if (!config.configured) return <SetupScreen config={config} />;

  const existing = resolutions[selectedId] || checks?.resolution || null;
  const page = VIEWS[view] || VIEWS.desk;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="logo" aria-hidden="true">P</span>
          <div>
            <div className="brand-name">Precedent</div>
            <div className="brand-sub">AP exception desk for {config.company.name}</div>
          </div>
        </div>
        <nav className="nav" aria-label="Main">
          {Object.entries(VIEWS).map(([key, v]) => (
            <button key={key} className={`nav-item ${view === key ? "active" : ""}`} aria-current={view === key ? "page" : undefined}
              onClick={() => setView(key)}>{v.nav}</button>
          ))}
        </nav>
        <div className="side-block">
          <label className="side-label" htmlFor="reviewer-select">Reviewing as</label>
          <select id="reviewer-select" className="side-select" value={reviewer} onChange={(e) => setReviewer(e.target.value)}>
            {REVIEWERS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div className="side-spacer" />
        <div className="side-block">
          <div className="bank-card" title={config.hindsight_base_url}>
            <span className="bank-line"><span className="dot" />Hindsight memory</span>
            <span className="mono">{config.bank_id}</span>
            <span className="side-label">{stats ? `${stats.memory_units} memory units` : "Connecting"}</span>
          </div>
          {config.public_demo ? (
            <p className="side-foot">Public demo. Reset, seeding and new replay runs are turned off so the shared memory stays intact.</p>
          ) : (
            <div className="side-actions">
              <button className="btn-side" disabled={!!memBusy} onClick={() => memoryAction("seed")}>
                {memBusy === "seed" ? "Loading" : "Load team history"}
              </button>
              <button className="btn-side" disabled={!!memBusy} onClick={() => memoryAction("reset")}>
                {memBusy === "reset" ? "Clearing" : "Reset memory"}
              </button>
            </div>
          )}
          <p className="side-foot">Model {config.model}</p>
        </div>
      </aside>

      <div className="content">
        <header className="page-head">
          <div>
            <h1>{page.title}</h1>
            <p>{page.sub}</p>
          </div>
        </header>

        {view === "replay" && <ReplayView onFinished={memoryChanged} publicDemo={config.public_demo} />}

        {view === "memory" && (
          <MemoryView key={memoryVersion} reviewer={reviewer} vendors={vendors} onMemoryChanged={memoryChanged} publicDemo={config.public_demo} />
        )}

        {view === "desk" && (
          <div className="layout">
            <InvoiceQueue invoices={invoices} selectedId={selectedId} onSelect={setSelectedId} resolutions={resolutions}
              triage={triage} onTriage={runTriage} triaging={triaging} ledgerIds={ledgerIds} />
            <main className="main">
              <ErrorBox error={checksError} onRetry={() => setSelectedId((id) => id)} />
              {!checks && !checksError && <Spinner label="Running rule checks" />}
              {checks && (
                <>
                  <InvoiceHeader checks={checks} />
                  <div className="actions">
                    <button className="btn btn-memory" disabled={!!running} onClick={() => run("memory")}>
                      {running === "memory" ? "Analysing" : "Analyse with memory"}
                    </button>
                    <button className="btn btn-ghost" disabled={!!running} onClick={() => run("plain")}>
                      {running === "plain" ? "Analysing" : "Analyse without memory"}
                    </button>
                    <button className="btn btn-ghost" disabled={!!running} onClick={() => run("compare")}>
                      {running === "compare" ? "Running both" : "Compare side by side"}
                    </button>
                    {running && <Spinner label="Checking rules, searching Hindsight, asking the agent" />}
                  </div>
                  <ErrorBox error={runError} onRetry={() => run("memory")} />
                  <CompareView data={compare} />
                  <POComparison checks={checks} />
                  <div className="grid">
                    <div className="col">
                      <Findings checks={checks} />
                      <VendorAndApproval checks={checks} />
                    </div>
                    <div className="col">
                      <MemoryPanel memory={result?.memory} vendorId={checks.vendor.id} vendorName={checks.vendor.name}
                        loading={!!running && running !== "plain"} />
                      <AgentPanel result={result} />
                      <ResolvePanel invoiceId={selectedId} checks={checks} onResolved={onResolved} existing={existing}
                        reviewerName={reviewer} lastResult={result} />
                    </div>
                  </div>
                </>
              )}
            </main>
          </div>
        )}
      </div>

      {memMsg && (
        <div className="toast" role="status">
          <span>{memMsg}</span>
          <button aria-label="Dismiss" onClick={() => setMemMsg(null)}>{"✕"}</button>
        </div>
      )}
    </div>
  );
}
