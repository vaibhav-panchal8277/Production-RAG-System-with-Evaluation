import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Slider } from "@/components/ui/slider";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Label } from "@/components/ui/label";

const NAV = [
  { id: "chat", label: "01 · Ask", key: "chat" },
  { id: "docs", label: "02 · Corpus", key: "docs" },
  { id: "eval", label: "03 · Eval Dashboard", key: "eval" },
  { id: "history", label: "04 · History", key: "history" },
];

export default function Sidebar({ active, setActive, controls, setControls }) {
  const {
    data: h,
    isError,
    failureCount,
  } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 8000,
  });

  // Three honest states instead of bare dashes. The API scales to zero, so the
  // first load after a quiet period is slow (a pending request), not a failure.
  // A refused or failed request counts as unreachable; the periodic refetch
  // keeps retrying and flips back to "connected" once the API answers.
  const apiState = isError || failureCount >= 2 ? "error" : h ? "ok" : "loading";
  const lfOk = h?.langfuse_configured;

  return (
    <aside
      data-testid="sidebar"
      className="fixed top-0 left-0 h-screen w-[260px] border-r border-white/10 bg-[#0a0a0c] z-10 flex flex-col"
    >
      {/* header */}
      <div className="px-5 pt-6 pb-4 border-b border-white/10">
        <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500">
          Retrieval Lab
        </div>
        <div className="font-heading text-[22px] font-black leading-none mt-1 text-white">
          rag/eval
        </div>
        {/* Model comes from /health so it can't drift from what the backend runs. */}
        <div className="font-mono text-[10px] text-neutral-500 mt-2">
          v0.1 · {h?.llm?.model ?? "loading model…"}
        </div>
      </div>

      {/* nav */}
      <nav className="py-2" aria-label="Sections">
        {NAV.map((n) => {
          const isActive = active === n.key;
          return (
            <button
              key={n.id}
              type="button"
              data-testid={`nav-${n.id}`}
              aria-current={isActive ? "page" : undefined}
              onClick={() => setActive(n.key)}
              className={`w-full text-left px-5 py-2.5 font-mono text-xs uppercase tracking-[0.14em] transition-colors border-l-[3px] ${
                isActive
                  ? "bg-white/[0.09] text-white font-bold border-white"
                  : "text-neutral-500 hover:text-white hover:bg-white/[0.03] border-transparent"
              }`}
            >
              {n.label}
            </button>
          );
        })}
      </nav>

      <div className="mx-5 border-t border-white/10 my-3" />

      {/* controls */}
      <div className="px-5 flex flex-col gap-5 flex-1 overflow-y-auto pb-4">
        <div>
          <div
            id="mode-label"
            className="font-mono text-[10px] uppercase tracking-[0.14em] text-neutral-500 mb-2"
          >
            Retrieval Mode
          </div>
          <RadioGroup
            value={controls.mode}
            onValueChange={(v) => setControls((c) => ({ ...c, mode: v }))}
            aria-labelledby="mode-label"
            data-testid="mode-radio-group"
          >
            {["hybrid", "dense", "keyword"].map((m) => (
              <div key={m} className="flex items-center gap-2 py-0.5">
                <RadioGroupItem
                  value={m}
                  id={`mode-${m}`}
                  data-testid={`mode-radio-${m}`}
                  className="border-white/40 text-white"
                />
                <Label
                  htmlFor={`mode-${m}`}
                  className="font-mono text-xs text-neutral-300 cursor-pointer"
                >
                  {m}
                </Label>
              </div>
            ))}
          </RadioGroup>
        </div>

        <div>
          <div className="flex items-baseline justify-between">
            <div
              id="top-k-label"
              className="font-mono text-[10px] uppercase tracking-[0.14em] text-neutral-500"
            >
              Top-K
            </div>
            <div className="font-mono text-sm text-white" data-testid="top-k-value">
              {controls.topK}
            </div>
          </div>
          <div id="top-k-help" className="text-[11px] text-neutral-500 mt-0.5 mb-1">
            Chunks retrieved per question
          </div>
          <Slider
            data-testid="top-k-slider"
            min={1}
            max={10}
            step={1}
            value={[controls.topK]}
            onValueChange={([v]) => setControls((c) => ({ ...c, topK: v }))}
            thumbLabel="Top-K: chunks retrieved per question"
            aria-describedby="top-k-help"
          />
        </div>

        <div className="mt-1">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-neutral-500 mb-2">
            Live System
          </div>

          <div
            className="flex items-center gap-2 py-1"
            role="status"
            aria-live="polite"
            data-testid="api-status"
          >
            <span
              className={`status-dot ${
                apiState === "ok" ? "" : apiState === "loading" ? "warn" : "err"
              }`}
              aria-hidden="true"
            />
            <span className="font-mono text-xs text-neutral-200">
              {apiState === "ok"
                ? "API connected"
                : apiState === "loading"
                  ? "Connecting to API…"
                  : "API unavailable"}
            </span>
          </div>

          {apiState === "loading" && (
            <p className="text-[11px] leading-snug text-neutral-500 mt-1">
              The API sleeps when idle. The first load can take about 30 seconds.
            </p>
          )}
          {apiState === "error" && (
            <p className="text-[11px] leading-snug text-neutral-500 mt-1">
              Can't reach the API right now. Retrying automatically.
            </p>
          )}

          {apiState === "ok" && (
            <dl className="mt-1">
              <StatRow label="Vectors indexed" value={h.pinecone?.total_vectors} />
              <StatRow label="Documents" value={h.mongo_docs} />
              <StatRow label="Queries logged" value={h.mongo_conversations} />
              <StatRow label="Embedding dim" value={h.pinecone?.dimension} />
              <div className="flex items-center justify-between py-1">
                <dt className="font-mono text-xs text-neutral-500">Tracing</dt>
                <dd className="flex items-center gap-2 m-0">
                  <span
                    className={`status-dot ${lfOk ? "" : "warn"}`}
                    data-testid="langfuse-status-dot"
                    aria-hidden="true"
                  />
                  <span className="font-mono text-xs text-neutral-300">
                    {lfOk ? "Connected" : "Not configured"}
                  </span>
                </dd>
              </div>
            </dl>
          )}
        </div>
      </div>

      <div className="px-5 py-3 border-t border-white/10 font-mono text-[10px] leading-relaxed text-neutral-600">
        groq · pinecone · minilm ·<br />
        ragas · langfuse · fastapi
      </div>
    </aside>
  );
}

function StatRow({ label, value }) {
  const missing = value === null || value === undefined;
  return (
    <div className="flex items-center justify-between py-1">
      <dt className="font-mono text-xs text-neutral-500">{label}</dt>
      <dd
        className={`font-mono text-xs tabular-nums m-0 ${
          missing ? "text-neutral-600" : "text-white"
        }`}
      >
        {missing ? "n/a" : value}
      </dd>
    </div>
  );
}
