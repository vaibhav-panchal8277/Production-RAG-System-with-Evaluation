import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export default function HistoryPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ["conversations"],
    queryFn: () => api.listConversations(100),
  });

  const exportJson = () => {
    const list = data?.conversations || [];
    const blob = new Blob([JSON.stringify(list, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `rag-conversations-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportCsv = () => {
    const list = data?.conversations || [];
    if (!list.length) return;
    const headers = ["id", "created_at", "mode", "query", "answer", "latency_ms", "trace_id"];
    const rows = list.map((c) =>
      [
        c.id || "",
        c.created_at || "",
        c.mode || "",
        `"${(c.query || "").replace(/"/g, '""')}"`,
        `"${(c.answer || "").replace(/"/g, '""')}"`,
        c.latency_ms || "",
        c.trace_id || "",
      ].join(",")
    );
    const csvContent = [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `rag-conversations-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen">
      <div className="px-8 pt-8 pb-6 border-b border-white/10 flex items-center justify-between">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500">
            Query log
          </div>
          <h1 className="font-heading text-4xl font-black leading-none mt-2 text-white">
            History.
          </h1>
          <div className="text-sm text-neutral-400 mt-3 max-w-2xl">
            Every query is persisted in MongoDB and mirrored to Langfuse as a trace with
            retrieve + generate spans.
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={exportCsv}
            data-testid="export-csv-btn"
            className="font-mono text-xs uppercase tracking-widest px-4 py-2 border border-white/20 bg-white/5 text-white hover:bg-white/10 transition-colors"
          >
            Export CSV
          </button>
          <button
            onClick={exportJson}
            data-testid="export-json-btn"
            className="font-mono text-xs uppercase tracking-widest px-4 py-2 border border-white/20 bg-white/5 text-white hover:bg-white/10 transition-colors"
          >
            Export JSON
          </button>
        </div>
      </div>

      <div className="p-8">
        {isLoading ? (
          <div className="font-mono text-xs text-neutral-500">loading…</div>
        ) : !data?.conversations?.length ? (
          <div className="font-mono text-xs text-neutral-600 uppercase tracking-widest">
            no queries yet — head to Ask.
          </div>
        ) : (
          <table className="w-full text-sm" data-testid="history-table">
            <thead>
              <tr className="border-b border-white/10 text-left">
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6">
                  Time
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6">
                  Mode
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6">
                  Query
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6">
                  Answer
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6 text-right">
                  Latency
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 text-right">
                  Trace
                </th>
              </tr>
            </thead>
            <tbody>
              {data.conversations.map((c) => (
                <tr key={c.id} className="border-b border-white/5 align-top hover:bg-white/[0.02]">
                  <td className="py-3 pr-6 font-mono text-xs text-neutral-500 whitespace-nowrap">
                    {c.created_at?.slice(0, 19).replace("T", " ")}
                  </td>
                  <td className="py-3 pr-6 font-mono text-xs text-neutral-300 uppercase">
                    {c.mode || "—"}
                  </td>
                  <td className="py-3 pr-6 text-white max-w-[26ch] truncate">{c.query}</td>
                  <td className="py-3 pr-6 text-neutral-300 max-w-[42ch] truncate">
                    {c.answer}
                  </td>
                  <td className="py-3 pr-6 font-mono text-xs text-neutral-400 text-right tabular-nums">
                    {c.latency_ms ?? "—"} ms
                  </td>
                  <td className="py-3 text-right">
                    {c.trace_id ? (
                      <a
                        href={`${process.env.REACT_APP_LANGFUSE_URL || "https://us.cloud.langfuse.com"}/trace/${c.trace_id}`}
                        target="_blank"
                        rel="noreferrer"
                        className="font-mono text-[10px] uppercase tracking-widest px-2 py-1 border border-blue-500/30 bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 transition-colors"
                      >
                        open ↗
                      </a>
                    ) : (
                      <span className="font-mono text-[10px] text-neutral-600">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
