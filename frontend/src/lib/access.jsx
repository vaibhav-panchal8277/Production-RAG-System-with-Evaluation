import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api, HAS_API_KEY } from "@/lib/api";

// What this browser may do, from /health. On a public deployment the backend
// sets RAG_API_KEY and the bundle ships without it, so visitors get a
// read-only UI: they can ask questions (if PUBLIC_QUERY is on) and browse
// documents and past eval runs, but not change the corpus, start evals or read
// other people's history. The server enforces all of this; the UI just avoids
// offering buttons that would only return 401.
export function useAccess() {
  const { data: h } = useQuery({ queryKey: ["health"], queryFn: api.health });
  const authRequired = Boolean(h?.auth_required);
  const isAdmin = !authRequired || HAS_API_KEY;
  return {
    loaded: Boolean(h),
    isAdmin,
    canQuery: isAdmin || Boolean(h?.public_query),
    rateLimit: h?.query_rate_per_min ?? null,
  };
}

export function AdminOnlyNote({ children }) {
  return (
    <div
      data-testid="admin-only-note"
      className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 border border-white/10 bg-white/[0.02] px-4 py-3"
    >
      {children}
    </div>
  );
}
