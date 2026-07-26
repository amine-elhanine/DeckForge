"use client";

import { create } from "zustand";

import { api, streamMessage } from "./api";
import type {
  Artifact,
  ContentDensity,
  Conversation,
  DeckOperation,
  LlmConnection,
  Message,
  Presentation,
  RenderPayload,
} from "./types";

interface RunState {
  active: boolean;
  status: string;
  progress: number;
  reply: string;
  error: string | null;
}

const IDLE: RunState = { active: false, status: "", progress: 0, reply: "", error: null };

interface WorkspaceState {
  conversations: Conversation[];
  conversationId: string | null;
  messages: Message[];
  presentation: Presentation | null;
  render: RenderPayload | null;
  slideIndex: number;
  run: RunState;
  artifacts: Artifact[];
  loading: boolean;
  abort: AbortController | null;
  connections: LlmConnection[];
  connectionsLoaded: boolean;
  /** Settings live in the store so the chat's empty state can open them too. */
  settingsOpen: boolean;
  /** How much prose each slide should carry. Persisted on the conversation. */
  density: ContentDensity;

  setSettingsOpen: (open: boolean) => void;
  setDensity: (density: ContentDensity) => Promise<void>;
  loadConnections: () => Promise<void>;
  loadConversations: () => Promise<void>;
  openConversation: (id: string) => Promise<void>;
  newConversation: () => Promise<string>;
  removeConversation: (id: string) => Promise<void>;
  renameConversation: (id: string, title: string) => Promise<void>;

  send: (content: string) => Promise<void>;
  cancel: () => void;

  refreshDeck: (presentationId?: string) => Promise<void>;
  selectSlide: (index: number) => void;
  applyOperations: (operations: DeckOperation[], summary?: string) => Promise<void>;
  setTheme: (theme: string) => Promise<void>;
  undo: () => Promise<void>;
  restore: (version: number) => Promise<void>;
  upload: (files: File[]) => Promise<void>;
}

