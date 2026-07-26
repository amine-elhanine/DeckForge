"use client";

import { Check, Palette } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/store";
import type { ThemeInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ThemePicker({ current }: { current: string }) {
  const setTheme = useWorkspace((s) => s.setTheme);
  const [open, setOpen] = useState(false);
  const [themes, setThemes] = useState<ThemeInfo[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open && themes.length === 0) void api.listThemes().then(setThemes);
  }, [open, themes.length]);

  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const choose = async (name: string) => {
    setBusy(name);
    try {
      await setTheme(name);
      setOpen(false);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div ref={container} className="relative">
      <button
        className={cn("btn btn-ghost h-8 gap-1.5 px-2", open && "bg-raised")}
        onClick={() => setOpen((v) => !v)}
        title="Change theme"
      >
        <Palette size={15} />
        <span className="hidden text-xs sm:inline">{current}</span>
      </button>

      {open && (
        <div className="absolute right-0 top-9 z-30 max-h-[420px] w-[320px] overflow-y-auto rounded-xl border border-line bg-surface p-2 shadow-xl">
          <p className="px-2 pb-2 pt-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
            Themes · {themes.length}
          </p>
          <div className="grid grid-cols-2 gap-1.5">
            {themes.map((theme) => (
              <button
                key={theme.name}
                onClick={() => void choose(theme.name)}
                disabled={busy !== null}
                className={cn(
                  "rounded-lg border p-2 text-left transition disabled:opacity-60",
                  theme.name === current
                    ? "border-brand bg-raised"
                    : "border-line hover:border-brand/50",
                )}
                title={theme.description}
              >
                <div
                  className="mb-1.5 flex h-9 items-end gap-1 rounded p-1.5"
                  style={{ background: theme.palette.background }}
                >
                  {["primary", "secondary", "accent"].map((token) => (
                    <span
                      key={token}
                      className="h-3 w-3 rounded-full"
                      style={{ background: theme.palette[token] }}
                    />
                  ))}
                  <span
                    className="ml-auto h-1.5 w-6 rounded"
                    style={{ background: theme.palette.text, opacity: 0.5 }}
                  />
                </div>
                <span className="flex items-center gap-1 text-xs font-medium">
                  {theme.label}
                  {theme.name === current && <Check size={12} className="text-brand" />}
                </span>
                <span className="block text-[10px] text-muted">
                  {theme.mode}
                  {theme.source !== "builtin" ? ` · ${theme.source}` : ""}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
