import { money, day } from "../api.js";
import { Chip, SeverityChip } from "./ui.jsx";

export default function InvoiceQueue({ invoices, selectedId, onSelect, resolutions }) {
  return (
    <aside className="queue">
      <div className="queue-head">
        <h2>Invoice queue</h2>
        <span className="muted small">{invoices.length} pending</span>
      </div>
      <ul>
        {invoices.map((inv) => {
          const resolved = resolutions[inv.id] || inv.resolution;
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
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
