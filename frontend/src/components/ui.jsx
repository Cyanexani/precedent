export const SEVERITY_LABEL = { high: "High", medium: "Medium", low: "Low", info: "Info", none: "Clean" };

export const ACTION_LABEL = {
  approve: "Approve",
  approve_with_conditions: "Approve with conditions",
  hold: "Hold",
  reject: "Reject",
  escalate: "Escalate",
};

export const PRECEDENT_LABEL = {
  none: "No precedent",
  applies: "Precedent applies",
  partially_applies: "Partially applies",
  does_not_apply: "Precedent does not apply",
  mixed: "Mixed precedents",
};

export function Chip({ tone = "neutral", children, title }) {
  return (
    <span className={`chip chip-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function SeverityChip({ severity }) {
  return <Chip tone={`sev-${severity}`}>{SEVERITY_LABEL[severity] || severity}</Chip>;
}

export function ActionChip({ action, big }) {
  const tone = { approve: "ok", approve_with_conditions: "ok-soft", hold: "warn", reject: "bad", escalate: "warn" }[action] || "neutral";
  return <span className={`chip chip-${tone} ${big ? "chip-big" : ""}`}>{ACTION_LABEL[action] || action}</span>;
}

export function Card({ title, subtitle, right, children, className = "" }) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <header className="card-head">
          <div>
            {title && <h3>{title}</h3>}
            {subtitle && <p className="muted small">{subtitle}</p>}
          </div>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function Spinner({ label }) {
  return (
    <div className="spinner-row">
      <span className="spinner" />
      <span className="muted">{label}</span>
    </div>
  );
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null;
  return (
    <div className="error-box">
      <strong>Something went wrong.</strong> <span>{error}</span>
      {onRetry && (
        <button className="btn btn-ghost btn-sm" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
