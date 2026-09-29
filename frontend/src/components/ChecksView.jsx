import { money, day } from "../api.js";
import { Card, Chip, SeverityChip } from "./ui.jsx";

export function InvoiceHeader({ checks }) {
  const { invoice: inv, vendor, purchase_order: po, goods_receipt: grn, payment, approval } = checks;
  return (
    <section className="card invoice-header">
      <div className="ih-main">
        <p className="eyebrow">{vendor.name}</p>
        <h1 className="mono">{inv.invoice_no}</h1>
        <p className="muted">
          {vendor.city}, {vendor.state} {vendor.msme && <Chip tone="neutral">MSME</Chip>} <span className="mono small">{vendor.gstin}</span>
        </p>
      </div>
      <div className="ih-total">
        <p className="eyebrow">Invoice total</p>
        <p className="big-number">{money(inv.total)}</p>
        <p className="muted small">
          {money(inv.subtotal)} plus GST {money(inv.tax_total)}
        </p>
      </div>
      <dl className="ih-facts">
        <div><dt>Invoice date</dt><dd>{day(inv.invoice_date)}</dd></div>
        <div><dt>Purchase order</dt><dd className="mono">{po ? po.id : "None quoted"}</dd></div>
        <div><dt>Goods receipt</dt><dd className="mono">{grn ? grn.id : vendor.supply_type === "services" ? "Service, not needed" : "None booked"}</dd></div>
        <div><dt>Terms</dt><dd>{payment.invoice_terms}{payment.invoice_terms !== payment.master_terms && ` (master ${payment.master_terms})`}</dd></div>
        <div><dt>Pay by</dt><dd>{day(payment.pay_by)}</dd></div>
        <div><dt>Approver</dt><dd><Chip tone={approval.level >= 3 ? "warn" : approval.level === 2 ? "info" : "neutral"}>{approval.approver_role}</Chip></dd></div>
      </dl>
      {inv.notes && <p className="invoice-note">Note on invoice: “{inv.notes}”</p>}
    </section>
  );
}

export function Findings({ checks }) {
  const { findings } = checks;
  return (
    <Card title="Rule checks" subtitle="Deterministic checks computed in code. The agent explains these, it does not change them."
      right={findings.length ? <Chip tone="neutral">{findings.length} finding{findings.length > 1 ? "s" : ""}</Chip> : <Chip tone="ok">All clear</Chip>}>
      {findings.length === 0 && <p className="muted">Price, quantity, receipt, GST, duplicate, vendor and terms checks all passed.</p>}
      <ul className="findings">
        {findings.map((f, i) => (
          <li key={i} className={`finding sev-border-${f.severity}`}>
            <div className="finding-top">
              <SeverityChip severity={f.severity} />
              <strong>{f.title}</strong>
              <span className="mono small muted">{f.code}</span>
            </div>
            <p>{f.detail}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function POComparison({ checks }) {
  const { po_comparison: rows, purchase_order: po } = checks;
  if (!po) {
    return (
      <Card title="PO comparison">
        <p className="muted">No purchase order on this invoice, so there is nothing to match against.</p>
      </Card>
    );
  }
  return (
    <Card title="PO comparison" subtitle={`${po.id}, raised ${day(po.po_date)}`}>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Item</th><th className="num">PO qty</th><th className="num">Received</th><th className="num">Invoiced</th>
              <th className="num">PO rate</th><th className="num">Invoice rate</th><th className="num">Variance</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.item_code}>
                <td>{r.description}</td>
                <td className="num">{r.po_qty}{r.previously_invoiced ? <span className="muted small"> ({r.previously_invoiced} billed)</span> : null}</td>
                <td className="num">{r.received_qty ?? "n/a"}</td>
                <td className={`num ${r.qty_ok && (r.received_qty == null || r.invoiced_qty <= r.received_qty) ? "" : "bad-cell"}`}>{r.invoiced_qty}</td>
                <td className="num">{money(r.po_price)}</td>
                <td className={`num ${r.price_ok ? "" : "bad-cell"}`}>{money(r.invoiced_price)}</td>
                <td className={`num ${r.price_ok ? "" : "bad-cell"}`}>{r.price_variance_pct > 0 ? "+" : ""}{r.price_variance_pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {po.amendments?.length > 0 && (
        <div className="amendments">
          {po.amendments.map((a, i) => (
            <p key={i}><Chip tone="info">PO amended {day(a.date)}</Chip> {a.change}. {a.reason}. <span className="muted">By {a.by}.</span></p>
          ))}
        </div>
      )}
    </Card>
  );
}

export function VendorAndApproval({ checks }) {
  const { baseline: b, approval, vendor } = checks;
  return (
    <Card title="Vendor history and approval">
      <div className="two-col">
        <div>
          <p className="eyebrow">6-month baseline</p>
          {b.median ? (
            <>
              <p><strong>{money(b.median)}</strong> median over {b.invoice_count} paid invoices</p>
              <p className="muted small">Range {money(b.min)} to {money(b.max)}. This invoice is <strong>{b.ratio}x</strong> the median.</p>
              <div className="bars">
                {b.recent.map((r) => (
                  <div key={r.invoice_no} className="bar" style={{ height: `${Math.min(100, (r.total / Math.max(b.max, checks.invoice.total)) * 100)}%` }} title={`${r.invoice_no}: ${money(r.total)}`} />
                ))}
                <div className="bar bar-current" style={{ height: `${Math.min(100, (checks.invoice.total / Math.max(b.max, checks.invoice.total)) * 100)}%` }} title={`This invoice: ${money(checks.invoice.total)}`} />
              </div>
            </>
          ) : (
            <p className="muted">Not enough history for {vendor.name} yet ({b.invoice_count} paid invoices).</p>
          )}
        </div>
        <div>
          <p className="eyebrow">Approval required</p>
          <p><strong>{approval.approver_role}</strong> (level {approval.level})</p>
          <ul className="plain-list small">
            {approval.reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      </div>
    </Card>
  );
}
