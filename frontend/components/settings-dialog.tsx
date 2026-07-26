"use client";

import {
  AlertTriangle,
  Check,
  CircleCheck,
  Cloud,
  HardDrive,
  Loader2,
  Plus,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useWorkspace } from "@/lib/store";
import type { LlmConnection, LlmProbeResult, ProviderTemplate } from "@/lib/types";
import { cn, relativeTime } from "@/lib/utils";

/** The edit form's shape. `apiKey === null` means "leave the stored key alone". */
interface Draft {
  id: string | null;
  name: string;
  provider: string;
  base_url: string;
  model: string;
  apiKey: string | null;
  temperature: string;
}

const NEW_DRAFT: Draft = {
  id: null,
  name: "",
  provider: "",
  base_url: "",
  model: "",
  apiKey: "",
  temperature: "",
};

/**
 * Manage the LLM connections DeckForge can use.
 *
 * Several may be saved — a local model, a work endpoint, a personal key — and
 * one is active at a time. Switching is a single click.
 */
export function SettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const connections = useWorkspace((s) => s.connections);
  const loadConnections = useWorkspace((s) => s.loadConnections);

  const [templates, setTemplates] = useState<ProviderTemplate[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [probe, setProbe] = useState<LlmProbeResult | null>(null);
  const [busy, setBusy] = useState<"save" | "test" | "delete" | "activate" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const template = templates.find((t) => t.name === draft?.provider);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setProbe(null);
    void api.providerTemplates().then(setTemplates);
    void loadConnections();
  }, [open, loadConnections]);

  // Open straight into the form when there is nothing saved yet.
  useEffect(() => {
    if (open && connections.length === 0 && draft === null && templates.length > 0) {
      setDraft({ ...NEW_DRAFT });
    }
  }, [open, connections.length, draft, templates.length]);

  const edit = useCallback((connection: LlmConnection) => {
    setProbe(null);
    setError(null);
    setDraft({
      id: connection.id,
      name: connection.name,
      provider: connection.provider,
      base_url: connection.base_url ?? "",
      model: connection.model,
      apiKey: null, // keep the stored key unless the user types a new one
      temperature: connection.temperature?.toString() ?? "",
    });
  }, []);

  const pickProvider = (name: string) => {
    const chosen = templates.find((t) => t.name === name);
    setProbe(null);
    setDraft((current) => ({
      ...(current ?? NEW_DRAFT),
      provider: name,
      // Prefill from the adapter, but never clobber what the user typed.
      name: current?.name || (chosen?.label ?? name),
      base_url: current?.base_url || (chosen?.default_base_url ?? ""),
      model: current?.model || (chosen?.default_model ?? ""),
    }));
  };

  const runTest = async () => {
    if (!draft?.provider) return;
    setBusy("test");
    setError(null);
    try {
      setProbe(
        await api.testConnection({
          provider: draft.provider,
          base_url: draft.base_url || null,
          api_key: draft.apiKey,
          model: draft.model || undefined,
          profile_id: draft.id ?? undefined,
        }),
      );
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    if (!draft) return;
    setBusy("save");
    setError(null);
    try {
      const temperature = draft.temperature.trim() ? Number(draft.temperature) : null;
      if (draft.id) {
        const patch: Record<string, unknown> = {
          name: draft.name,
          provider: draft.provider,
          base_url: draft.base_url || null,
          model: draft.model,
          temperature,
        };
        // Only send the key when the user actually typed one.
        if (draft.apiKey !== null) patch.api_key = draft.apiKey;
        await api.updateConnection(draft.id, patch);
      } else {
        await api.createConnection({
          name: draft.name,
          provider: draft.provider,
          base_url: draft.base_url || null,
          api_key: draft.apiKey || null,
          model: draft.model,
          temperature,
        } as never);
      }
      await loadConnections();
      setDraft(null);
      setProbe(null);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const activate = async (id: string) => {
    setBusy("activate");
    try {
      await api.activateConnection(id);
      await loadConnections();
    } finally {
      setBusy(null);
    }
  };

  const remove = async (id: string) => {
    setBusy("delete");
    try {
      await api.deleteConnection(id);
      await loadConnections();
      if (draft?.id === id) setDraft(null);
    } finally {
      setBusy(null);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Model connections"
    >
      <div
        className="flex h-[560px] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold">Model connections</h2>
            <p className="text-[11px] text-muted">
              Save as many as you like and switch whenever you want.
            </p>
          </div>
          <button className="btn btn-ghost h-7 w-7 p-0" onClick={onClose} aria-label="Close">
            <X size={14} />
          </button>
        </header>

        <div className="flex min-h-0 flex-1">
          {/* Saved connections */}
          <div className="flex w-[240px] shrink-0 flex-col border-r border-line">
            <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
              {connections.length === 0 && (
                <p className="px-2 py-6 text-center text-xs text-muted">
                  No connections yet. Add one to start generating.
                </p>
              )}
              {connections.map((connection) => (
                <button
                  key={connection.id}
                  onClick={() => edit(connection)}
                  className={cn(
                    "w-full rounded-lg border px-2.5 py-2 text-left transition",
                    draft?.id === connection.id
                      ? "border-brand bg-raised"
                      : "border-transparent hover:bg-raised",
                  )}
                >
                  <span className="flex items-center gap-1.5">
                    {connection.kind === "local" ? (
                      <HardDrive size={12} className="shrink-0 text-muted" />
                    ) : (
                      <Cloud size={12} className="shrink-0 text-muted" />
                    )}
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">
                      {connection.name}
                    </span>
                    {connection.is_active && (
                      <CircleCheck size={13} className="shrink-0 text-brand" />
                    )}
                    {connection.last_error && (
                      <AlertTriangle size={12} className="shrink-0 text-amber-500" />
                    )}
                  </span>
                  <span className="mt-0.5 block truncate text-[11px] text-muted">
                    {connection.model || connection.provider_label}
                  </span>
                </button>
              ))}
            </div>
            <div className="border-t border-line p-2">
              <button
                className="btn w-full"
                onClick={() => {
                  setProbe(null);
                  setError(null);
                  setDraft({ ...NEW_DRAFT });
                }}
              >
                <Plus size={14} /> Add connection
              </button>
            </div>
          </div>

          {/* Editor */}
          <div className="min-w-0 flex-1 overflow-y-auto p-4">
            {draft === null ? (
              <div className="grid h-full place-items-center text-center">
                <div>
                  <p className="text-sm font-medium">
                    {connections.find((c) => c.is_active)?.name ?? "Nothing selected"}
                  </p>
                  <p className="mt-1 text-xs text-muted">
                    Pick a connection to edit it, or add another.
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <Field label="Provider">
                  <select
                    className="field"
                    value={draft.provider}
                    onChange={(event) => pickProvider(event.target.value)}
                  >
                    <option value="">Choose a provider…</option>
                    <optgroup label="Runs on this machine">
                      {templates
                        .filter((t) => t.kind === "local")
                        .map((t) => (
                          <option key={t.name} value={t.name}>
                            {t.label}
                          </option>
                        ))}
                    </optgroup>
                    <optgroup label="Cloud">
                      {templates
                        .filter((t) => t.kind === "cloud")
                        .map((t) => (
                          <option key={t.name} value={t.name}>
                            {t.label}
                          </option>
                        ))}
                    </optgroup>
                  </select>
                  {template?.note && (
                    <p className="mt-1 text-[11px] text-muted">{template.note}</p>
                  )}
                </Field>

                <Field label="Name">
                  <input
                    className="field"
                    value={draft.name}
                    placeholder="e.g. Work DeepSeek"
                    onChange={(event) =>
                      setDraft({ ...draft, name: event.target.value })
                    }
                  />
                </Field>

                <Field label="Base URL" hint="Leave blank for the provider default.">
                  <input
                    className="field font-mono text-[13px]"
                    value={draft.base_url}
                    placeholder={template?.default_base_url ?? "https://api.example.com/v1"}
                    onChange={(event) => setDraft({ ...draft, base_url: event.target.value })}
                  />
                </Field>

                <Field
                  label="Model"
                  hint={
                    probe?.models.length
                      ? `${probe.models.length} models found — pick one below.`
                      : undefined
                  }
                >
                  <input
                    className="field font-mono text-[13px]"
                    list="deckforge-model-options"
                    value={draft.model}
                    placeholder={template?.default_model ?? "model name"}
                    onChange={(event) => setDraft({ ...draft, model: event.target.value })}
                  />
                  <datalist id="deckforge-model-options">
                    {(probe?.models.length
                      ? probe.models
                      : (template?.suggested_models ?? [])
                    ).map((name) => (
                      <option key={name} value={name} />
                    ))}
                  </datalist>
                </Field>

                {template?.requires_api_key !== false && (
                  <Field
                    label="API key"
                    hint={
                      draft.id && draft.apiKey === null
                        ? "A key is stored. Type to replace it."
                        : "Stored locally in your own data folder — not a secrets vault."
                    }
                  >
                    <input
                      className="field font-mono text-[13px]"
                      type="password"
                      autoComplete="off"
                      value={draft.apiKey ?? ""}
                      placeholder={
                        draft.id && draft.apiKey === null
                          ? connections.find((c) => c.id === draft.id)?.api_key_hint ?? "••••"
                          : "sk-…"
                      }
                      onChange={(event) => setDraft({ ...draft, apiKey: event.target.value })}
                    />
                  </Field>
                )}

                <Field label="Temperature" hint="Blank uses the application default.">
                  <input
                    className="field"
                    inputMode="decimal"
                    value={draft.temperature}
                    placeholder="0.7"
                    onChange={(event) => setDraft({ ...draft, temperature: event.target.value })}
                  />
                </Field>

                {probe && (
                  <div
                    className={cn(
                      "rounded-lg border p-2.5 text-xs",
                      probe.ok
                        ? "border-green-500/40 bg-green-500/5 text-green-600 dark:text-green-400"
                        : "border-amber-500/40 bg-amber-500/5 text-amber-600 dark:text-amber-400",
                    )}
                  >
                    <p className="font-medium">
                      {probe.ok
                        ? `Connected in ${probe.latency_ms} ms · ${probe.models.length} models`
                        : "Could not connect"}
                    </p>
                    {probe.error && <p className="mt-0.5 opacity-90">{probe.error}</p>}
                    {probe.hint && <p className="mt-0.5 opacity-80">{probe.hint}</p>}
                  </div>
                )}

                {error && (
                  <p className="rounded-lg border border-red-500/40 bg-red-500/5 p-2.5 text-xs text-red-500">
                    {error}
                  </p>
                )}

                {draft.id &&
                  connections.find((c) => c.id === draft.id)?.last_error &&
                  !probe && (
                    <p className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-2.5 text-xs text-amber-600 dark:text-amber-400">
                      Last run failed: {connections.find((c) => c.id === draft.id)?.last_error}
                    </p>
                  )}
              </div>
            )}
          </div>
        </div>

        <footer className="flex items-center gap-2 border-t border-line px-4 py-3">
          {draft?.id && (
            <>
              <button
                className="btn text-red-500"
                onClick={() => void remove(draft.id!)}
                disabled={busy !== null}
              >
                <Trash2 size={14} /> Delete
              </button>
              {!connections.find((c) => c.id === draft.id)?.is_active && (
                <button
                  className="btn"
                  onClick={() => void activate(draft.id!)}
                  disabled={busy !== null}
                >
                  <Check size={14} /> Use this one
                </button>
              )}
            </>
          )}
          <div className="ml-auto flex items-center gap-2">
            {draft && (
              <button
                className="btn"
                onClick={() => void runTest()}
                disabled={!draft.provider || busy !== null}
              >
                {busy === "test" ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Zap size={14} />
                )}
                Test
              </button>
            )}
            <button className="btn" onClick={onClose}>
              Close
            </button>
            {draft && (
              <button
                className="btn btn-primary"
                onClick={() => void save()}
                disabled={!draft.provider || !draft.name.trim() || busy !== null}
              >
                {busy === "save" && <Loader2 size={14} className="animate-spin" />}
                {draft.id ? "Save" : "Add connection"}
              </button>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-muted">{hint}</span>}
    </label>
  );
}
