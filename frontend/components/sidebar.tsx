"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  Layers,
  MessageSquarePlus,
  MoreHorizontal,
  Search,
  Settings2,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";

import { AppearanceToggle } from "@/components/appearance-toggle";
import { SettingsDialog } from "@/components/settings-dialog";
import { useWorkspace } from "@/lib/store";
import { bucketByAge, cn, relativeTime } from "@/lib/utils";

export function Sidebar() {
  const conversations = useWorkspace((s) => s.conversations);
  const conversationId = useWorkspace((s) => s.conversationId);
  const openConversation = useWorkspace((s) => s.openConversation);
  const newConversation = useWorkspace((s) => s.newConversation);
  const removeConversation = useWorkspace((s) => s.removeConversation);

  const connections = useWorkspace((s) => s.connections);
  const settingsOpen = useWorkspace((s) => s.settingsOpen);
  const setSettingsOpen = useWorkspace((s) => s.setSettingsOpen);
  const activeConnection = connections.find((c) => c.is_active);

  const [query, setQuery] = useState("");
  const [menuFor, setMenuFor] = useState<string | null>(null);

  const groups = useMemo(() => {
    const term = query.trim().toLowerCase();
    const filtered = term
      ? conversations.filter((c) => c.title.toLowerCase().includes(term))
      : conversations;
    return bucketByAge(filtered);
  }, [conversations, query]);

  return (
    <aside className="flex h-full w-[270px] shrink-0 flex-col border-r border-line bg-surface">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="grid h-8 w-8 place-items-center rounded-lg bg-brand text-brand-ink">
          <Layers size={17} />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold leading-tight">DeckForge</p>
          <p className="truncate text-[11px] text-muted">local · agentic · yours</p>
        </div>
        <div className="ml-auto">
          <AppearanceToggle />
        </div>
      </div>

      <div className="px-3">
        <button
          className="btn btn-primary w-full"
          onClick={() => void newConversation()}
          aria-label="Start a new conversation"
        >
          <MessageSquarePlus size={15} />
          New presentation
        </button>
      </div>

      <div className="relative px-3 py-3">
        <Search size={14} className="pointer-events-none absolute left-6 top-1/2 -translate-y-1/2 text-muted" />
        <input
          className="field pl-8"
          placeholder="Search conversations"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {groups.length === 0 && (
          <p className="px-3 py-8 text-center text-xs text-muted">
            {conversations.length === 0
              ? "No conversations yet. Start one above."
              : "Nothing matches that search."}
          </p>
        )}
        {groups.map((group) => (
          <div key={group.label} className="mb-3">
            <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
              {group.label}
            </p>
            <ul className="space-y-0.5">
              {group.items.map((conversation) => {
                const active = conversation.id === conversationId;
                return (
                  <li key={conversation.id} className="group relative">
                    <button
                      onClick={() => void openConversation(conversation.id)}
                      className={cn(
                        "w-full rounded-lg px-3 py-2 text-left transition",
                        active ? "bg-raised" : "hover:bg-raised/70",
                      )}
                    >
                      <span className="block truncate text-sm font-medium">
                        {conversation.title}
                      </span>
                      <span className="mt-0.5 flex items-center gap-2 text-[11px] text-muted">
                        <span>{relativeTime(conversation.updated_at)}</span>
                        {conversation.presentation_count > 0 && (
                          <span className="chip">
                            {conversation.presentation_count} deck
                            {conversation.presentation_count > 1 ? "s" : ""}
                          </span>
                        )}
                      </span>
                    </button>
                    <button
                      className="absolute right-1.5 top-1.5 hidden rounded p-1 text-muted hover:bg-line hover:text-ink group-hover:block"
                      onClick={() =>
                        setMenuFor(menuFor === conversation.id ? null : conversation.id)
                      }
                      aria-label="Conversation actions"
                    >
                      <MoreHorizontal size={14} />
                    </button>
                    <AnimatePresence>
                      {menuFor === conversation.id && (
                        <motion.div
                          initial={{ opacity: 0, y: -4 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -4 }}
                          className="absolute right-2 top-8 z-20 w-40 overflow-hidden rounded-lg border border-line bg-surface shadow-lg"
                        >
                          <button
                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-red-500 hover:bg-raised"
                            onClick={() => {
                              setMenuFor(null);
                              void removeConversation(conversation.id);
                            }}
                          >
                            <Trash2 size={14} /> Delete
                          </button>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-line p-2">
        <button
          className="btn btn-ghost w-full justify-start text-left"
          onClick={() => setSettingsOpen(true)}
          title="Manage model connections"
        >
          <Settings2 size={15} className="shrink-0" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm">
              {activeConnection?.name ?? "Set up a model"}
            </span>
            <span className="block truncate text-[11px] font-normal text-muted">
              {activeConnection
                ? activeConnection.model || activeConnection.provider_label
                : "No connection yet"}
            </span>
          </span>
          {activeConnection?.last_error && (
            <span
              className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500"
              title={activeConnection.last_error}
            />
          )}
        </button>
      </div>

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </aside>
  );
}
