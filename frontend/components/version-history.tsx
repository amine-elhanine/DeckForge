"use client";

import { GitFork, RotateCcw, X } from "lucide-react";
import { useState } from "react";

import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/store";
import type { Presentation } from "@/lib/types";
import { cn, relativeTime } from "@/lib/utils";

export function VersionHistory({
  presentation,
  onClose,
}: {
  presentation: Presentation;
  onClose: () => void;
}) {
  const restore = useWorkspace((s) => s.restore);
  const loadConversations = useWorkspace((s) => s.loadConversations);
  const [busy, setBusy] = useState<number | null>(null);

  const versions = [...presentation.versions].reverse();

  return (
    <aside className="flex w-[280px] shrink-0 flex-col border-l border-line bg-surface">
      <header className="flex items-center justify-between border-b border-line px-3 py-2.5">
        <p className="text-sm font-semibold">History</p>
        <button className="btn btn-ghost h-7 w-7 p-0" onClick={onClose} aria-label="Close history">
          <X size={14} />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {versions.map((version) => {
          const current = version.version === presentation.version;
          return (
            <div
              key={version.id}
              className={cn(
                "mb-1.5 rounded-lg border p-2.5",
                current ? "border-brand bg-raised" : "border-line",
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold tabular-nums">v{version.version}</span>
                <span className="text-[10px] text-muted">{relativeTime(version.created_at)}</span>
              </div>
              <p className="mt-0.5 line-clamp-2 text-xs text-muted">
                {version.label || "No description"}
              </p>
              <p className="mt-1 text-[10px] text-muted">{version.slide_count} slides</p>
              {!current && (
                <button
                  className="btn mt-2 h-7 w-full text-xs"
                  disabled={busy !== null}
                  onClick={async () => {
                    setBusy(version.version);
                    try {
                      await restore(version.version);
                    } finally {
                      setBusy(null);
                    }
                  }}
                >
                  <RotateCcw size={12} />
                  {busy === version.version ? "Restoring…" : "Restore"}
                </button>
              )}
            </div>
          );
        })}
      </div>

      <div className="border-t border-line p-2">
        <button
          className="btn w-full"
          onClick={async () => {
            await api.fork(presentation.id);
            await loadConversations();
          }}
          title="Create an independent copy of this deck"
        >
          <GitFork size={14} />
          Fork this deck
        </button>
      </div>
    </aside>
  );
}
