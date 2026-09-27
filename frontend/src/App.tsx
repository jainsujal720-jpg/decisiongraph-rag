import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type HealthComponent = { name: string; status: string; latency_ms: number; detail: string | null };
type Health = { status: string; components: HealthComponent[] };
type Metrics = {
  total_queries: number;
  answered_queries: number;
  abstained_queries: number;
  average_latency_ms: number;
  average_confidence: number;
  pending_reviews: number;
};
type Citation = { citation: string; source_name: string; content: string; section_path: string[]; rerank_score: number };
type Claim = { text: string; citations: string[]; supported: boolean; verification_reasons: string[] };
type Review = {
  id: string;
  question: string;
  reason: string;
  status: "pending" | "approved" | "rejected";
  requester_id: string;
  proposed_answer: string | null;
  confidence: { overall: number; label: string };
  created_at: string;
  resolution_notes: string | null;
};
type Answer = {
  answer: string;
  decision: "answered" | "abstained";
  route: string;
  route_reason: string;
  latency_ms: number;
  confidence: { overall: number; retrieval_quality: number; groundedness: number; citation_coverage: number; label: string };
  claims: Claim[];
  citations: Citation[];
  review: Review | null;
  model_calls?: { purpose: string; model: string | null; task_class: string;
    fallback_used: boolean; usage?: { input_tokens: number | null; output_tokens: number | null;
      token_cost_usd: number | null }; routing?: { source: string; jev_mode: string;
      jev_class: string | null; jev_confidence: number | null; reason: string } }[];
};
type DocumentSummary = {
  document_id: string; filename: string; access_scope: string; owner_id: string;
  latest_version_number: number; status: string; parent_chunks: number; child_chunks: number; updated_at: string;
};
type CloudConfig = { enabled: boolean; provider: string };
type CloudUploadStatus = { id: string; filename: string; status: string;
  document_id: string | null; error_message: string | null };

