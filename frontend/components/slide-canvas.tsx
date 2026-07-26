"use client";

import { memo } from "react";

import { cn } from "@/lib/utils";

/**
 * Injects the deck's theme stylesheet once.
 *
 * The backend renders slides to HTML and hands over the matching CSS, so the
 * preview is byte-for-byte what the exporters produce. Every selector in that
 * sheet is namespaced `df-`, which keeps it from touching the app's own chrome.
 */
export function DeckStyles({ css }: { css: string }) {
  return <style data-deckforge-theme dangerouslySetInnerHTML={{ __html: css }} />;
}

interface SlideCanvasProps {
  html: string;
  className?: string;
  /** Blocks pointer events — used for thumbnails. */
  inert?: boolean;
}

/**
 * Renders one pre-rendered slide.
 *
 * Slide geometry is expressed in container-query units, so the same markup is a
 * 180px thumbnail or a full-width canvas with no extra work: the parent's width
 * is the only input.
 */
export const SlideCanvas = memo(function SlideCanvas({
  html,
  className,
  inert = false,
}: SlideCanvasProps) {
  return (
    <div
      className={cn("deck-scope w-full", inert && "pointer-events-none select-none", className)}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
});
