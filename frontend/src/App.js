import React, { useState } from "react";
import "@/App.css";
import { Toaster } from "@/components/ui/sonner";
import Sidebar from "@/components/Sidebar";
import ChatPanel from "@/components/ChatPanel";
import DocumentsPanel from "@/components/DocumentsPanel";
import EvalDashboard from "@/components/EvalDashboard";
import HistoryPanel from "@/components/HistoryPanel";

export default function App() {
  const [active, setActive] = useState("chat");
  const [controls, setControls] = useState({ mode: "hybrid", topK: 5 });

  return (
    <div className="min-h-screen bg-[#0a0a0c] text-white noise-bg relative">
      <Sidebar
        active={active}
        setActive={setActive}
        controls={controls}
        setControls={setControls}
      />
      <main className="ml-[260px] relative z-[1]" data-testid="main-content">
        {active === "chat" && <ChatPanel controls={controls} />}
        {active === "docs" && <DocumentsPanel />}
        {active === "eval" && <EvalDashboard />}
        {active === "history" && <HistoryPanel />}
      </main>
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: "#111114",
            border: "1px solid rgba(255,255,255,0.15)",
            color: "#fff",
            borderRadius: 0,
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 12,
          },
        }}
      />
    </div>
  );
}
