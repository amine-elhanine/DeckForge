"use client";

import {
  ChevronLeft,
  ChevronRight,
  Copy,
  GripVertical,
  History,
  Maximize2,
  NotebookPen,
  Presentation,
  Trash2,
  Undo2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ExportMenu } from "@/components/export-menu";
import { absoluteUrl } from "@/lib/api";
import { SlideCanvas, DeckStyles } from "@/components/slide-canvas";
import { ThemePicker } from "@/components/theme-picker";
import { VersionHistory } from "@/components/version-history";
import { useWorkspace } from "@/lib/store";
import { cn } from "@/lib/utils";

export function DeckPanel() {
  const presentation = useWorkspace((s) => s.presentation);
  const render = useWorkspace((s) => s.render);
  const slideIndex = useWorkspace((s) => s.slideIndex);
  const selectSlide = useWorkspace((s) => s.selectSlide);
  const applyOperations = useWorkspace((s) => s.applyOperations);
  const undo = useWorkspace((s) => s.undo);
  const run = useWorkspace((s) => s.run);

  const [showNotes, setShowNotes] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);
  const railRef = useRef<HTMLDivElement>(null);

  const slides = render?.slides ?? [];
  const current = slides[slideIndex];

  useEffect(() => {
    const active = railRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    active?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [slideIndex]);

  if (!presentation || !render) {
    return <EmptyDeck busy={run.active} status={run.status} />;
  }

  const reorder = async (from: number, to: number) => {
    if (from === to) return;
    const slideId = slides[from].id;
    await applyOperations(
      [{ op: "move_slide", slide_id: slideId, to_index: to }],
      `Moved slide ${from + 1} to position ${to + 1}`,
    );
    selectSlide(to);
  };

  return (
    <section className="flex h-full min-w-0 flex-col bg-canvas">
      <DeckStyles css={render.css} />

      <header className="flex items-center gap-2 border-b border-line bg-surface px-4 py-2.5">
        <Presentation size={16} className="shrink-0 text-muted" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold leading-tight">{presentation.title}</p>
          <p className="text-[11px] text-muted">
            {presentation.slide_count} slides · v{presentation.version} · {render.theme}
          </p>
        </div>

        <ThemePicker current={presentation.theme} />
        <button
          className="btn btn-ghost h-8 w-8 p-0"
          onClick={() => void undo()}
          title="Undo (⌘Z)"
          aria-label="Undo"
        >
          <Undo2 size={15} />
        </button>
        <button
          className={cn("btn btn-ghost h-8 w-8 p-0", showHistory && "bg-raised")}
          onClick={() => setShowHistory((v) => !v)}
          title="Version history"
          aria-label="Version history"
        >
          <History size={15} />
        </button>
        <button
          className={cn("btn btn-ghost h-8 w-8 p-0", showNotes && "bg-raised")}
          onClick={() => setShowNotes((v) => !v)}
          title="Speaker notes"
          aria-label="Speaker notes"
        >
          <NotebookPen size={15} />
        </button>
        <a
          className="btn btn-ghost h-8 w-8 p-0"
          href={absoluteUrl(`/api/v1/presentations/${presentation.id}/preview`)}
          target="_blank"
          rel="noreferrer"
          title="Open full preview"
        >
          <Maximize2 size={15} />
        </a>
        <ExportMenu presentationId={presentation.id} title={presentation.title} />
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Slide rail */}
        <div
          ref={railRef}
          className="w-[188px] shrink-0 space-y-2 overflow-y-auto border-r border-line bg-surface/60 p-2"
        >
          {slides.map((slide, index) => (
            <div
              key={slide.id}
              data-active={index === slideIndex}
              draggable
              onDragStart={() => setDragIndex(index)}
              onDragOver={(event) => {
                event.preventDefault();
                setOverIndex(index);
              }}
              onDragEnd={() => {
                setDragIndex(null);
                setOverIndex(null);
              }}
              onDrop={(event) => {
                event.preventDefault();
                if (dragIndex !== null) void reorder(dragIndex, index);
                setDragIndex(null);
                setOverIndex(null);
              }}
              className={cn(
                "group relative cursor-pointer rounded-lg border p-1 transition",
                index === slideIndex
                  ? "border-brand ring-2 ring-brand/30"
                  : "border-line hover:border-brand/40",
                overIndex === index && dragIndex !== null && "border-brand",
                dragIndex === index && "opacity-40",
              )}
              onClick={() => selectSlide(index)}
            >
              <SlideCanvas html={slide.html} inert />
              <div className="mt-1 flex items-center gap-1 px-0.5">
                <GripVertical size={11} className="shrink-0 text-muted opacity-0 group-hover:opacity-100" />
                <span className="text-[10px] tabular-nums text-muted">{index + 1}</span>
                <span className="truncate text-[10px] text-muted">{slide.title || slide.kind}</span>
              </div>
              <div className="absolute right-1 top-1 hidden gap-0.5 group-hover:flex">
                <button
                  className="rounded bg-surface/90 p-1 text-muted hover:text-ink"
                  title="Duplicate slide"
                  onClick={(event) => {
                    event.stopPropagation();
                    void applyOperations(
                      [{ op: "duplicate_slide", slide_id: slide.id }],
                      "Duplicated a slide",
                    );
                  }}
                >
                  <Copy size={11} />
                </button>
                <button
                  className="rounded bg-surface/90 p-1 text-muted hover:text-red-500"
                  title="Delete slide"
                  onClick={(event) => {
                    event.stopPropagation();
                    void applyOperations(
                      [{ op: "delete_slide", slide_id: slide.id }],
                      "Deleted a slide",
                    );
                  }}
                >
                  <Trash2 size={11} />
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* Stage */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-5">
            {current && (
              <div className="w-full max-w-[1100px] animate-fade-up">
                <SlideCanvas html={current.html} />
              </div>
            )}
          </div>

          <div className="flex items-center justify-center gap-3 border-t border-line bg-surface px-4 py-2">
            <button
              className="btn btn-ghost h-8 w-8 p-0"
              onClick={() => selectSlide(slideIndex - 1)}
              disabled={slideIndex === 0}
              aria-label="Previous slide"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="text-xs tabular-nums text-muted">
              {slideIndex + 1} / {slides.length}
            </span>
            <button
              className="btn btn-ghost h-8 w-8 p-0"
              onClick={() => selectSlide(slideIndex + 1)}
              disabled={slideIndex >= slides.length - 1}
              aria-label="Next slide"
            >
              <ChevronRight size={16} />
            </button>
            {current && (
              <span className="ml-2 chip">{current.layout}</span>
            )}
          </div>

          {showNotes && current && (
            <div className="max-h-44 overflow-y-auto border-t border-line bg-surface px-5 py-3">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
                Speaker notes
              </p>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">
                {current.notes || <span className="text-muted">No notes on this slide yet.</span>}
              </p>
            </div>
          )}
        </div>

        {showHistory && (
          <VersionHistory
            presentation={presentation}
            onClose={() => setShowHistory(false)}
          />
        )}
      </div>
    </section>
  );
}

function EmptyDeck({ busy, status }: { busy: boolean; status: string }) {
  return (
    <section className="grid h-full place-items-center bg-canvas p-8">
      <div className="max-w-sm text-center">
        <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-xl bg-raised text-muted">
          <Presentation size={22} />
        </div>
        <p className="text-sm font-medium">
          {busy ? status || "Building your deck…" : "No presentation yet"}
        </p>
        <p className="mt-1 text-sm text-muted">
          {busy
            ? "Slides will appear here as they are written."
            : "Ask for one in the chat and it will render here — then keep refining it."}
        </p>
        {busy && (
          <div className="mx-auto mt-4 h-1 w-40 overflow-hidden rounded-full bg-raised">
            <div className="h-full w-1/2 animate-shimmer rounded-full bg-gradient-to-r from-transparent via-brand to-transparent bg-[length:200%_100%]" />
          </div>
        )}
      </div>
    </section>
  );
}
