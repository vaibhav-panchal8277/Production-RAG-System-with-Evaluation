/**
 * Parses inline citation markers like "[chunk 3]" or "[chunk 3, 5]"
 * and returns JSX with clickable spans linked to chunk highlight state.
 */
import React from "react";

const RE = /\[chunk\s+([\d,\s]+)\]/gi;

export default function CitedText({ text, activeChunk, setActiveChunk }) {
  if (!text) return null;

  const parts = [];
  let last = 0;
  let m;
  RE.lastIndex = 0;
  while ((m = RE.exec(text)) !== null) {
    if (m.index > last) parts.push({ kind: "text", value: text.slice(last, m.index) });
    const nums = m[1]
      .split(",")
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => !Number.isNaN(n));
    parts.push({ kind: "cite", nums });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", value: text.slice(last) });

  return (
    <span className="whitespace-pre-wrap">
      {parts.map((p, i) => {
        if (p.kind === "text") return <span key={i}>{p.value}</span>;
        return p.nums.map((n, j) => (
          <button
            key={`${i}-${j}`}
            data-testid={`citation-${n}`}
            className={`citation-marker ${activeChunk === n ? "active" : ""}`}
            onMouseEnter={() => setActiveChunk?.(n)}
            onMouseLeave={() => setActiveChunk?.(null)}
            onClick={() => setActiveChunk?.(n === activeChunk ? null : n)}
          >
            [{n}]
          </button>
        ));
      })}
    </span>
  );
}
