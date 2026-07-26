"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  AlignLeft,
  ArrowUp,
  Check,
  Download,
  FileText,
  Loader2,
  Paperclip,
  Settings2,
  Sparkles,
  Square,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { saveApiFile } from "@/lib/download";
import { useWorkspace } from "@/lib/store";
import type { Artifact, ContentDensity, Message } from "@/lib/types";
import { cn, formatBytes } from "@/lib/utils";

const STARTERS = [
  "Create a 12-slide presentation about reinforcement learning for engineers",
  "Turn my uploaded notes into an investor pitch",
  "Build a 5-minute lightning talk on prompt injection",
  "Draft a Q3 business review for the leadership team",
];

export function ChatPanel() {
  const messages = useWorkspace((s) => s.messages);
  const run = useWorkspace((s) => s.run);
  const send = useWorkspace((s) => s.send);
  const cancel = useWorkspace((s) => s.cancel);
  const upload = useWorkspace((s) => s.upload);
  const artifacts = useWorkspace((s) => s.artifacts);
  const loading = useWorkspace((s) => s.loading);
  const connections = useWorkspace((s) => s.connections);
  const connectionsLoaded = useWorkspace((s) => s.connectionsLoaded);
  const setSettingsOpen = useWorkspace((s) => s.setSettingsOpen);
  const density = useWorkspace((s) => s.density);
  const setDensity = useWorkspace((s) => s.setDensity);

  const needsSetup = connectionsLoaded && connections.length === 0;

  const [draft, setDraft] = useState("");
  const [uploads, setUploads] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages, run.reply, run.status]);

  useEffect(() => {
    const element = textarea.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`;
  }, [draft]);

  const submit = async () => {
    const content = draft.trim();
    if (!content || run.active) return;
    setDraft("");
    await send(content);
  };

  const handleFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    const list = Array.from(files);
    await upload(list);
    setUploads((current) => [...current, ...list.map((f) => f.name)]);
  };

  const empty = messages.length === 0 && !run.active;

  return (
    <section
      className="flex h-full min-w-0 flex-col bg-canvas"
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        void handleFiles(event.dataTransfer.files);
      }}
    >
      <div ref={scroller} className="relative min-h-0 flex-1 overflow-y-auto">
        {dragging && (
          <div className="pointer-events-none absolute inset-3 z-10 grid place-items-center rounded-xl border-2 border-dashed border-brand bg-brand/5 text-sm font-medium text-brand">
            Drop documents to give the agent source material
          </div>
        )}

        <div className="mx-auto w-full max-w-3xl px-5 py-6">
          {loading && messages.length === 0 && (
            <div className="space-y-3">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-16 animate-pulse rounded-xl bg-raised" />
              ))}
            </div>
          )}

          {needsSetup && <SetupBanner onOpen={() => setSettingsOpen(true)} />}

          {empty && !loading && <EmptyState onPick={(text) => setDraft(text)} />}

          <div className="space-y-6">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}

            {run.active && <LiveTurn status={run.status} progress={run.progress} reply={run.reply} />}

            {run.error && (
              <div className="flex items-start gap-2 rounded-xl border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-500">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                <div>
                  <p className="font-medium">That didn&apos;t work</p>
                  <p className="text-red-500/80">{run.error}</p>
                </div>
              </div>
            )}

            {artifacts.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {artifacts.map((artifact) => (
                  <ArtifactButton key={artifact.id} artifact={artifact} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="border-t border-line bg-surface/80 px-5 py-3 backdrop-blur">
        <div className="mx-auto w-full max-w-3xl">
          {uploads.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {uploads.map((name) => (
                <span key={name} className="chip">
                  <FileText size={11} />
                  {name}
                </span>
              ))}
            </div>
          )}

          <div className="flex items-end gap-2 rounded-xl border border-line bg-surface p-2 focus-within:border-brand">
            <button
              className="btn btn-ghost h-9 w-9 shrink-0 p-0"
              onClick={() => fileInput.current?.click()}
              title="Attach documents"
              aria-label="Attach documents"
            >
              <Paperclip size={16} />
            </button>
            <input
              ref={fileInput}
              type="file"
              multiple
              className="hidden"
              accept=".pdf,.docx,.pptx,.md,.txt,.csv,.xlsx,.png,.jpg,.jpeg"
              onChange={(event) => void handleFiles(event.target.files)}
            />
            <textarea
              ref={textarea}
              rows={1}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void submit();
                }
              }}
              placeholder="Describe the presentation, or ask for a change…"
              className="max-h-48 min-h-[36px] flex-1 resize-none bg-transparent px-1 py-2 text-[15px] outline-none placeholder:text-muted"
            />
            {run.active ? (
              <button className="btn h-9 w-9 shrink-0 p-0" onClick={cancel} title="Stop">
                <Square size={14} />
              </button>
            ) : (
              <button
                className="btn btn-primary h-9 w-9 shrink-0 p-0"
                onClick={() => void submit()}
                disabled={!draft.trim()}
                title="Send"
                aria-label="Send message"
              >
                <ArrowUp size={16} />
              </button>
            )}
          </div>
          <div className="mt-1.5 flex items-center justify-between gap-3">
            <DensityPicker value={density} onChange={(next) => void setDensity(next)} />
            <p className="text-[11px] text-muted">
              Enter to send · Shift+Enter for a new line · ⌘Z to undo a deck change
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

const DENSITIES: { value: ContentDensity; label: string; hint: string }[] = [
  { value: "concise", label: "Concise", hint: "Short cues for a presenter to talk around" },
  { value: "balanced", label: "Balanced", hint: "A lead sentence and full-clause bullets" },
  { value: "rich", label: "Rich", hint: "Explanatory paragraphs — reads without a presenter" },
];

/** How much prose the writer puts on each slide. */
function DensityPicker({
  value,
  onChange,
}: {
  value: ContentDensity;
  onChange: (density: ContentDensity) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <AlignLeft size={12} className="shrink-0 text-muted" aria-hidden />
      <div className="flex rounded-lg border border-line p-0.5" role="group" aria-label="Detail">
        {DENSITIES.map((option) => (
          <button
            key={option.value}
            onClick={() => onChange(option.value)}
            title={option.hint}
            aria-pressed={value === option.value}
            className={cn(
              "rounded-md px-2 py-0.5 text-[11px] transition",
              value === option.value
                ? "bg-raised font-medium text-ink"
                : "text-muted hover:text-ink",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function SetupBanner({ onOpen }: { onOpen: () => void }) {
  return (
    <div className="mb-6 flex items-start gap-3 rounded-xl border border-brand/40 bg-brand/5 p-4">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand/15 text-brand">
        <Settings2 size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">Connect a model to get started</p>
        <p className="mt-0.5 text-sm text-muted">
          Point DeckForge at a local model or a cloud provider. You can save several and switch
          between them at any time.
        </p>
      </div>
      <button className="btn btn-primary shrink-0" onClick={onOpen}>
        Set up
      </button>
    </div>
  );
}

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="py-10">
      <div className="mb-6 flex items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-xl bg-brand/10 text-brand">
          <Sparkles size={20} />
        </div>
        <div>
          <h1 className="text-lg font-semibold">What are we presenting?</h1>
          <p className="text-sm text-muted">
            Describe it once, then keep refining — the conversation never loses context.
          </p>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {STARTERS.map((starter) => (
          <button
            key={starter}
            onClick={() => onPick(starter)}
            className="panel p-3 text-left text-sm text-muted transition hover:border-brand/50 hover:text-ink"
          >
            {starter}
          </button>
        ))}
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] animate-fade-up rounded-2xl rounded-br-sm bg-brand px-4 py-2.5 text-[15px] text-brand-ink">
          {message.content}
        </div>
      </div>
    );
  }

  const { changelog, artifacts, review, questions } = message.metadata ?? {};
  return (
    <div className="animate-fade-up">
      <div className="prose-chat max-w-none">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
      </div>

      {questions && questions.length > 0 && (
        <ul className="mt-2 space-y-1 text-sm text-muted">
          {questions.map((question) => (
            <li key={question}>• {question}</li>
          ))}
        </ul>
      )}

      {changelog && changelog.length > 0 && (
        <details className="mt-2 text-xs text-muted">
          <summary className="cursor-pointer select-none hover:text-ink">
            {changelog.length} change{changelog.length > 1 ? "s" : ""} applied
          </summary>
          <ul className="mt-1 space-y-0.5 pl-4">
            {changelog.map((entry, index) => (
              <li key={`${entry}-${index}`} className="list-disc">
                {entry}
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {review && (
          <span className="chip" title={`${review.issues} issues found by the reviewer`}>
            review {review.score.toFixed(1)}/10
          </span>
        )}
        {artifacts?.map((artifact) => (
          <ArtifactButton key={artifact.id} artifact={artifact} compact />
        ))}
      </div>
    </div>
  );
}

/**
 * Downloads an export.
 *
 * A plain `<a download>` silently does nothing inside the desktop webview, so
 * this goes through the shared save helper and reports what happened.
 */
function ArtifactButton({ artifact, compact = false }: { artifact: Artifact; compact?: boolean }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  const save = async () => {
    setState("busy");
    const result = await saveApiFile(artifact.download_url, artifact.filename);
    if (result.status === "error") {
      setState("error");
      setMessage(result.message ?? "Could not save the file.");
    } else if (result.status === "cancelled") {
      setState("idle");
    } else {
      setState("done");
      setMessage(result.path ?? null);
    }
  };

  return (
    <span className="inline-flex flex-col">
      <button className="btn" onClick={() => void save()} disabled={state === "busy"}>
        {state === "busy" ? (
          <Loader2 size={13} className="animate-spin" />
        ) : state === "done" ? (
          <Check size={13} className="text-green-500" />
        ) : (
          <Download size={13} />
        )}
        {artifact.filename}
        {!compact && <span className="text-muted">{formatBytes(artifact.size_bytes)}</span>}
      </button>
      {state === "error" && <span className="mt-1 text-[11px] text-red-500">{message}</span>}
      {state === "done" && message && (
        <span className="mt-1 truncate text-[11px] text-muted" title={message}>
          Saved to {message}
        </span>
      )}
    </span>
  );
}

function LiveTurn({
  status,
  progress,
  reply,
}: {
  status: string;
  progress: number;
  reply: string;
}) {
  return (
    <div className="animate-fade-up">
      <AnimatePresence mode="wait">
        {!reply && (
          <motion.div
            key={status}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="flex items-center gap-2 text-sm text-muted"
          >
            <Loader2 size={14} className="animate-spin" />
            <span>{status || "Working"}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {!reply && (
        <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-raised">
          <motion.div
            className="h-full rounded-full bg-brand"
            animate={{ width: `${Math.max(4, Math.round(progress * 100))}%` }}
            transition={{ ease: "easeOut", duration: 0.4 }}
          />
        </div>
      )}

      {reply && (
        <div className="prose-chat max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{reply}</ReactMarkdown>
          <span className={cn("ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-brand align-middle")} />
        </div>
      )}
    </div>
  );
}
