"""Streamlit frontend for the RAG Evaluation System."""
import os
import time
import requests
import pandas as pd
import streamlit as st

# ============ CONFIG ============
BACKEND = os.environ.get("BACKEND_INTERNAL_URL", "http://localhost:8001")
API = f"{BACKEND}/api"
LANGFUSE_UI = os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com")

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
    padding: 12px 16px; margin: 8px 0; font-size: 14px; }
.chunk-src { font-size: 11px; text-transform:uppercase; letter-spacing:.06em; color:#7a7570; }
.answer-box { background:#111214; color:#f6f2ea; padding: 18px 22px; border-radius: 12px;
    line-height: 1.55; font-size: 15px; }
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
def api_get(path, **params):
    r = requests.get(f"{API}{path}", params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def api_post(path, json=None, files=None):
    r = requests.post(f"{API}{path}", json=json, files=files, timeout=300)
    r.raise_for_status()
    return r.json()


def api_delete(path):
    r = requests.delete(f"{API}{path}", timeout=60)
    r.raise_for_status()
    return r.json()


def score_badge(v):
    if v is None:
        return '<span class="badge">n/a</span>'
    if v >= 0.8:
        klass = "ok"
    elif v >= 0.6:
        klass = "warn"
    else:
        klass = "err"
    return f'<span class="badge {klass}">{v:.2f}</span>'


# ============ SIDEBAR ============
with st.sidebar:
    st.markdown("### RAG Evaluation Lab")
    st.caption("Retrieval + generation with faithfulness scores you can actually point to.")
    st.markdown("---")
    try:
        h = api_get("/health")
        st.markdown(f"**Vector store**  \n{h['pinecone'].get('total_vectors', 0)} vectors indexed")
        st.markdown(f"**Documents**: {h['mongo_docs']}")
        st.markdown(f"**Conversations**: {h['mongo_conversations']}")
        lf = "connected" if h["langfuse_configured"] else "not configured"
        st.markdown(f"**Langfuse**: {lf}")
    except Exception as e:
        st.error(f"Backend not reachable: {e}")

    st.markdown("---")
    if st.button("Seed sample documents", key="btn-seed"):
        with st.spinner("Ingesting sample corpus..."):
            res = api_post("/documents/seed")
        st.success(f"Seeded {len(res['ingested'])} documents")
        st.rerun()

    st.markdown("---")
    st.caption("Emergent proxy · OpenAI gpt-5.4-mini · MiniLM embeddings (local) · Pinecone · Langfuse · RAGAS")


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
        try:
            with st.spinner("Retrieving & generating..."):
                res = api_post("/query", json={"query": query.strip(), "top_k": top_k, "mode": mode})
        except requests.HTTPError as e:
            try:
                st.error(e.response.json().get("detail", str(e)))
            except Exception:
                st.error(str(e))
            res = None
        except Exception as e:
            st.error(str(e))
            res = None

        if res:
            st.markdown(f'<div class="answer-box">{res["answer"]}</div>', unsafe_allow_html=True)
            meta_col1, meta_col2, meta_col3, meta_col4 = st.columns(4)
            meta_col1.markdown(f'<span class="badge">mode: {res["mode"]}</span>', unsafe_allow_html=True)
            meta_col2.markdown(f'<span class="badge">latency: {res["latency_ms"]} ms</span>', unsafe_allow_html=True)
            meta_col3.markdown(f'<span class="badge">model: {res["model"]}</span>', unsafe_allow_html=True)
            if res.get("trace_id"):
                meta_col4.markdown(
                    f'<a href="{LANGFUSE_UI}" target="_blank" style="text-decoration:none;"><span class="badge ok">Langfuse trace ↗</span></a>',
                    unsafe_allow_html=True,
                )

            st.markdown("### Retrieved context")
            for i, c in enumerate(res["contexts"], 1):
                src = c.get("source") or "unknown"
                section = c.get("section") or ""
                score = c.get("score")
                header = f"[chunk {i}] {src}"
                if section:
                    header += f" · {section}"
                if score is not None:
                    header += f" · score={score:.3f}"
                st.markdown(
                    f'<div class="chunk-card"><div class="chunk-src">{header}</div>{c["text"]}</div>',
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
                    r = requests.post(f"{API}/documents/upload", files=files, timeout=300)
                    r.raise_for_status()
                    st.success(f"Ingested {r.json().get('n_chunks',0)} chunks from {up.name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")

        st.markdown("#### Or use the sample corpus")
        st.caption("Ships with 4 example docs: HR remote-work policy, data-retention standard, Widget-3000 tech manual, incident-response runbook.")
        if st.button("Seed sample corpus", key="seed-btn-2"):
            with st.spinner("Seeding..."):
                api_post("/documents/seed")
            st.success("Done")
            st.rerun()

    with list_col:
        st.markdown("#### Indexed documents")
        docs = api_get("/documents")["documents"]
        if not docs:
            st.info("No documents indexed yet. Upload one or seed the sample corpus.")
        else:
            df = pd.DataFrame(docs)
            cols_order = [c for c in ["title", "source", "kind", "n_chunks", "updated_at"] if c in df.columns]
            st.dataframe(df[cols_order], use_container_width=True, hide_index=True)
            del_source = st.selectbox("Remove document", [""] + [d["source"] for d in docs], key="del-select")
            if del_source and st.button(f"Delete {del_source}", key="del-btn"):
                api_delete(f"/documents/{del_source}")
                st.success("Deleted")
                st.rerun()

# ============ EVALUATION TAB ============
with tab_eval:
    st.markdown("#### Run evaluation")
    ec1, ec2, ec3 = st.columns([1.2, 1, 2])
    with ec1:
        scope = st.selectbox(
            "Scope",
            ["testset", "recent"],
            format_func=lambda s: "Golden test-set (8 Q&A)" if s == "testset" else "Last N user queries",
            key="scope-select",
        )
    with ec2:
        limit = st.number_input("Limit", 1, 100, 8, key="limit-input")
    with ec3:
        st.markdown("")
        st.markdown("")
        run_btn = st.button("Run RAGAS evaluation", key="eval-run-btn", use_container_width=True)

    if run_btn:
        with st.spinner("Running Faithfulness · Answer Relevancy · Context Precision (this may take 30–90s)…"):
            try:
                res = api_post("/evaluations/run", json={"scope": scope, "limit": int(limit)})
            except Exception as e:
                st.error(f"Eval failed: {e}")
                res = None
        if res:
            agg = res["aggregate"]
            m1, m2, m3, m4 = st.columns(4)
            m1.markdown(
                f'<div class="metric-card"><div class="metric-label">Faithfulness</div>'
                f'<div class="metric-value">{(agg["faithfulness"] or 0):.2f}</div></div>',
                unsafe_allow_html=True,
            )
            m2.markdown(
                f'<div class="metric-card"><div class="metric-label">Answer Relevancy</div>'
                f'<div class="metric-value">{(agg["answer_relevancy"] or 0):.2f}</div></div>',
                unsafe_allow_html=True,
            )
            m3.markdown(
                f'<div class="metric-card"><div class="metric-label">Context Precision</div>'
                f'<div class="metric-value">{(agg["context_precision"] or 0):.2f}</div></div>',
                unsafe_allow_html=True,
            )
            m4.markdown(
                f'<div class="metric-card"><div class="metric-label">Samples · Duration</div>'
                f'<div class="metric-value">{agg["n_samples"]} · {agg["duration_s"]}s</div></div>',
                unsafe_allow_html=True,
            )
            st.markdown("### Per-question scores")
            df = pd.DataFrame(res["per_row"])
            st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("#### Historical eval runs")
    try:
        runs = api_get("/evaluations")["runs"]
    except Exception:
        runs = []
    if not runs:
        st.info("No evaluations yet. Run one above.")
    else:
        rdf = pd.DataFrame(runs)
        # keep only summary columns
        keep = [c for c in ["created_at", "scope", "n_samples", "faithfulness",
                            "answer_relevancy", "context_precision", "duration_s"] if c in rdf.columns]
        st.dataframe(rdf[keep], use_container_width=True, hide_index=True)

        # Trend chart
        if {"faithfulness", "answer_relevancy", "context_precision"}.issubset(rdf.columns):
            chart_df = rdf[["created_at", "faithfulness", "answer_relevancy", "context_precision"]].copy()
            chart_df["created_at"] = pd.to_datetime(chart_df["created_at"], errors="coerce")
            chart_df = chart_df.sort_values("created_at").set_index("created_at")
            st.markdown("### Metric trends")
            st.line_chart(chart_df)

# ============ HISTORY TAB ============
with tab_history:
    convs = api_get("/conversations", limit=50)["conversations"]
    if not convs:
        st.info("No queries yet. Head to the Chat tab.")
    else:
        for c in convs:
            with st.expander(f"[{c.get('mode','?')}] {c['query'][:90]}   —   {c.get('latency_ms','?')} ms"):
                st.markdown(f"**Answer:** {c['answer']}")
                st.caption(f"model={c.get('model')} · created={c.get('created_at')} · trace_id={c.get('trace_id') or '—'}")
                if c.get("trace_id"):
                    st.markdown(f"[Open in Langfuse ↗]({LANGFUSE_UI})")