const DEFAULT_SCOPES = "team";

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function App() {
  const [apiBase, setApiBase] = useState("http://localhost:8000");
  const [apiKey, setApiKey] = useState("");
  const [bearerToken, setBearerToken] = useState("");
  const [tenantId, setTenantId] = useState("acme");
  const [userId, setUserId] = useState("sujal");
  const [scopes, setScopes] = useState(DEFAULT_SCOPES);
  const [question, setQuestion] = useState("");
  const [health, setHealth] = useState<Health | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [cloudFile, setCloudFile] = useState<File | null>(null);
  const [cloudGraphEnrichment, setCloudGraphEnrichment] = useState(false);
  const [cloudConfig, setCloudConfig] = useState<CloudConfig | null>(null);
  const [cloudUploadId, setCloudUploadId] = useState<string | null>(null);
  const [cloudUploadStatus, setCloudUploadStatus] = useState<CloudUploadStatus | null>(null);
  const [uploadScope, setUploadScope] = useState("team");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [selectedReview, setSelectedReview] = useState<Review | null>(null);
  const [showReviewQueue, setShowReviewQueue] = useState(false);
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("Ready to inspect grounded answers and human-review work.");

  const requestHeaders = useMemo(() => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (apiKey.trim()) headers["X-API-Key"] = apiKey.trim();
    if (bearerToken.trim()) headers.Authorization = `Bearer ${bearerToken.trim()}`;
    return headers;
  }, [apiKey, bearerToken]);

  const call = useCallback(async <T,>(path: string, init?: RequestInit): Promise<T> => {
    const response = await fetch(`${apiBase.replace(/\/$/, "")}${path}`, {
      ...init,
      headers: { ...requestHeaders, ...(init?.headers ?? {}) },
    });
    const body = await response.json().catch(() => ({ detail: "The API returned an unreadable response." }));
    if (!response.ok) throw new Error(body.detail ?? `Request failed with HTTP ${response.status}`);
    return body as T;
  }, [apiBase, requestHeaders]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextHealth, nextMetrics, reviewResponse, documentResponse, nextCloud] = await Promise.all([
        call<Health>("/health/ready"),
        call<Metrics>(`/v1/metrics?tenant_id=${encodeURIComponent(tenantId)}`),
        call<{ items: Review[] }>(`/v1/reviews?tenant_id=${encodeURIComponent(tenantId)}&review_status=pending&limit=20`),
        call<{ items: DocumentSummary[] }>(`/v1/documents?tenant_id=${encodeURIComponent(tenantId)}&user_id=${encodeURIComponent(userId)}&allowed_scopes=${encodeURIComponent(scopes)}&limit=50`),
        call<CloudConfig>("/v1/cloud/config"),
      ]);
      setHealth(nextHealth);
      setMetrics(nextMetrics);
      setReviews(reviewResponse.items);
      setDocuments(documentResponse.items);
      setCloudConfig(nextCloud);
      setSelectedReview((current) => reviewResponse.items.find((item) => item.id === current?.id) ?? null);
      setMessage("Dashboard data refreshed from the live API.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to refresh the dashboard.");
    } finally {
      setLoading(false);
    }
  }, [call, tenantId]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function askQuestion(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    try {
      const result = await call<Answer>("/v1/answers", {
        method: "POST",
        body: JSON.stringify({
          query: question.trim(), tenant_id: tenantId, user_id: userId,
          allowed_scopes: scopes.split(",").map((item) => item.trim()).filter(Boolean), limit: 8,
        }),
      });
      setAnswer(result);
      setMessage(result.decision === "answered" ? "Answer verified against retrieved evidence." : "The system abstained safely and created a review item.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to generate an answer.");
    } finally {
      setLoading(false);
    }
  }

  async function resolveReview(outcome: "approved" | "rejected") {
    if (!selectedReview) return;
    setLoading(true);
    try {
      await call<Review>(`/v1/reviews/${selectedReview.id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ tenant_id: tenantId, reviewer_id: userId, outcome, notes: notes.trim() || null }),
      });
      setMessage(`Review ${outcome}. The decision is now part of the audit trail.`);
      setNotes("");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to resolve the review.");
    } finally {
      setLoading(false);
    }
  }

  async function uploadDocument(event: FormEvent) {
    event.preventDefault();
    if (!uploadFile) return;
    setLoading(true);
    try {
      const form = new FormData();
      form.append("file", uploadFile);
      form.append("tenant_id", tenantId);
      form.append("owner_id", userId);
      form.append("access_scope", uploadScope);
      const headers: Record<string, string> = {};
      if (apiKey.trim()) headers["X-API-Key"] = apiKey.trim();
      if (bearerToken.trim()) headers.Authorization = `Bearer ${bearerToken.trim()}`;
      const response = await fetch(`${apiBase.replace(/\/$/, "")}/v1/documents`, { method: "POST", headers, body: form });
      const body = await response.json().catch(() => ({ detail: "The API returned an unreadable response." }));
      if (!response.ok) throw new Error(body.detail ?? `Upload failed with HTTP ${response.status}`);
      setUploadFile(null);
      setMessage(`${body.filename} indexed: ${body.child_chunks} searchable chunks.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to upload the document.");
    } finally {
      setLoading(false);
    }
  }

  async function uploadCloudDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!cloudFile || !cloudConfig?.enabled) return;
    const form = event.currentTarget;
    setCloudUploadId(null);
    setCloudUploadStatus(null);
    setLoading(true);
    try {
      const checksum = Array.from(new Uint8Array(await crypto.subtle.digest(
        "SHA-256", await cloudFile.arrayBuffer()
      ))).map((byte) => byte.toString(16).padStart(2, "0")).join("");
      const prepared = await call<{ upload_id: string; upload_url: string;
        headers: Record<string, string> }>("/v1/cloud/uploads", {
        method: "POST",
        body: JSON.stringify({ tenant_id: tenantId, owner_id: userId,
          access_scope: uploadScope, filename: cloudFile.name,
          content_type: cloudFile.type || "application/octet-stream",
          size_bytes: cloudFile.size, checksum_sha256: checksum }),
      });
      setCloudUploadId(prepared.upload_id);
      // This request goes directly to S3. API credentials are never sent there.
      const uploaded = await fetch(prepared.upload_url, {
        method: "PUT", headers: prepared.headers, body: cloudFile,
      });
      if (!uploaded.ok) throw new Error(`Cloud upload failed (HTTP ${uploaded.status}). Check bucket CORS.`);
      const result = await call<{ document_id: string; filename: string;
        child_chunks: number | null; graph_chunks?: number; graph_status?: string }>(`/v1/cloud/uploads/${prepared.upload_id}/complete`, {
        method: "POST", body: JSON.stringify({ tenant_id: tenantId, owner_id: userId,
          enrich_graph: cloudGraphEnrichment }),
      });
      setCloudFile(null);
      form.reset();
      await refresh();
      setMessage(`${result.filename} stored in the cloud and indexed${result.child_chunks == null ? "" : `: ${result.child_chunks} searchable chunks`}.${result.graph_status === "failed" ? " Graph enrichment failed; the document is searchable, and graph enrichment can be retried." : result.graph_chunks == null ? "" : ` Graph enriched from ${result.graph_chunks} chunks.`}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cloud upload failed.");
    } finally {
      setLoading(false);
    }
  }

  async function inspectCloudUpload() {
    if (!cloudUploadId) return;
    try {
      const result = await call<CloudUploadStatus>(
        `/v1/cloud/uploads/${cloudUploadId}?tenant_id=${encodeURIComponent(tenantId)}&owner_id=${encodeURIComponent(userId)}`
      );
      setCloudUploadStatus(result);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to inspect the cloud upload.");
    }
  }

  async function operateDocument(documentId: string, action: "reindex" | "delete") {
    setLoading(true);
    try {
      const path = action === "reindex" ? `/v1/documents/${documentId}/reindex` : `/v1/documents/${documentId}`;
      await call(path, { method: action === "reindex" ? "POST" : "DELETE", body: JSON.stringify({ tenant_id: tenantId, actor_id: userId }) });
      setMessage(action === "reindex" ? "Document embeddings were refreshed and audited." : "Document, vectors, and graph evidence were deleted.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Document operation failed.");
    } finally {
      setLoading(false);
    }
  }

  const answerRate = metrics && metrics.total_queries ? metrics.answered_queries / metrics.total_queries : 0;

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">DG</span><div><strong>DecisionGraph</strong><small>Governed GraphRAG</small></div></div>
        <p className="eyebrow">Live workspace</p>
        <label>API base URL<input value={apiBase} onChange={(event) => setApiBase(event.target.value)} /></label>
        <label>Optional API key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Only when API_ACCESS_KEY is set" /></label>
        <label>Optional bearer token<input type="password" value={bearerToken} onChange={(event) => setBearerToken(event.target.value)} placeholder="Required only when AUTH_MODE=jwt" /></label>
        <label>Tenant<input value={tenantId} onChange={(event) => setTenantId(event.target.value)} /></label>
        <label>Reviewer / user<input value={userId} onChange={(event) => setUserId(event.target.value)} /></label>
        <label>Allowed scopes<input value={scopes} onChange={(event) => setScopes(event.target.value)} placeholder="team, company" /></label>
        <button className="secondary" onClick={() => void refresh()} disabled={loading}>{loading ? "Refreshing…" : "Refresh live data"}</button>
        <p className="security-note">Keys and tokens remain only in this browser tab. They are never saved by the dashboard.</p>
      </aside>

      <section className="workspace">
        <header className="topbar"><div><p className="eyebrow">Evidence-first operations</p><h1>Reviewer dashboard</h1></div><div className={`system-status ${health?.status === "ready" ? "ready" : "warning"}`}><span />{health?.status === "ready" ? "All systems ready" : "Checking systems"}</div></header>
        <p className="message" aria-live="polite">{message}</p>

        <section className="metrics-grid" aria-label="Operational metrics">
          <Metric label="Queries" value={String(metrics?.total_queries ?? "—")} help="Audited answer requests" />
          <Metric label="Answer rate" value={percent(answerRate)} help="Answered rather than abstained" />
          <Metric label="Avg. confidence" value={metrics ? percent(metrics.average_confidence) : "—"} help="Evidence-backed confidence" />
          <Metric label="Pending review" value={String(metrics?.pending_reviews ?? "—")} help="Items needing a human decision" />
        </section>

        <section className="card query-card">
          <div className="card-heading"><div><p className="eyebrow">Grounded answer</p><h2>Ask the knowledge base</h2></div><span className="pill">citations required</span></div>
          <form onSubmit={askQuestion}>
            <textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} aria-label="Question" placeholder="Ask about an indexed document" />
            <button className="primary" disabled={loading || !question.trim()}>{loading ? "Verifying evidence…" : "Generate verified answer"}</button>
          </form>
        </section>

        <section className="card document-card">
          <div className="card-heading"><div><p className="eyebrow">Document operations</p><h2>Knowledge-base lifecycle</h2></div><span className="count">{documents.length}</span></div>
          <form className="upload-form" onSubmit={uploadDocument}>
            <input aria-label="Document to upload" type="file" accept=".pdf,.docx,.txt,.md,.csv" onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)} />
            <select aria-label="Document access scope" value={uploadScope} onChange={(event) => setUploadScope(event.target.value)}><option value="team">team</option><option value="company">company</option><option value="private">private</option></select>
            <button className="primary" disabled={loading || !uploadFile}>{loading ? "Indexing…" : "Upload and index"}</button>
          </form>
          {documents.length === 0 ? <p className="empty">No accessible documents are indexed for this scope.</p> : <div className="document-list">{documents.map((document) => <article className="document-row" key={document.document_id}><div><strong>{document.filename}</strong><p>v{document.latest_version_number} · {document.access_scope} · {document.child_chunks} searchable chunks</p></div><div className="document-actions"><button className="compact" disabled={loading} onClick={() => void operateDocument(document.document_id, "reindex")}>Re-index</button><button className="compact danger" disabled={loading} onClick={() => { if (window.confirm(`Delete ${document.filename} and its graph evidence?`)) void operateDocument(document.document_id, "delete"); }}>Delete</button></div></article>)}</div>}
        </section>

        <section className="card document-card">
          <div className="card-heading"><div><p className="eyebrow">Cloud documents · Stage 14</p><h2>Upload to private cloud storage</h2></div><span className="pill">{cloudConfig?.enabled ? "S3 ready" : "Setup required"}</span></div>
          <p className="empty">Files are uploaded directly to your private S3 bucket and then indexed by DecisionGraph. The document list above shows the indexed result.</p>
          {cloudConfig?.enabled ? <form className="upload-form" onSubmit={uploadCloudDocument}>
            <input aria-label="Cloud document to upload" type="file" accept=".pdf,.docx,.txt,.md,.csv,.xlsx" onChange={(event) => setCloudFile(event.target.files?.[0] ?? null)} />
            <select aria-label="Cloud document access scope" value={uploadScope} onChange={(event) => setUploadScope(event.target.value)}><option value="team">team</option><option value="company">company</option><option value="private">private</option></select>
            <button className="primary" disabled={loading || !cloudFile || cloudFile.size > 20 * 1024 * 1024}>{loading ? "Uploading and indexing…" : "Upload to S3 and index"}</button>
            <label className="cloud-option"><input type="checkbox" checked={cloudGraphEnrichment} onChange={(event) => setCloudGraphEnrichment(event.target.checked)} />Also extract evidence-backed graph relationships (uses an additional model call)</label>
          </form> : <p className="empty">Set CLOUD_S3_BUCKET and CLOUD_S3_REGION on the API to enable cloud uploads.</p>}
          {cloudUploadId && <div className="cloud-inspect"><button className="compact" onClick={() => void inspectCloudUpload()}>Check last upload status</button>{cloudUploadStatus && <span>{cloudUploadStatus.filename}: {cloudUploadStatus.status}{cloudUploadStatus.error_message ? ` · ${cloudUploadStatus.error_message}` : ""}</span>}</div>}
        </section>

        {answer && <section className="card answer-card">
          <div className="card-heading"><div><p className="eyebrow">{answer.route} route · {answer.route_reason}</p><h2>{answer.decision === "answered" ? "Verified answer" : "Safe abstention"}</h2></div><span className={`decision ${answer.decision}`}>{answer.decision}</span></div>
          <p className="answer-text">{answer.answer}</p>
          <div className="confidence-row"><span>Confidence <strong>{percent(answer.confidence.overall)}</strong> · {answer.confidence.label}</span><span>{answer.latency_ms} ms</span></div>
          <div className="meter"><span style={{ width: percent(answer.confidence.overall) }} /></div>
          {answer.review && <p className="review-context">This question was added to human review: {answer.review.reason}.</p>}
          {answer.model_calls && answer.model_calls.length > 0 && <div className="model-trace">
            <h3>Model decisions</h3>
            {answer.model_calls.map((call, index) => <article className="model-call" key={`${call.purpose}-${index}`}>
              <div><strong>{call.purpose === "draft" ? "Answer draft" : "Citation verification"}: {call.model ?? "unknown model"}</strong>
                <p>Task class: {call.task_class} · {call.routing?.source === "jev" ? "Jev selected the route" : "Rules selected the route"}{call.fallback_used ? " · fallback used" : ""}</p>
                {call.routing?.jev_class && <small>Jev suggested {call.routing.jev_class} ({percent(call.routing.jev_confidence ?? 0)} confidence) · {call.routing.reason}</small>}
                {call.usage?.input_tokens != null && <small> · Input: {call.usage.input_tokens} / output: {call.usage.output_tokens ?? 0} tokens · model token estimate ${call.usage.token_cost_usd ?? 0}</small>}
              </div>
            </article>)}
            <small>Token cost is estimated from recorded usage; it is not your provider invoice.</small>
          </div>}
          {answer.claims.length > 0 && <div className="claim-list"><h3>Claim verification</h3>{answer.claims.map((claim) => <article className="claim" key={claim.text}><span className={claim.supported ? "check" : "cross"}>{claim.supported ? "✓" : "×"}</span><div><strong>{claim.text}</strong><p>{claim.verification_reasons.join(" ")}</p><small>{claim.citations.join(", ")}</small></div></article>)}</div>}
          {answer.citations.length > 0 && <div className="citation-list"><h3>Evidence</h3>{answer.citations.map((citation) => <article className="citation" key={citation.citation}><b>{citation.citation}</b><div><strong>{citation.source_name}</strong><p>{citation.content}</p><small>{citation.section_path.join(" › ") || "Graph evidence"} · rerank {percent(citation.rerank_score)}</small></div></article>)}</div>}
        </section>}

        <section className="review-backlog">
          <div className="card review-backlog-heading"><div><p className="eyebrow">Human in the loop</p><h2>Tenant review backlog</h2><p className="review-context">Past questions awaiting review across {tenantId}. These items are separate from the answer above.</p></div><button className="secondary" aria-expanded={showReviewQueue} onClick={() => setShowReviewQueue((current) => !current)}>{showReviewQueue ? "Hide review backlog" : `Show ${reviews.length} pending reviews`}</button></div>
          {showReviewQueue && <div className="lower-grid">
          <section className="card"><div className="card-heading"><div><p className="eyebrow">Human in the loop</p><h2>Pending review queue</h2></div><span className="count">{reviews.length}</span></div>
            {reviews.length === 0 ? <p className="empty">No pending reviews. Low-confidence or abstained answers will appear here.</p> : <div className="review-list">{reviews.map((review) => <button className={`review-row ${selectedReview?.id === review.id ? "selected" : ""}`} key={review.id} onClick={() => setSelectedReview(review)}><strong>{review.question}</strong><span>{review.reason}</span><small>{percent(review.confidence.overall)} confidence</small></button>)}</div>}
          </section>
          <section className="card"><div className="card-heading"><div><p className="eyebrow">Resolution</p><h2>{selectedReview ? "Review decision" : "Select a queue item"}</h2></div></div>
            {selectedReview ? <><p className="review-question">{selectedReview.question}</p><p className="review-reason">{selectedReview.reason}</p><label>Resolution notes<textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={4} placeholder="State what the reviewer verified or why it was rejected." /></label><div className="actions"><button className="approve" disabled={loading} onClick={() => void resolveReview("approved")}>Approve</button><button className="reject" disabled={loading} onClick={() => void resolveReview("rejected")}>Reject</button></div></> : <p className="empty">Choose a pending item to record a reviewer outcome.</p>}
          </section>
          </div>}
        </section>

        <section className="dependency-strip">{health?.components.map((component) => <span key={component.name} className={component.status === "up" ? "dependency up" : "dependency down"}>{component.name} · {component.status} · {Math.round(component.latency_ms)} ms</span>)}</section>
      </section>
    </main>
  );
}

function Metric({ label, value, help }: { label: string; value: string; help: string }) {
  return <article className="metric"><span>{label}</span><strong>{value}</strong><small>{help}</small></article>;
}

export default App;
