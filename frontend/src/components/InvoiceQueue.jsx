import { money, day } from "../api.js";
import { Chip, SeverityChip } from "./ui.jsx";

export default function InvoiceQueue({ invoices, selectedId, onSelect, resolutions, triage, onTriage, triaging, ledgerIds }) {
  return (
    <aside className="queue">
      <div className="queue-head">
        <h2>Invoice queue</h2>
        <span className="muted small">{invoices.length} pending</span>
      </div>
      <button className="btn btn-ghost btn-sm triage-btn" disabled={triaging} onClick={onTriage}>
        {triaging ? "Checking memory" : "Check against memory"}
      </button>
      <ul>
        {invoices.map((inv) => {
          const resolved = resolutions[inv.id] || inv.resolution || ledgerIds?.has(inv.case_id);
          const t = triage?.[inv.id];
          return (
            <li key={inv.id}>
              <button className={`queue-item ${selectedId === inv.id ? "active" : ""}`} onClick={() => onSelect(inv.id)}>
                <div className="qi-top">
                  <span className="mono">{inv.invoice_no}</span>
                  <span className="qi-amount">{money(inv.total)}</span>
                </div>
                <div className="qi-vendor">{inv.vendor_name}</div>
                <div className="qi-meta">
                  <span className="muted small">{day(inv.invoice_date)}</span>
                  {resolved ? <Chip tone="memory">Resolved, in memory</Chip> : <SeverityChip severity={inv.max_severity} />}
                </div>
                {inv.scenario && <div className="qi-scenario">{inv.scenario}</div>}
                {t && !t.error && (t.precedent_count > 0 || t.vendor_notes > 0) && (
                  <div className="qi-memory">
                    {t.precedent_count > 0 && <Chip tone="memory-soft">{t.precedent_count} precedent{t.precedent_count > 1 ? "s" : ""}</Chip>}
                    {t.vendor_notes > 0 && <Chip tone="info">vendor note</Chip>}
                  </div>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
