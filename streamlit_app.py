"""Streamlit frontend for the RAG Evaluation System.

Security note: every piece of dynamic content (model answers, chunk text,
document names) is passed through `html.escape()` before it reaches a
`unsafe_allow_html=True` block. Chunk text originates from user-uploaded
documents, so interpolating it raw was a stored-XSS vector.
"""
import html
import os
import time
from urllib.parse import quote

import pandas as pd
import requests
import streamlit as st

# ============ CONFIG ============
BACKEND = os.environ.get("BACKEND_INTERNAL_URL", "http://localhost:8001")
API = f"{BACKEND}/api"
LANGFUSE_UI = os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
API_KEY = (os.environ.get("RAG_API_KEY") or "").strip()

st.set_page_config(
    page_title="RAG Evaluation Lab",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============ STYLING ============
st.markdown(
    """
<style>
:root { --accent:#e85d3a; --accent-2:#f0b83a; --ink:#111214; --ink-soft:#3d4046; --paper:#faf7f2; --line:#e6e0d6; }
html, body, [class*="css"]  {
    font-family: "IBM Plex Sans", "IBM Plex Mono", ui-sans-serif, system-ui, sans-serif;
    color: var(--ink);
}
h1, h2, h3, .st-emotion-cache-10trblm { font-family: "Fraunces", "IBM Plex Serif", Georgia, serif; letter-spacing: -0.01em; }
.main .block-container { padding-top: 1.6rem; max-width: 1300px; }
.stApp { background:
    radial-gradient(1200px 500px at 90% -10%, rgba(232,93,58,.10), transparent 60%),
    radial-gradient(900px 500px at -10% 20%, rgba(240,184,58,.10), transparent 60%),
    var(--paper);
}
.metric-card {
    border: 1px solid var(--line); border-radius: 14px; padding: 18px 20px; background:#fff;
    box-shadow: 0 1px 0 rgba(0,0,0,.02);
}
.metric-label { font-size: 12px; letter-spacing:.08em; text-transform:uppercase; color:#7a7570; }
.metric-value { font-size: 30px; font-weight: 600; margin-top: 4px; font-family:"Fraunces",serif; }
.chunk-card { border-left: 3px solid var(--accent); background:#fff; border-radius: 10px;
    padding: 12px 16px; margin: 8px 0; font-size: 14px; white-space: pre-wrap; }
.chunk-src { font-size: 11px; text-transform:uppercase; letter-spacing:.06em; color:#7a7570; }
.answer-box { background:#111214; color:#f6f2ea; padding: 18px 22px; border-radius: 12px;
    line-height: 1.55; font-size: 15px; white-space: pre-wrap; }
.answer-box code, .answer-box strong { color: var(--accent-2); }
.badge { display:inline-block; padding: 2px 10px; border-radius: 999px;
    background:#1a1b1d; color:#f6f2ea; font-size: 11px; letter-spacing:.05em; margin-right:6px; }
.badge.ok { background: #135e3c; }
.badge.warn { background: #a35b13; }
.badge.err { background: #7c221a; }
hr { border-color: var(--line); }
.stButton>button, .stDownloadButton>button {
    border-radius: 999px; padding: 8px 18px; border:1px solid #111214; background:#111214; color:#faf7f2;
    font-weight: 500; letter-spacing:.02em;
}
.stButton>button:hover { background: var(--accent); border-color: var(--accent); color:#fff; }
[data-testid="stSidebar"] { background: #1a1b1d; }
[data-testid="stSidebar"] * { color:#e9e4da !important; }
[data-testid="stSidebar"] .stButton>button { background: var(--accent); border-color: var(--accent); color:#fff; }
input, textarea { border-radius: 10px !important; }
</style>
""",
    unsafe_allow_html=True,
)


# ============ API HELPERS ============
# What a backend call can raise: transport/HTTP errors (bad JSON included), a
# missing key in a response, or a failed / timed-out background evaluation.
API_ERRORS = (requests.RequestException, KeyError, ValueError, RuntimeError)


def _headers() -> dict:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def api_get(path, **params):
    r = requests.get(f"{API}{path}", params=params, timeout=60, headers=_headers())
    r.raise_for_status()
    return r.json()


def api_post(path, json=None, files=None):
    r = requests.post(
        f"{API}{path}", json=json, files=files, timeout=600, headers=_headers()
    )
    r.raise_for_status()
    return r.json()


def api_delete(path):
    r = requests.delete(f"{API}{path}", timeout=60, headers=_headers())
    r.raise_for_status()
    return r.json()


def run_eval_in_background(scope: str, limit: int, timeout_s: int = 3600) -> dict:
    """Start a background evaluation and poll until it finishes.

    A full test-set run can outlast what proxies hold one request open for.
    """
    job = api_post("/evaluations/run", json={"scope": scope, "limit": limit, "background": True})
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(3)
        status = api_get(f"/evaluations/jobs/{job['job_id']}")
        if status["status"] == "done":
            return status["result"]
        if status["status"] == "failed":
            raise RuntimeError(status.get("error") or "Evaluation failed")
    raise RuntimeError("Evaluation is still running; check the history table later.")


def err_text(e: Exception) -> str:
    """Human-readable error, preferring the API's `detail` field."""
    resp = getattr(e, "response", None)
    if resp is not None:
        try:
            return str(resp.json().get("detail", resp.text))[:400]
        except ValueError:
            return (resp.text or str(e))[:400]
    return str(e)[:400]


def fmt_metric(v) -> str:
    return "—" if v is None else f"{v:.2f}"


# ============ SIDEBAR ============
with st.sidebar:
    st.markdown("### RAG Evaluation Lab")
    st.caption("Retrieval + generation with faithfulness scores you can actually point to.")
    st.markdown("---")
    health = None
    try:
        health = api_get("/health")
        pc = health.get("pinecone") or {}
        st.markdown(f"**Vector store**  \n{pc.get('total_vectors', 0)} vectors indexed")
        if pc.get("error"):
            st.caption(f"⚠️ {pc['error']}")
        st.markdown(f"**BM25 chunks**: {health.get('bm25_chunks', 0)}")
        st.markdown(f"**Documents**: {health.get('mongo_docs', 0)}")
        st.markdown(f"**Conversations**: {health.get('mongo_conversations', 0)}")
        lf = "connected" if health.get("langfuse_configured") else "not configured"
        st.markdown(f"**Langfuse**: {lf}")
        if health.get("auth_required") and not API_KEY:
            st.warning("Backend requires an API key. Set RAG_API_KEY for this app.")
    except API_ERRORS as e:
        st.error(f"Backend not reachable: {err_text(e)}")

    st.markdown("---")
    if st.button("Seed sample documents", key="btn-seed"):
        try:
            with st.spinner("Ingesting sample corpus..."):
                res = api_post("/documents/seed")
            st.success(f"Seeded {len(res['ingested'])} documents")
            st.rerun()
        except API_ERRORS as e:
            st.error(f"Seed failed: {err_text(e)}")

    st.markdown("---")
    llm = (health or {}).get("llm") or {}
    st.caption(
        f"Groq · {llm.get('model', 'openai/gpt-oss-120b')} · "
        f"MiniLM embeddings (local) · Pinecone · Langfuse · RAGAS"
    )


# ============ HEADER ============
st.markdown(
    """
<div style="display:flex; align-items:flex-end; justify-content:space-between; margin-bottom: 4px;">
  <div>
    <div style="font-size:12px; letter-spacing:.16em; text-transform:uppercase; color:#7a7570;">The Eval-First RAG</div>
    <h1 style="margin:0; font-size: 44px;">Ask. Retrieve. <span style="color:#e85d3a;">Verify.</span></h1>
    <div style="color:#3d4046; font-size:15px; max-width: 680px; margin-top:6px;">
      Every answer is grounded in retrieved chunks with citations, and scored on Faithfulness,
      Answer Relevancy, and Context Precision — because "it returned something" isn't proof it's right.
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)
st.markdown("")

tab_chat, tab_docs, tab_eval, tab_history = st.tabs(
    ["💬  Chat", "📚  Documents", "📊  Evaluation Dashboard", "🗂  Query History"]
)

# ============ CHAT TAB ============
with tab_chat:
    col_q, col_opts = st.columns([3, 1])
    with col_q:
        query = st.text_area(
            "Ask a question about the indexed documents",
            key="query-input",
            placeholder="e.g. What is the retention period for Confidential-tier data?",
            height=90,
        )
    with col_opts:
        mode = st.selectbox("Retrieval mode", ["hybrid", "dense", "keyword"], index=0, key="mode-select")
        top_k = st.slider("Top-K chunks", 1, 10, 5, key="topk-slider")
        submit = st.button("Ask", key="ask-btn", use_container_width=True)

    if submit and query.strip():
        res = None
        try:
            with st.spinner("Retrieving & generating..."):
                res = api_post(
                    "/query",
                    json={"query": query.strip(), "top_k": top_k, "mode": mode},
                )
        except API_ERRORS as e:
            st.error(err_text(e))

        if res:
            # escape(): the answer is model output and must never be treated as markup
            st.markdown(
                f'<div class="answer-box">{html.escape(res.get("answer", ""))}</div>',
                unsafe_allow_html=True,
            )
            meta_col1, meta_col2, meta_col3, meta_col4 = st.columns(4)
            meta_col1.markdown(
                f'<span class="badge">mode: {html.escape(str(res.get("mode", "")))}</span>',
                unsafe_allow_html=True,
            )
            meta_col2.markdown(
                f'<span class="badge">latency: {int(res.get("latency_ms") or 0)} ms</span>',
                unsafe_allow_html=True,
            )
            meta_col3.markdown(
                f'<span class="badge">model: {html.escape(str(res.get("model", "")))}</span>',
                unsafe_allow_html=True,
            )
            if res.get("trace_id"):
                meta_col4.markdown(
                    f'<a href="{html.escape(LANGFUSE_UI)}" target="_blank" rel="noopener noreferrer" '
                    f'style="text-decoration:none;"><span class="badge ok">Langfuse trace ↗</span></a>',
                    unsafe_allow_html=True,
                )

            st.markdown("### Retrieved context")
            for i, c in enumerate(res.get("contexts") or [], 1):
                meta = c.get("metadata") or {}
                src = c.get("source") or meta.get("source") or "unknown"
                section = c.get("section") or meta.get("section") or ""
                score = c.get("score")
                header = f"[chunk {i}] {src}"
                if section:
                    header += f" · {section}"
                if isinstance(score, (int, float)):
                    header += f" · score={score:.3f}"
                # escape(): chunk text comes from uploaded documents
                st.markdown(
                    f'<div class="chunk-card"><div class="chunk-src">{html.escape(header)}</div>'
                    f"{html.escape(c.get('text', ''))}</div>",
                    unsafe_allow_html=True,
                )

# ============ DOCUMENTS TAB ============
with tab_docs:
    up_col, list_col = st.columns([1, 2])
    with up_col:
        st.markdown("#### Upload document")
        up = st.file_uploader("PDF or Markdown", type=["pdf", "md", "txt"], key="uploader")
        if up is not None and st.button("Ingest", key="ingest-btn"):
            with st.spinner("Chunking, embedding, upserting to Pinecone..."):
                files = {"file": (up.name, up.getvalue(), up.type or "application/octet-stream")}
                try:
                    r = requests.post(
                        f"{API}/documents/upload",
                        files=files,
                        timeout=600,
                        headers=_headers(),
                    )
                    r.raise_for_status()
                    data = r.json()
                    st.success(f"Ingested {data.get('n_chunks', 0)} chunks from {up.name}")
                    if data.get("warning"):
                        st.warning(data["warning"])
                    st.rerun()
                except API_ERRORS as e:
                    st.error(f"Failed: {err_text(e)}")

        st.markdown("#### Or use the sample corpus")
        st.caption("Ships with 4 example docs: HR remote-work policy, data-retention standard, Widget-3000 tech manual, incident-response runbook.")
        if st.button("Seed sample corpus", key="seed-btn-2"):
            try:
                with st.spinner("Seeding..."):
                    api_post("/documents/seed")
                st.success("Done")
                st.rerun()
            except API_ERRORS as e:
                st.error(f"Seed failed: {err_text(e)}")

    with list_col:
        st.markdown("#### Indexed documents")
        try:
            docs = api_get("/documents")["documents"]
        except API_ERRORS as e:
            docs = []
            st.error(f"Could not load documents: {err_text(e)}")
        if not docs:
            st.info("No documents indexed yet. Upload one or seed the sample corpus.")
        else:
            df = pd.DataFrame(docs)
            cols_order = [c for c in ["title", "source", "kind", "n_chunks", "updated_at"] if c in df.columns]
            st.dataframe(df[cols_order], use_container_width=True, hide_index=True)
            del_source = st.selectbox("Remove document", [""] + [d["source"] for d in docs], key="del-select")
            if del_source and st.button(f"Delete {del_source}", key="del-btn"):
                try:
                    # quote(): filenames may contain spaces or reserved characters
                    api_delete(f"/documents/{quote(del_source, safe='')}")
                    st.success("Deleted")
                    st.rerun()
                except API_ERRORS as e:
                    st.error(f"Delete failed: {err_text(e)}")

# ============ EVALUATION TAB ============
with tab_eval:
    st.markdown("#### Run evaluation")
    ec1, ec2, ec3 = st.columns([1.2, 1, 2])
    with ec1:
        scope = st.selectbox(
            "Scope",
            ["testset", "recent"],
            format_func=lambda s: "Golden test-set" if s == "testset" else "Last N user queries",
            key="scope-select",
        )
    with ec2:
        limit = st.number_input("Limit", 1, 100, 8, key="limit-input")
    with ec3:
        st.markdown("")
        st.markdown("")
        run_btn = st.button("Run RAGAS evaluation", key="eval-run-btn", use_container_width=True)

    if run_btn:
        res = None
        with st.spinner("Running Faithfulness · Answer Relevancy · Context Precision (this may take a while)…"):
            try:
                res = run_eval_in_background(scope, int(limit))
            except API_ERRORS as e:
                st.error(f"Eval failed: {err_text(e)}")
        if res:
            agg = res.get("aggregate") or {}
            m1, m2, m3, m4 = st.columns(4)
            for col, label, key in (
                (m1, "Faithfulness", "faithfulness"),
                (m2, "Answer Relevancy", "answer_relevancy"),
                (m3, "Context Precision", "context_precision"),
            ):
                col.markdown(
                    f'<div class="metric-card"><div class="metric-label">{label}</div>'
                    f'<div class="metric-value">{fmt_metric(agg.get(key))}</div></div>',
                    unsafe_allow_html=True,
                )
            m4.markdown(
                f'<div class="metric-card"><div class="metric-label">Samples · Duration</div>'
                f'<div class="metric-value">{agg.get("n_samples", 0)} · {agg.get("duration_s", 0)}s</div></div>',
                unsafe_allow_html=True,
            )
            # Golden-set metrics: only populated for test-set runs.
            g1, g2, g3, g4 = st.columns(4)
            for col, label, key in (
                (g1, "Answer Correctness", "answer_correctness"),
                (g2, "Context Recall", "context_recall"),
                (g3, "Retrieval Hit Rate", "retrieval_hit_rate"),
                (g4, "Refusal Accuracy", "refusal_accuracy"),
            ):
                col.markdown(
                    f'<div class="metric-card"><div class="metric-label">{label}</div>'
                    f'<div class="metric-value">{fmt_metric(agg.get(key))}</div></div>',
                    unsafe_allow_html=True,
                )
            st.markdown("### Per-question scores")
            st.dataframe(pd.DataFrame(res.get("per_row") or []), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("#### Historical eval runs")
    try:
        runs = api_get("/evaluations")["runs"]
    except API_ERRORS:
        runs = []
    if not runs:
        st.info("No evaluations yet. Run one above.")
    else:
        rdf = pd.DataFrame(runs)
        keep = [c for c in ["created_at", "scope", "n_samples", "faithfulness",
                            "answer_relevancy", "context_precision", "answer_correctness",
                            "context_recall", "retrieval_hit_rate", "retrieval_mrr",
                            "refusal_accuracy", "duration_s"] if c in rdf.columns]
        st.dataframe(rdf[keep], use_container_width=True, hide_index=True)

        if {"faithfulness", "answer_relevancy", "context_precision"}.issubset(rdf.columns):
            chart_df = rdf[["created_at", "faithfulness", "answer_relevancy", "context_precision"]].copy()
            chart_df["created_at"] = pd.to_datetime(chart_df["created_at"], errors="coerce")
            chart_df = chart_df.dropna(subset=["created_at"]).sort_values("created_at").set_index("created_at")
            if not chart_df.empty:
                st.markdown("### Metric trends")
                st.line_chart(chart_df)

# ============ HISTORY TAB ============
with tab_history:
    try:
        convs = api_get("/conversations", limit=50)["conversations"]
    except API_ERRORS as e:
        convs = []
        st.error(f"Could not load history: {err_text(e)}")
    if not convs:
        st.info("No queries yet. Head to the Chat tab.")
    else:
        for c in convs:
            title = f"[{c.get('mode', '?')}] {(c.get('query') or '')[:90]}   —   {c.get('latency_ms', '?')} ms"
            with st.expander(title):
                # st.text(): renders model output literally, no markup interpretation
                st.markdown("**Answer:**")
                st.text(c.get("answer") or "")
                st.caption(
                    f"model={c.get('model')} · created={c.get('created_at')} · "
                    f"trace_id={c.get('trace_id') or '—'}"
                )
                if c.get("trace_id"):
                    st.markdown(f"[Open in Langfuse ↗]({LANGFUSE_UI})")
