/**
 * Typed client for the DeckForge API.
 *
 * Requests go straight to the backend origin rather than through a Next.js
 * rewrite: the dev-server proxy buffers responses, which silently breaks the
 * Server-Sent Events stream that drives live progress. The backend allows the
 * frontend origin via `DECKFORGE_CORS_ORIGINS`.
 */

import type {
  AssetInfo,
  Conversation,
  DeckOperation,
  ExportFormat,
  LayoutInfo,
  LlmConnection,
  LlmProbeResult,
  Message,
  Presentation,
  ProviderInfo,
  ProviderTemplate,
  RenderPayload,
  RunEvent,
  RunEventName,
  ThemeInfo,
} from "./types";

/**
 * Backend origin.
 *
 * Empty means same-origin, which is how the desktop build runs: FastAPI serves
 * this bundle itself. `npm run dev` sets `NEXT_PUBLIC_API_URL` via
 * `.env.development` because the UI is then on a different port.
 */
export const API_ORIGIN = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");

const BASE = `${API_ORIGIN}/api/v1`;

/** Turn a backend-relative URL (as returned in artifacts) into an absolute one. */
export function absoluteUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_ORIGIN}${path}`;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code = "error",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "content-type": "application/json" }
        : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    let code = "error";
    try {
      const body = await response.json();
      message = body?.error?.message ?? body?.detail ?? message;
      code = body?.error?.code ?? code;
    } catch {
      /* non-JSON error body — keep the status text */
    }
    throw new ApiError(message, response.status, code);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  // -- conversations ------------------------------------------------------ //
  listConversations: () => request<Conversation[]>("/conversations"),

  createConversation: (title?: string, settings?: Record<string, unknown>) =>
    request<Conversation>("/conversations", {
      method: "POST",
      body: JSON.stringify({ title, settings }),
    }),

  getConversation: (id: string) => request<Conversation>(`/conversations/${id}`),

  updateConversation: (id: string, patch: { title?: string; settings?: Record<string, unknown> }) =>
    request<Conversation>(`/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteConversation: (id: string) =>
    request<void>(`/conversations/${id}`, { method: "DELETE" }),

  listMessages: (id: string) => request<Message[]>(`/conversations/${id}/messages`),

  uploadFiles: (id: string, files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<AssetInfo[]>(`/conversations/${id}/uploads`, { method: "POST", body: form });
  },

  listAssets: (id: string) => request<AssetInfo[]>(`/conversations/${id}/assets`),

  // -- presentations ------------------------------------------------------ //
  getPresentation: (id: string) => request<Presentation>(`/presentations/${id}`),

  renderPayload: (id: string) => request<RenderPayload>(`/presentations/${id}/stylesheet`),

  applyOperations: (id: string, operations: DeckOperation[], summary = "Manual edit") =>
    request<Presentation>(`/presentations/${id}/operations`, {
      method: "POST",
      body: JSON.stringify({ summary, operations }),
    }),

  undo: (id: string) => request<Presentation>(`/presentations/${id}/undo`, { method: "POST" }),

  restoreVersion: (id: string, version: number) =>
    request<Presentation>(`/presentations/${id}/versions/${version}/restore`, { method: "POST" }),

  fork: (id: string, version?: number) =>
    request<Presentation>(
      `/presentations/${id}/fork${version ? `?version=${version}` : ""}`,
      { method: "POST" },
    ),

  // -- LLM connections ---------------------------------------------------- //
  providerTemplates: () => request<ProviderTemplate[]>("/llm/providers"),

  listConnections: () => request<LlmConnection[]>("/llm/connections"),

  createConnection: (payload: Partial<LlmConnection> & { api_key?: string | null }) =>
    request<LlmConnection>("/llm/connections", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  /**
   * Partial update. Omit `api_key` to keep the stored key — the client never
   * receives it, so sending the masked hint back would destroy it.
   */
  updateConnection: (id: string, patch: Record<string, unknown>) =>
    request<LlmConnection>(`/llm/connections/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteConnection: (id: string) =>
    request<void>(`/llm/connections/${id}`, { method: "DELETE" }),

  activateConnection: (id: string) =>
    request<LlmConnection>(`/llm/connections/${id}/activate`, { method: "POST" }),

  testConnection: (payload: {
    provider?: string;
    base_url?: string | null;
    api_key?: string | null;
    model?: string;
    profile_id?: string;
  }) => request<LlmProbeResult>("/llm/test", { method: "POST", body: JSON.stringify(payload) }),

  // -- catalog ------------------------------------------------------------ //
  listThemes: () => request<ThemeInfo[]>("/themes"),
  listLayouts: () => request<LayoutInfo[]>("/layouts"),
  listProviders: () => request<ProviderInfo[]>("/providers"),
  listFormats: () => request<ExportFormat[]>("/formats"),

  providerModels: (name: string) =>
    request<{ provider: string; models: string[]; reachable: boolean; error?: string }>(
      `/providers/${name}/models`,
    ),

  downloadUrl: (presentationId: string, format: string) =>
    `${BASE}/presentations/${presentationId}/download?format=${format}`,
};

/**
 * Stream one conversational turn.
 *
 * `EventSource` cannot POST, so the stream is read from `fetch` and the SSE
 * framing is parsed here. Returns an abort handle so the UI can cancel a run.
 */
export function streamMessage(
  conversationId: string,
  content: string,
  handlers: Partial<Record<RunEventName, (data: any) => void>> & {
    onError?: (message: string) => void;
  },
  options: { presentationId?: string | null; signal?: AbortSignal } = {},
): Promise<void> {
  return (async () => {
    let response: Response;
    try {
      response = await fetch(`${BASE}/conversations/${conversationId}/messages`, {
        method: "POST",
        headers: { "content-type": "application/json", accept: "text/event-stream" },
        body: JSON.stringify({ content, presentation_id: options.presentationId ?? null }),
        signal: options.signal,
      });
    } catch (error) {
      if ((error as Error).name === "AbortError") return;
      handlers.onError?.((error as Error).message);
      return;
    }

    if (!response.ok || !response.body) {
      handlers.onError?.(`The server returned ${response.status}.`);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const dispatch = (raw: string) => {
      let name: RunEventName = "status";
      const dataLines: string[] = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) name = line.slice(6).trim() as RunEventName;
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) return;
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse(dataLines.join("\n"));
      } catch {
        return;
      }
      handlers[name]?.(data);
    };

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary = buffer.indexOf("\n\n");
        while (boundary !== -1) {
          dispatch(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 2);
          boundary = buffer.indexOf("\n\n");
        }
      }
      if (buffer.trim()) dispatch(buffer);
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        handlers.onError?.((error as Error).message);
      }
    }
  })();
}

export type { RunEvent };
