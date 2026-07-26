"use client";

import { AlertTriangle, Check, Download, FolderOpen, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { isDesktop, revealFile, saveApiFile, type SaveOutcome } from "@/lib/download";
import type { ExportFormat } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ExportMenu({
  presentationId,
  title,
}: {
  presentationId: string;
  title: string;
}) {
  const [open, setOpen] = useState(false);
  const [formats, setFormats] = useState<ExportFormat[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<SaveOutcome | null>(null);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open && formats.length === 0) void api.listFormats().then(setFormats);
  }, [open, formats.length]);

  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  // Clear a success message on its own; errors stay until dismissed.
  useEffect(() => {
    if (outcome?.status !== "saved" && outcome?.status !== "downloaded") return;
    const timer = setTimeout(() => setOutcome(null), 8000);
    return () => clearTimeout(timer);
  }, [outcome]);

  const run = async (format: ExportFormat) => {
    setBusy(format.name);
    setOutcome(null);
    const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    const result = await saveApiFile(
      `/api/v1/presentations/${presentationId}/download?format=${format.name}`,
      `${slug || "presentation"}.${format.extension}`,
    );
    setBusy(null);
    setOutcome(result);
    if (result.status !== "error") setOpen(false);
  };

  return (
    <div ref={container} className="relative">
      <button
        className={cn("btn btn-primary h-8 gap-1.5 px-2.5", open && "brightness-110")}
        onClick={() => setOpen((v) => !v)}
        disabled={busy !== null}
      >
        {busy ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
        <span className="hidden text-xs sm:inline">{busy ? "Exporting…" : "Export"}</span>
      </button>

      {open && (
        <div className="absolute right-0 top-9 z-30 w-64 overflow-hidden rounded-xl border border-line bg-surface p-1 shadow-xl">
          {formats.map((format) => (
            <button
              key={format.name}
              onClick={() => void run(format)}
              disabled={busy !== null}
              className="block w-full rounded-lg px-3 py-2 text-left hover:bg-raised disabled:opacity-50"
            >
              <span className="flex items-center justify-between text-sm font-medium">
                {format.label}
                {busy === format.name ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <span className="chip">.{format.extension}</span>
                )}
              </span>
              <span className="mt-0.5 block text-[11px] leading-snug text-muted">
                {format.description}
              </span>
            </button>
          ))}
          {formats.length === 0 && (
            <p className="px-3 py-4 text-center text-xs text-muted">Loading formats…</p>
          )}
          {outcome?.status === "error" && (
            <p className="m-1 rounded-lg bg-red-500/10 p-2 text-[11px] text-red-500">
              {outcome.message}
            </p>
          )}
        </div>
      )}

      {!open && outcome && outcome.status !== "cancelled" && (
        <ExportResult outcome={outcome} onDismiss={() => setOutcome(null)} />
      )}
    </div>
  );
}

function ExportResult({
  outcome,
  onDismiss,
}: {
  outcome: SaveOutcome;
  onDismiss: () => void;
}) {
  if (outcome.status === "error") {
    return (
      <div className="absolute right-0 top-9 z-30 flex w-72 items-start gap-2 rounded-xl border border-red-500/40 bg-surface p-3 shadow-xl">
        <AlertTriangle size={15} className="mt-0.5 shrink-0 text-red-500" />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-red-500">Export failed</p>
          <p className="mt-0.5 text-[11px] text-muted">{outcome.message}</p>
        </div>
        <button className="btn btn-ghost h-6 px-1.5 text-[11px]" onClick={onDismiss}>
          Close
        </button>
      </div>
    );
  }

  return (
    <div className="absolute right-0 top-9 z-30 flex w-72 items-start gap-2 rounded-xl border border-line bg-surface p-3 shadow-xl">
      <Check size={15} className="mt-0.5 shrink-0 text-green-500" />
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium">Saved</p>
        <p className="mt-0.5 truncate text-[11px] text-muted" title={outcome.path ?? outcome.name}>
          {outcome.path ?? outcome.name}
        </p>
        {isDesktop() && outcome.path && (
          <button
            className="btn mt-2 h-7 w-full text-[11px]"
            onClick={() => void revealFile(outcome.path!)}
          >
            <FolderOpen size={12} /> Show in folder
          </button>
        )}
      </div>
    </div>
  );
}
