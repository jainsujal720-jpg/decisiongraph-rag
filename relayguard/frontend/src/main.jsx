import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API = "http://localhost:8100";

function App() {
  const [tenant, setTenant] = useState("acme");
  const [apiKey, setApiKey] = useState("demo-acme-operator-key");
  const [principal, setPrincipal] = useState(null);
  const [user, setUser] = useState("sujal");
  const [prompt, setPrompt] = useState("Summarize this meeting note");
  const [failure, setFailure] = useState(false);
  const [privileged, setPrivileged] = useState(false);
  const [metrics, setMetrics] = useState(null);
  const [budget, setBudget] = useState(null);
  const [providerHealth, setProviderHealth] = useState(null);
  const [integrity, setIntegrity] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [signals, setSignals] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const headers = () => ({ "X-API-Key": apiKey });
  const refresh = async () => {
    const target = encodeURIComponent(tenant);
    const [metricsResponse, budgetResponse, healthResponse, whoamiResponse, integrityResponse, signalsResponse] = await Promise.all([
      fetch(`${API}/v1/metrics?tenant_id=${target}`, { headers: headers() }),
      fetch(`${API}/v1/budget?tenant_id=${target}`, { headers: headers() }),
      fetch(`${API}/v1/providers/health`, { headers: headers() }),
      fetch(`${API}/v1/whoami`, { headers: headers() }),
      fetch(`${API}/v1/audit/integrity?tenant_id=${target}`, { headers: headers() }),
      fetch(`${API}/v1/governance/signals?tenant_id=${target}`, { headers: headers() }),
    ]);
    if (!metricsResponse.ok || !budgetResponse.ok || !healthResponse.ok || !whoamiResponse.ok || !integrityResponse.ok || !signalsResponse.ok) {
      throw new Error("Could not load governance data");
    }
    setMetrics(await metricsResponse.json());
    setBudget(await budgetResponse.json());
    setProviderHealth(await healthResponse.json());
    setPrincipal(await whoamiResponse.json());
    setIntegrity(await integrityResponse.json());
    setSignals(await signalsResponse.json());
  };

  useEffect(() => { refresh().catch(() => setError("Authentication or API connection failed")); }, []);

  const generateEvidence = async () => {
    setError("");
    try {
      const target = encodeURIComponent(tenant);
      const response = await fetch(`${API}/v1/audit/evidence?tenant_id=${target}`, { headers: headers() });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Evidence export failed");
      setEvidence(data);
    } catch (issue) { setError(issue.message); }
  };

  const submit = async (event) => {
    event.preventDefault(); setLoading(true); setError("");
    try {
      const response = await fetch(`${API}/v1/chat/completions`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
        body: JSON.stringify({ tenant_id: tenant, user_id: user, prompt, simulate_primary_failure: failure, requires_privileged_access: privileged })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Request failed");
      setResult(data); await refresh();
    } catch (issue) { setError(issue.message); } finally { setLoading(false); }
  };

  return <main>
    <header><p>GOVERNED LLM GATEWAY</p><h1>RelayGuard control plane</h1><span>Stage 10 · governance risk signals</span></header>
    <section className="metrics">{[["Requests", metrics?.requests ?? "—"], ["Fallbacks", metrics?.fallbacks ?? "—"], ["Model token estimate", metrics ? `$${(metrics.token_cost_usd ?? 0).toFixed(6)} (${metrics.measured_requests ?? 0} measured)` : "—"], ["Governance estimate", metrics ? `$${metrics.total_cost_usd.toFixed(6)}` : "—"], ["Budget left", budget ? `$${budget.remaining_usd.toFixed(6)}` : "—"]].map(([label, value]) => <article key={label}><small>{label}</small><strong>{value}</strong></article>)}</section>
    <section className="panel"><h2>Caller identity</h2><p>{principal ? `${principal.tenant_id} is authenticated as ${principal.role}.` : "Verifying API key…"} Privileged actions require an operator role.</p><label>API key<input value={apiKey} onChange={e => setApiKey(e.target.value)} onBlur={() => refresh().catch(issue => setError(issue.message))} /></label></section>
    <section className="panel"><h2>Audit integrity</h2><p>{integrity?.verified ? `Verified hash chain · ${integrity.events_checked} event${integrity.events_checked === 1 ? "" : "s"} checked` : "Audit chain could not be verified."}</p></section>
    <section className="panel"><h2>Audit evidence</h2><p>Only an operator can generate a tenant-scoped review bundle.</p><button type="button" onClick={generateEvidence}>Generate evidence bundle</button>{evidence && <p>Verified export: {evidence.events.length} event{evidence.events.length === 1 ? "" : "s"} · ledger head {evidence.integrity.head_hash.slice(0, 12)}…</p>}</section>
    <section className="panel"><h2>Governance alerts</h2><p>{signals?.status === "healthy" ? "No active governance risks." : "Operator attention is required."}</p>{signals?.signals?.map((signal, index) => <p className="error" key={index}>{signal.severity.toUpperCase()}: {signal.message}</p>)}</section>
    <section className="panel"><h2>Shared provider resilience</h2><p>{providerHealth?.status === "healthy" ? "All provider circuits are closed and shared through Redis." : "A shared provider circuit is open; every API instance will use the approved fallback."}</p><div className="circuits">{providerHealth?.circuits?.map(circuit => <article key={circuit.model} className={circuit.state === "open" ? "circuit open" : "circuit"}><strong>{circuit.model}</strong><span>{circuit.state}</span><small>{circuit.failures} recent failure{circuit.failures === 1 ? "" : "s"}{circuit.retry_after_seconds ? ` · retry in ${circuit.retry_after_seconds}s` : ""}</small></article>)}</div></section>
    <section className="panel"><h2>Send governed request</h2><form onSubmit={submit}>
      <label>Tenant<input value={tenant} onChange={e => setTenant(e.target.value)} /></label>
      <label>User<input value={user} onChange={e => setUser(e.target.value)} /></label>
      <label>Prompt<textarea value={prompt} onChange={e => setPrompt(e.target.value)} /></label>
      <label className="check"><input type="checkbox" checked={failure} onChange={e => setFailure(e.target.checked)} /> Simulate primary-model failure</label>
      <label className="check"><input type="checkbox" checked={privileged} onChange={e => setPrivileged(e.target.checked)} /> Mark as a privileged governed action</label>
      <button disabled={loading}>{loading ? "Routing…" : "Route safely"}</button>
    </form></section>
    {error && <p className="error">{error}</p>}
    {result && <section className="panel result"><h2>Governed response</h2><p>{result.answer}</p><dl><div><dt>Route</dt><dd>{result.route.primary_model} → {result.route.fallback_model}</dd></div><div><dt>Actual model</dt><dd>{result.served_model}</dd></div><div><dt>Served by</dt><dd>{result.served_by}{result.fallback_used ? " (fallback used)" : ""}</dd></div><div><dt>Jev decision</dt><dd>{result.routing?.jev_class ? `${result.routing.jev_class} · confidence ${Math.round(result.routing.jev_confidence * 100)}% · ${result.routing.reason}` : result.routing?.reason ?? "off"}</dd></div><div><dt>Routing source</dt><dd>{result.routing?.source ?? "rules"}</dd></div><div><dt>Model input / output tokens</dt><dd>{result.usage?.input_tokens ?? "—"} / {result.usage?.output_tokens ?? "—"}</dd></div><div><dt>Model token estimate</dt><dd>{result.usage?.token_cost_usd == null ? "Unavailable" : `$${result.usage.token_cost_usd}`}</dd></div><div><dt>Jev token estimate</dt><dd>{result.routing?.jev_cost_usd == null ? "—" : `$${result.routing.jev_cost_usd}`}</dd></div><div><dt>Governance estimate</dt><dd>${result.cost_usd}</dd></div><div><dt>Retries</dt><dd>{result.governance.retry_count}</dd></div><div><dt>Budget remaining</dt><dd>${result.governance.remaining_budget_usd}</dd></div><div><dt>Reason</dt><dd>{result.route.reason}</dd></div></dl><small>Token estimates use measured tokens and a price table. Governance budget still uses its legacy estimate; neither figure is an invoice.</small></section>}
    <footer>Tenant identity and role are verified before routing; each completed request is linked into the tamper-evident audit chain.</footer>
  </main>;
}
createRoot(document.getElementById("root")).render(<App />);