export const useWorkspace = create<WorkspaceState>((set, get) => ({
  conversations: [],
  conversationId: null,
  messages: [],
  presentation: null,
  render: null,
  slideIndex: 0,
  run: IDLE,
  artifacts: [],
  loading: false,
  abort: null,
  connections: [],
  connectionsLoaded: false,
  settingsOpen: false,
  density: "rich",

  setSettingsOpen(open) {
    set({ settingsOpen: open });
  },

  async setDensity(density) {
    set({ density });
    const id = get().conversationId;
    // Nothing to persist until a conversation exists; `newConversation` carries
    // whatever is selected when the first message is sent.
    if (id) await api.updateConversation(id, { settings: { density } });
  },

  async loadConnections() {
    try {
      set({ connections: await api.listConnections(), connectionsLoaded: true });
    } catch {
      // The backend may still be starting; the caller retries on next open.
      set({ connectionsLoaded: true });
    }
  },

  async loadConversations() {
    set({ conversations: await api.listConversations() });
  },

  async openConversation(id) {
    set({ loading: true, conversationId: id, artifacts: [], run: IDLE });
    try {
      const [messages, conversation] = await Promise.all([
        api.listMessages(id),
        api.getConversation(id),
      ]);
      set({ messages });
      const saved = conversation.settings?.density;
      if (saved === "concise" || saved === "balanced" || saved === "rich") set({ density: saved });
      if (conversation.latest_presentation_id) {
        await get().refreshDeck(conversation.latest_presentation_id);
      } else {
        set({ presentation: null, render: null, slideIndex: 0 });
      }
    } finally {
      set({ loading: false });
    }
  },

  async newConversation() {
    const conversation = await api.createConversation(undefined, { density: get().density });
    set((state) => ({
      conversations: [conversation, ...state.conversations],
      conversationId: conversation.id,
      messages: [],
      presentation: null,
      render: null,
      slideIndex: 0,
      artifacts: [],
      run: IDLE,
    }));
    return conversation.id;
  },

  async removeConversation(id) {
    await api.deleteConversation(id);
    const remaining = get().conversations.filter((c) => c.id !== id);
    set({ conversations: remaining });
    if (get().conversationId === id) {
      set({ conversationId: null, messages: [], presentation: null, render: null });
    }
  },

  async renameConversation(id, title) {
    const updated = await api.updateConversation(id, { title });
    set((state) => ({
      conversations: state.conversations.map((c) => (c.id === id ? updated : c)),
    }));
  },

  async send(content) {
    const conversationId = get().conversationId ?? (await get().newConversation());
    const optimistic: Message = {
      id: `tmp_${Date.now()}`,
      conversation_id: conversationId,
      role: "user",
      content,
      created_at: new Date().toISOString(),
      metadata: {},
      presentation_id: null,
      presentation_version: null,
    };
    const controller = new AbortController();
    set((state) => ({
      messages: [...state.messages, optimistic],
      run: { active: true, status: "Thinking", progress: 0.02, reply: "", error: null },
      artifacts: [],
      abort: controller,
    }));

    await streamMessage(
      conversationId,
      content,
      {
        status: (data) =>
          set((state) => ({
            run: {
              ...state.run,
              status: String(data.message ?? state.run.status),
              progress: typeof data.progress === "number" ? data.progress : state.run.progress,
            },
          })),
        token: (data) =>
          set((state) => ({ run: { ...state.run, reply: state.run.reply + (data.text ?? "") } })),
        // A deck snapshot mid-run lets the preview fill in while slides are still
        // being written, rather than staying blank until the turn ends.
        deck: () => void get().refreshDeck(get().presentation?.id),
        artifact: (data) =>
          set((state) => ({ artifacts: [...state.artifacts, data as Artifact] })),
        message: (data) => {
          const message = data as Message;
          set((state) => ({
            messages: [...state.messages.filter((m) => m.id !== optimistic.id), optimistic, message],
            run: IDLE,
          }));
          if (message.presentation_id) void get().refreshDeck(message.presentation_id);
          void get().loadConversations();
        },
        error: (data) =>
          set((state) => ({
            run: { ...state.run, active: false, error: String(data.message ?? "Something failed") },
          })),
        done: () => set((state) => ({ run: { ...state.run, active: false }, abort: null })),
        onError: (message) =>
          set((state) => ({ run: { ...state.run, active: false, error: message } })),
      },
      { presentationId: get().presentation?.id ?? null, signal: controller.signal },
    );
  },

  cancel() {
    get().abort?.abort();
    set({ run: IDLE, abort: null });
  },

  async refreshDeck(presentationId) {
    const id = presentationId ?? get().presentation?.id;
    if (!id) return;
    const [presentation, render] = await Promise.all([
      api.getPresentation(id),
      api.renderPayload(id),
    ]);
    set((state) => ({
      presentation,
      render,
      slideIndex: Math.min(state.slideIndex, Math.max(0, render.slides.length - 1)),
    }));
  },

  selectSlide(index) {
    const total = get().render?.slides.length ?? 0;
    if (total === 0) return;
    set({ slideIndex: Math.max(0, Math.min(index, total - 1)) });
  },

  async applyOperations(operations, summary = "Manual edit") {
    const id = get().presentation?.id;
    if (!id || operations.length === 0) return;
    await api.applyOperations(id, operations, summary);
    await get().refreshDeck(id);
  },

  async setTheme(theme) {
    await get().applyOperations([{ op: "set_theme", theme }], `Switched to the ${theme} theme`);
  },

  async undo() {
    const id = get().presentation?.id;
    if (!id) return;
    await api.undo(id);
    await get().refreshDeck(id);
  },

  async restore(version) {
    const id = get().presentation?.id;
    if (!id) return;
    await api.restoreVersion(id, version);
    await get().refreshDeck(id);
  },

  async upload(files) {
    const conversationId = get().conversationId ?? (await get().newConversation());
    await api.uploadFiles(conversationId, files);
  },
}));
