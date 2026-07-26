"use client";

import { useEffect } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";

import { ChatPanel } from "@/components/chat-panel";
import { DeckPanel } from "@/components/deck-panel";
import { Sidebar } from "@/components/sidebar";
import { useWorkspace } from "@/lib/store";

/** The three-pane workspace: conversations, chat, deck. */
export function Workspace() {
  const loadConversations = useWorkspace((s) => s.loadConversations);
  const loadConnections = useWorkspace((s) => s.loadConnections);
  const conversationId = useWorkspace((s) => s.conversationId);
  const conversations = useWorkspace((s) => s.conversations);
  const openConversation = useWorkspace((s) => s.openConversation);
  const selectSlide = useWorkspace((s) => s.selectSlide);
  const slideIndex = useWorkspace((s) => s.slideIndex);
  const undo = useWorkspace((s) => s.undo);

  useEffect(() => {
    void loadConversations();
    void loadConnections();
  }, [loadConversations, loadConnections]);

  // Open the most recent conversation on first load.
  useEffect(() => {
    if (!conversationId && conversations.length > 0) {
      void openConversation(conversations[0].id);
    }
  }, [conversationId, conversations, openConversation]);

  // Global keyboard shortcuts.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z" && !event.shiftKey) {
        event.preventDefault();
        void undo();
        return;
      }
      if (typing) return;
      if (event.key === "ArrowDown" || event.key === "ArrowRight" || event.key === "j") {
        event.preventDefault();
        selectSlide(slideIndex + 1);
      } else if (event.key === "ArrowUp" || event.key === "ArrowLeft" || event.key === "k") {
        event.preventDefault();
        selectSlide(slideIndex - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectSlide, slideIndex, undo]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-canvas">
      <Sidebar />
      <PanelGroup direction="horizontal" className="flex-1" autoSaveId="deckforge-panels">
        <Panel defaultSize={42} minSize={26} className="min-w-0">
          <ChatPanel />
        </Panel>
        <PanelResizeHandle className="group relative w-px bg-line transition-colors hover:bg-brand/60">
          <div className="absolute inset-y-0 -left-1 -right-1" />
        </PanelResizeHandle>
        <Panel defaultSize={58} minSize={30} className="min-w-0">
          <DeckPanel />
        </Panel>
      </PanelGroup>
    </div>
  );
}
