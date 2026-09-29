async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`/api${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    throw new Error("Cannot reach the Precedent server. Is the backend running on port 8000?");
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail;
    const msg = Array.isArray(detail)
      ? detail.map((d) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join("; ")
      : detail || `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return data;
}

export const api = {
  config: () => request("/config"),
  invoices: () => request("/invoices"),
  invoice: (id) => request(`/invoices/${id}`),
  analyze: (id, useMemory, reviewer) =>
    request(`/invoices/${id}/analyze`, { method: "POST", body: { use_memory: useMemory, reviewer: reviewer || null } }),
  compare: (id, reviewer) => request(`/invoices/${id}/compare`, { method: "POST", body: { reviewer: reviewer || null } }),
  vendors: () => request("/vendors"),
  addNote: (body) => request("/memory/notes", { method: "POST", body }),
  ledger: () => request("/memory/ledger"),
  forget: (docId) => request(`/memory/documents/${encodeURIComponent(docId)}`, { method: "DELETE" }),
  playbook: () => request("/memory/playbook"),
  refreshPlaybook: () => request("/memory/playbook/refresh", { method: "POST" }),
  triage: () => request("/triage", { method: "POST" }),
  metrics: () => request("/metrics"),
  resolve: (id, body) => request(`/invoices/${id}/resolve`, { method: "POST", body }),
  memoryStats: () => request("/memory/stats"),
  seedHistory: () => request("/memory/seed-history", { method: "POST" }),
  resetMemory: () => request("/memory/reset", { method: "POST" }),
  ask: (question, vendorId) => request("/memory/ask", { method: "POST", body: { question, vendor_id: vendorId || null } }),
};

const inrWhole = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const inrPaise = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const money = (n) => (n == null ? "" : Number.isInteger(Number(n)) ? inrWhole.format(Number(n)) : inrPaise.format(Number(n)));
export const day = (s) =>
  s ? new Date(s).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "";
