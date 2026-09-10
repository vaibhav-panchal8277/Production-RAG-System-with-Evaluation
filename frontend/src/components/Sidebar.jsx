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
  const { data: h } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 8000,
  });

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
          v0.1 · {h?.llm?.model ?? "…"}
        </div>
      </div>

      {/* nav */}
      <nav className="py-2">
        {NAV.map((n) => (
          <button
            key={n.id}
            data-testid={`nav-${n.id}`}
            onClick={() => setActive(n.key)}
            className={`w-full text-left px-5 py-2.5 font-mono text-xs uppercase tracking-[0.14em] transition-colors border-l-2 ${
              active === n.key
                ? "bg-white/[0.04] text-white border-white"
                : "text-neutral-500 hover:text-white hover:bg-white/[0.02] border-transparent"
            }`}
          >
            {n.label}
          </button>
        ))}
      </nav>

      <div className="mx-5 border-t border-white/10 my-3" />

      {/* controls */}
      <div className="px-5 flex flex-col gap-4 flex-1 overflow-y-auto pb-4">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-neutral-500 mb-2">
            Retrieval Mode
          </div>
          <RadioGroup
            value={controls.mode}
            onValueChange={(v) => setControls((c) => ({ ...c, mode: v }))}
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
          <div className="flex items-baseline justify-between mb-2">
            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-neutral-500">
              Top-K
            </div>
            <div className="font-mono text-sm text-white" data-testid="top-k-value">
              {controls.topK}
            </div>
          </div>
          <Slider
            data-testid="top-k-slider"
            min={1}
            max={10}
            step={1}
            value={[controls.topK]}
            onValueChange={([v]) => setControls((c) => ({ ...c, topK: v }))}
            className="slider-sharp"
          />
        </div>

        <div className="mt-2">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-neutral-500 mb-3">
            Live System
          </div>
          <StatRow label="vectors" value={h?.pinecone?.total_vectors ?? "—"} />
          <StatRow label="documents" value={h?.mongo_docs ?? "—"} />
          <StatRow label="queries" value={h?.mongo_conversations ?? "—"} />
          <StatRow label="pinecone dim" value={h?.pinecone?.dimension ?? "—"} />
          <div className="flex items-center justify-between py-1">
            <div className="font-mono text-xs text-neutral-500">langfuse</div>
            <div className="flex items-center gap-2">
              <span
                className={`status-dot ${lfOk ? "" : "err"}`}
                data-testid="langfuse-status-dot"
              />
              <span className="font-mono text-xs text-neutral-300">
                {lfOk ? "connected" : "off"}
              </span>
            </div>
          </div>
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
  return (
    <div className="flex items-center justify-between py-1">
      <div className="font-mono text-xs text-neutral-500">{label}</div>
      <div className="font-mono text-xs text-white tabular-nums">{value}</div>
    </div>
  );
}
