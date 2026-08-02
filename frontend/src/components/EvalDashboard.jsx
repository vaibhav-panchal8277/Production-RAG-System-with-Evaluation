import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from "recharts";

const METRIC_COLORS = {
  faithfulness: "#22c55e",
  answer_relevancy: "#eab308",
  context_precision: "#3b82f6",
};

const scoreColor = (v) => {
  if (v == null) return "text-neutral-500";
  if (v >= 0.8) return "text-green-400";
  if (v >= 0.6) return "text-yellow-400";
  return "text-red-400";
};

export default function EvalDashboard() {
  const [scope, setScope] = useState("testset");
  const [limit, setLimit] = useState(45);
  const [latest, setLatest] = useState(null);
  const qc = useQueryClient();

  const testsetQ = useQuery({ queryKey: ["testset"], queryFn: api.testset });
  const testsetSize = testsetQ.data?.testset?.length ?? 45;
  const runs = useQuery({ queryKey: ["evals"], queryFn: () => api.listEvals(30) });

  const runEval = useMutation({
    mutationFn: () => api.runEval({ scope, limit: parseInt(limit, 10) }),
    onSuccess: (r) => {
      setLatest(r);
      toast.success(`Eval complete · ${r.aggregate.n_samples} samples`);
      qc.invalidateQueries({ queryKey: ["evals"] });
    },
    onError: (e) =>
      toast.error(e?.response?.data?.detail || e.message || "Eval failed"),
  });

  const agg = latest?.aggregate || runs.data?.runs?.[0] || null;

  const chartData = (runs.data?.runs || [])
    .slice()
    .reverse()
    .map((r) => ({
      time: (r.created_at || "").slice(11, 16),
      faithfulness: r.faithfulness,
      answer_relevancy: r.answer_relevancy,
      context_precision: r.context_precision,
    }));

  return (
    <div className="min-h-screen">
      <div className="px-8 pt-8 pb-6 border-b border-white/10">
        <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500">
          Evaluation Layer
        </div>
        <h1 className="font-heading text-4xl font-black leading-none mt-2 text-white">
          The number you can point to.
        </h1>
        <div className="text-sm text-neutral-400 mt-3 max-w-2xl">
          RAGAS Faithfulness · Answer Relevancy · Context Precision, computed on the golden
          test-set or your recent queries. Every metric is pushed as a Langfuse score,
          traceable per-query.
        </div>
      </div>

      {/* Controls */}
      <div className="grid grid-cols-12 border-b border-white/10">
        <div className="col-span-3 p-6 border-r border-white/10">
          <div className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 mb-2">
            Scope
          </div>
          <Select value={scope} onValueChange={setScope}>
            <SelectTrigger
              data-testid="scope-select"
              className="rounded-none bg-[#111114] border-white/10 text-white h-10 font-mono text-xs"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#111114] border-white/10 text-white">
              <SelectItem value="testset" data-testid="scope-testset">
                Golden test-set ({testsetSize} Q&amp;A)
              </SelectItem>
              <SelectItem value="recent" data-testid="scope-recent">
                Recent user queries
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="col-span-2 p-6 border-r border-white/10">
          <div className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 mb-2">
            Limit
          </div>
          <input
            data-testid="limit-input"
            type="number"
            min={1}
            max={100}
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            className="w-full bg-[#111114] border border-white/10 text-white font-mono text-sm px-3 h-10 focus:outline-none focus:border-white/40"
          />
        </div>
        <div className="col-span-7 p-6 flex items-end justify-end">
          <Button
            data-testid="run-eval-btn"
            onClick={() => runEval.mutate()}
            disabled={runEval.isPending}
            className="rounded-none bg-white text-black hover:bg-neutral-200 font-mono text-xs uppercase tracking-[0.18em] h-10 px-6"
          >
            {runEval.isPending ? "Evaluating…" : "Run evaluation →"}
          </Button>
        </div>
      </div>

      {/* Metric bento */}
      <div className="grid grid-cols-3 border-b border-white/10">
        <MetricCard
          label="Faithfulness"
          value={agg?.faithfulness}
          testId="metric-faithfulness"
          hint="answer supported by retrieved context"
          color={METRIC_COLORS.faithfulness}
        />
        <MetricCard
          label="Answer Relevancy"
          value={agg?.answer_relevancy}
          testId="metric-answer-relevancy"
          hint="does the answer address the question"
          color={METRIC_COLORS.answer_relevancy}
          bordered
        />
        <MetricCard
          label="Context Precision"
          value={agg?.context_precision}
          testId="metric-context-precision"
          hint="was the retrieved context actually relevant"
          color={METRIC_COLORS.context_precision}
        />
      </div>

      {/* Trend chart */}
      <div className="border-b border-white/10 p-8">
        <div className="flex items-center justify-between mb-4">
          <div className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
            Metric trends · last {chartData.length} runs
          </div>
          <div className="font-mono text-[10px] text-neutral-600">
            {runs.data?.runs?.length ?? 0} historical run{(runs.data?.runs?.length ?? 0) === 1 ? "" : "s"}
          </div>
        </div>
        <div className="h-[280px]" data-testid="trend-chart">
          {chartData.length === 0 ? (
            <div className="font-mono text-xs text-neutral-600 uppercase tracking-widest">
              no evaluation runs yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" strokeDasharray="3 3" />
                <XAxis
                  dataKey="time"
                  stroke="#71717a"
                  fontSize={11}
                  tickLine={false}
                  axisLine={{ stroke: "rgba(255,255,255,0.15)" }}
                />
                <YAxis
                  stroke="#71717a"
                  fontSize={11}
                  tickLine={false}
                  domain={[0, 1]}
                  axisLine={{ stroke: "rgba(255,255,255,0.15)" }}
                />
                <Tooltip
                  contentStyle={{
                    background: "#111114",
                    border: "1px solid rgba(255,255,255,0.2)",
                    borderRadius: 0,
                    fontSize: 12,
                    fontFamily: "JetBrains Mono",
                  }}
                  labelStyle={{ color: "#fff" }}
                />
                <Legend
                  wrapperStyle={{
                    fontFamily: "JetBrains Mono",
                    fontSize: 10,
                    textTransform: "uppercase",
                    letterSpacing: "0.1em",
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="faithfulness"
                  stroke={METRIC_COLORS.faithfulness}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="answer_relevancy"
                  stroke={METRIC_COLORS.answer_relevancy}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="context_precision"
                  stroke={METRIC_COLORS.context_precision}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Per-row */}
      {latest && (
        <div className="p-8 border-b border-white/10">
          <div className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 mb-4">
            Latest run · per-question scores
          </div>
          <table className="w-full text-sm" data-testid="per-row-table">
            <thead>
              <tr className="border-b border-white/10 text-left">
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6">
                  Question
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6 text-right">
                  Faithfulness
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6 text-right">
                  Answer Rel.
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 text-right">
                  Ctx. Precision
                </th>
              </tr>
            </thead>
            <tbody>
              {latest.per_row.map((r, i) => (
                <tr key={i} className="border-b border-white/5 hover:bg-white/[0.02]">
                  <td className="py-3 pr-6 text-white">{r.query}</td>
                  <td
                    className={`py-3 pr-6 font-mono tabular-nums text-right ${scoreColor(
                      r.faithfulness
                    )}`}
                  >
                    {r.faithfulness ?? "—"}
                  </td>
                  <td
                    className={`py-3 pr-6 font-mono tabular-nums text-right ${scoreColor(
                      r.answer_relevancy
                    )}`}
                  >
                    {r.answer_relevancy ?? "—"}
                  </td>
                  <td
                    className={`py-3 font-mono tabular-nums text-right ${scoreColor(
                      r.context_precision
                    )}`}
                  >
                    {r.context_precision ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Historical runs */}
      <div className="p-8">
        <div className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 mb-4">
          Historical eval runs
        </div>
        {runs.data?.runs?.length ? (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 text-left">
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6">
                  When
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6">
                  Scope
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6 text-right">
                  N
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6 text-right">
                  F
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6 text-right">
                  AR
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6 text-right">
                  CP
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 text-right">
                  Duration
                </th>
              </tr>
            </thead>
            <tbody>
              {runs.data.runs.map((r) => (
                <tr key={r.id} className="border-b border-white/5">
                  <td className="py-2.5 pr-6 font-mono text-xs text-neutral-400">
                    {r.created_at?.slice(0, 19).replace("T", " ")}
                  </td>
                  <td className="py-2.5 pr-6 font-mono text-xs text-neutral-300">
                    {r.scope}
                  </td>
                  <td className="py-2.5 pr-6 font-mono tabular-nums text-right text-white">
                    {r.n_samples}
                  </td>
                  <td className={`py-2.5 pr-6 font-mono tabular-nums text-right ${scoreColor(r.faithfulness)}`}>
                    {r.faithfulness ?? "—"}
                  </td>
                  <td className={`py-2.5 pr-6 font-mono tabular-nums text-right ${scoreColor(r.answer_relevancy)}`}>
                    {r.answer_relevancy ?? "—"}
                  </td>
                  <td className={`py-2.5 pr-6 font-mono tabular-nums text-right ${scoreColor(r.context_precision)}`}>
                    {r.context_precision ?? "—"}
                  </td>
                  <td className="py-2.5 font-mono text-xs text-neutral-500 tabular-nums text-right">
                    {r.duration_s}s
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="font-mono text-xs text-neutral-600 uppercase tracking-widest">
            no runs yet.
          </div>
        )}
      </div>
    </div>
  );
}

function MetricCard({ label, value, hint, color, testId, bordered }) {
  const display = value == null ? "—" : value.toFixed(2);
  return (
    <div
      data-testid={testId}
      className={`p-6 flex flex-col gap-2 ${bordered ? "border-l border-r border-white/10" : ""}`}
    >
      <div className="flex items-center gap-2">
        <div className="w-2 h-2" style={{ background: color }} />
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500">
          {label}
        </div>
      </div>
      <div
        className="font-mono text-5xl text-white tabular-nums leading-none mt-1"
        data-testid={`${testId}-value`}
      >
        {display}
      </div>
      <div className="text-[11px] text-neutral-500 leading-relaxed">{hint}</div>
    </div>
  );
}
