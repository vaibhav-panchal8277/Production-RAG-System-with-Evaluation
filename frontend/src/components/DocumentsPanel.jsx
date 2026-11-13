import React, { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAccess, AdminOnlyNote } from "@/lib/access";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

export default function DocumentsPanel() {
  const qc = useQueryClient();
  const { isAdmin } = useAccess();
  const { data, isLoading } = useQuery({
    queryKey: ["documents"],
    queryFn: api.listDocs,
  });
  const fileRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  const seed = useMutation({
    mutationFn: api.seedDocs,
    onSuccess: (r) => {
      const ok = r.ingested.filter((x) => !x.error).length;
      toast.success(`Seeded ${ok} documents`);
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["health"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const del = useMutation({
    mutationFn: api.deleteDoc,
    onSuccess: () => {
      toast.success("Deleted");
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["health"] });
    },
    // 503 = vector store unreachable; nothing was deleted, safe to retry.
    onError: (e) => toast.error(e?.response?.data?.detail || e.message),
  });

  const handleUpload = async (file) => {
    if (!file) return;
    setUploading(true);
    try {
      const r = await api.uploadDoc(file);
      toast.success(`Ingested ${r.n_chunks} chunks from ${file.name}`);
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["health"] });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const docs = data?.documents || [];

  return (
    <div className="min-h-screen">
      <div className="px-8 pt-8 pb-6 border-b border-white/10">
        <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500">
          Corpus manager
        </div>
        <h1 className="font-heading text-4xl font-black leading-none mt-2 text-white">
          Documents.
        </h1>
        <div className="text-sm text-neutral-400 mt-3 max-w-2xl">
          Chunks are stored in MongoDB for BM25, embeddings live in Pinecone (dim 384,
          MiniLM), and every upload triggers a full BM25 rebuild.
        </div>
      </div>

      {/* Actions */}
      {!isAdmin ? (
        <div className="p-8 border-b border-white/10">
          <AdminOnlyNote>
            Read-only demo · uploading, seeding and deleting documents need the admin key
          </AdminOnlyNote>
        </div>
      ) : (
      <div className="grid grid-cols-2 border-b border-white/10">
        <div className="p-8 border-r border-white/10">
          <div className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 mb-3">
            Upload document
          </div>
          <input
            ref={fileRef}
            type="file"
            data-testid="file-input"
            accept=".pdf,.md,.txt"
            onChange={(e) => handleUpload(e.target.files?.[0])}
            className="text-sm text-neutral-300 file:font-mono file:text-xs file:uppercase file:tracking-widest file:bg-white file:text-black file:border-0 file:px-4 file:py-2 file:mr-4 hover:file:bg-neutral-200 file:cursor-pointer"
          />
          <div className="font-mono text-[10px] text-neutral-600 mt-3">
            {uploading ? "chunking · embedding · upserting…" : "PDF, Markdown, or plain text"}
          </div>
        </div>
        <div className="p-8">
          <div className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 mb-3">
            Sample corpus
          </div>
          <div className="text-sm text-neutral-400 mb-3">
            4 sample docs — HR policy, data retention, Widget-3000 manual, incident runbook.
          </div>
          <Button
            data-testid="seed-btn"
            onClick={() => seed.mutate()}
            disabled={seed.isPending}
            className="rounded-none bg-white text-black hover:bg-neutral-200 font-mono text-xs uppercase tracking-[0.18em] h-10 px-6"
          >
            {seed.isPending ? "Seeding…" : "Seed sample corpus"}
          </Button>
        </div>
      </div>
      )}

      {/* Table */}
      <div className="p-8">
        <div className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 mb-4">
          Indexed documents ({docs.length})
        </div>
        {isLoading ? (
          <div className="font-mono text-xs text-neutral-500">loading…</div>
        ) : docs.length === 0 ? (
          <div className="font-mono text-xs text-neutral-600 uppercase tracking-widest">
            no documents indexed. seed or upload above.
          </div>
        ) : (
          <table className="w-full text-sm" data-testid="documents-table">
            <thead>
              <tr className="border-b border-white/10 text-left">
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6">
                  Title
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6">
                  Source
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6">
                  Kind
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6 text-right">
                  Chunks
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 pr-6">
                  Updated
                </th>
                <th className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 pb-2 text-right">
                  Action
                </th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr
                  key={d.source}
                  data-testid={`doc-row-${d.source}`}
                  className="border-b border-white/5 hover:bg-white/[0.02] transition-colors"
                >
                  <td className="py-3 pr-6 text-white">{d.title}</td>
                  <td className="py-3 pr-6 font-mono text-xs text-neutral-400">
                    {d.source}
                  </td>
                  <td className="py-3 pr-6 font-mono text-xs text-neutral-400 uppercase">
                    {d.kind}
                  </td>
                  <td className="py-3 pr-6 font-mono text-white tabular-nums text-right">
                    {d.n_chunks}
                  </td>
                  <td className="py-3 pr-6 font-mono text-xs text-neutral-500">
                    {d.updated_at?.slice(0, 19).replace("T", " ")}
                  </td>
                  <td className="py-3 text-right">
                    {isAdmin && (
                    <button
                      data-testid={`delete-${d.source}`}
                      onClick={() => del.mutate(d.source)}
                      className="font-mono text-[10px] uppercase tracking-widest px-2 py-1 border border-white/10 text-neutral-400 hover:border-red-500 hover:text-red-400 transition-colors"
                    >
                      Delete
                    </button>
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
