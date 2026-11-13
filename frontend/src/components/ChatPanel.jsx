import React, { useState, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import CitedText from "@/components/CitedText";
import { toast } from "sonner";

export default function ChatPanel({ controls }) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState(null);
  const [activeChunk, setActiveChunk] = useState(null);
  const qc = useQueryClient();

  const runQuery = useMutation({
    mutationFn: (q) =>
      api.query({ query: q, top_k: controls.topK, mode: controls.mode }),
    onSuccess: (data) => {
      setResult(data);
      qc.invalidateQueries({ queryKey: ["health"] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e) => {
      const msg = e?.response?.data?.detail || e.message || "Query failed";
      toast.error(msg);
    },
  });

  const suggestions = useMemo(
    () => [
      "What is the retention period for Confidential-tier data?",
      "What does fault code E03 on the Widget-3000 mean?",
      "What is the annual reimbursement limit for ergonomic accessories?",
      "How quickly must SEV-1 incidents be acknowledged?",
    ],
    []
  );

  const submit = () => {
    if (!query.trim()) return;
    runQuery.mutate(query.trim());
  };

  return (
    <div className="grid grid-cols-12 gap-0 h-full">
      {/* Left: chat */}
      <div className="col-span-7 border-r border-white/10 flex flex-col min-h-screen">
        <div className="px-8 pt-8 pb-4 border-b border-white/10">
          <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500">
            Query interface
          </div>
          <h1 className="font-heading text-4xl font-black leading-none mt-2 text-white">
            Ask the corpus.
          </h1>
          <div className="text-sm text-neutral-400 mt-3 max-w-lg">
            Answers are constrained to retrieved chunks with inline{" "}
            <span className="citation-marker">[N]</span> citations. Hover a citation to
            highlight the source chunk on the right.
          </div>
        </div>

        <div className="px-8 py-5 border-b border-white/10">
          <Textarea
            data-testid="query-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
            }}
            placeholder="Type your question. ⌘/Ctrl + Enter to submit."
            className="min-h-[96px] bg-[#111114] border border-white/10 text-white rounded-none font-body focus:border-white/40 focus:ring-0 resize-none"
          />
          <div className="flex flex-wrap items-center justify-between gap-3 mt-3">
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  data-testid={`suggestion-${i}`}
                  onClick={() => setQuery(s)}
                  className="font-mono text-[11px] uppercase tracking-wider px-2 py-1 border border-white/10 text-neutral-400 hover:border-white hover:text-white transition-colors"
                >
                  {s.slice(0, 42) + (s.length > 42 ? "…" : "")}
                </button>
              ))}
            </div>
            <Button
              data-testid="ask-button"
              onClick={submit}
              disabled={runQuery.isPending || !query.trim()}
              className="rounded-none bg-white text-black hover:bg-neutral-200 font-mono text-xs uppercase tracking-[0.18em] px-6 h-10"
            >
              {runQuery.isPending ? "Thinking…" : "Ask →"}
            </Button>
          </div>
        </div>

        <div className="flex-1 px-8 py-6 overflow-y-auto">
          {runQuery.isPending && (
            <div className="font-mono text-xs text-neutral-500 animate-pulse">
              retrieving · generating · logging trace…
            </div>
          )}
          {!result && !runQuery.isPending && (
            <div className="font-mono text-xs text-neutral-600 uppercase tracking-widest">
              waiting for input…
            </div>
          )}
          {result && (
            <div>
              <div
                data-testid="answer-box"
                className="border-l-2 border-white pl-4 py-1 text-[15px] leading-relaxed text-white"
              >
                <CitedText
                  text={result.answer}
                  activeChunk={activeChunk}
                  setActiveChunk={setActiveChunk}
                />
              </div>

              <div className="flex flex-wrap gap-2 mt-5">
                <MetaTag label="mode" value={result.mode} />
                <MetaTag label="latency" value={`${result.latency_ms} ms`} />
                <MetaTag label="model" value={result.model} />
                {result.trace_id && (
                  <a
                    href={`${process.env.REACT_APP_LANGFUSE_URL || "https://us.cloud.langfuse.com"}/trace/${result.trace_id}`}
                    target="_blank"
                    rel="noreferrer"
                    data-testid="langfuse-trace-link"
                    className="font-mono text-[10px] uppercase tracking-widest px-2 py-1 border border-blue-500/30 bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 transition-colors"
                  >
                    langfuse trace ↗
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right: retrieved chunks */}
      <div className="col-span-5 flex flex-col min-h-screen">
        <div className="px-8 pt-8 pb-4 border-b border-white/10">
          <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500">
            Retrieved context
          </div>
          <div className="font-heading text-xl font-bold text-white mt-2">
            {result ? `${result.contexts.length} chunks` : "—"}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-3">
          {(result?.contexts || []).map((c, i) => {
            const idx = i + 1;
            return (
              <div
                key={c.id}
                data-testid={`chunk-card-${idx}`}
                onMouseEnter={() => setActiveChunk(idx)}
                onMouseLeave={() => setActiveChunk(null)}
                className={`chunk-card border border-white/10 bg-[#111114] p-4 transition-colors ${
                  activeChunk === idx ? "highlight" : ""
                }`}
              >
                <div className="flex items-center justify-between mb-2 gap-3">
                  <div className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 truncate">
                    <span className="text-white">[{idx}]</span>{" "}
                    {c.source || "unknown"}
                    {c.section ? ` · ${c.section}` : ""}
                  </div>
                  <div className="font-mono text-[10px] text-neutral-500 tabular-nums shrink-0">
                    {c.score != null ? c.score.toFixed(3) : ""}
                  </div>
                </div>
                <div className="text-[13px] text-neutral-300 leading-relaxed max-h-56 overflow-y-auto whitespace-pre-wrap">
                  {c.text}
                </div>
              </div>
            );
          })}
          {!result && (
            <div className="font-mono text-[11px] text-neutral-600 uppercase tracking-widest">
              chunks appear here after retrieval
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MetaTag({ label, value }) {
  return (
    <div className="font-mono text-[10px] uppercase tracking-widest border border-white/10 bg-white/[0.02] px-2 py-1 text-neutral-400">
      <span className="text-neutral-600">{label}:</span>{" "}
      <span className="text-white">{value}</span>
    </div>
  );
}
