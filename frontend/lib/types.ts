/** Types mirroring the backend's Pydantic schemas. */

export type Role = "user" | "assistant" | "system" | "tool";

/** How much prose each slide carries. Mirrors the backend `ContentDensity`. */
export type ContentDensity = "concise" | "balanced" | "rich";

export interface Conversation {
  id: string;
  title: string;
  archived: boolean;
  created_at: string;
  updated_at: string;
  settings: Record<string, unknown>;
  message_count: number;
  presentation_count: number;
  latest_presentation_id: string | null;
}

export interface Artifact {
  id: string;
  format: string;
  filename: string;
  size_bytes: number;
  download_url: string;
}

export interface MessageMetadata {
  intent?: string;
  changed?: boolean;
  changelog?: string[];
  questions?: string[];
  artifacts?: Artifact[];
  review?: { score: number; verdict: string; issues: number };
  error?: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: Role;
  content: string;
  created_at: string;
  metadata: MessageMetadata;
  presentation_id: string | null;
  presentation_version: number | null;
}

export interface VersionSummary {
  id: string;
  version: number;
  label: string;
  created_at: string;
  slide_count: number;
}

export interface PresentationSummary {
  id: string;
  conversation_id: string;
  title: string;
  theme: string;
  slide_count: number;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Presentation extends PresentationSummary {
  deck: Deck;
  versions: VersionSummary[];
}

export interface Deck {
  id: string;
  title: string;
  subtitle?: string | null;
  theme: string;
  slides: DeckSlide[];
  sections: { id: string; title: string }[];
  meta: Record<string, unknown>;
  version: number;
}

export interface DeckSlide {
  id: string;
  kind: string;
  layout: string;
  title: string;
  subtitle?: string | null;
  notes: string;
  hidden?: boolean;
  locked?: boolean;
}

/** A slide pre-rendered by the backend, ready to inject. */
export interface RenderedSlide {
  id: string;
  index: number;
  html: string;
  layout: string;
  kind: string;
  title: string;
  notes: string;
}

export interface RenderPayload {
  css: string;
  theme: string;
  mode: "light" | "dark";
  slides: RenderedSlide[];
}

export interface ThemeInfo {
  name: string;
  label: string;
  description: string;
  tags: string[];
  mode: string;
  palette: Record<string, string>;
  fonts: Record<string, string>;
  source: string;
}

export interface LayoutInfo {
  name: string;
  label: string;
  description: string;
  slots: string[];
  suits: string[];
}

/** A saved LLM connection. The API key itself is never sent to the client. */
export interface LlmConnection {
  id: string;
  name: string;
  provider: string;
  provider_label: string;
  kind: "local" | "cloud";
  base_url: string | null;
  model: string;
  temperature: number | null;
  max_tokens: number | null;
  is_active: boolean;
  has_api_key: boolean;
  api_key_hint: string | null;
  options: Record<string, unknown>;
  last_checked_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

/** Defaults used to prefill the "add a connection" form. */
export interface ProviderTemplate {
  name: string;
  label: string;
  kind: "local" | "cloud";
  requires_api_key: boolean;
  default_base_url: string | null;
  default_model: string;
  suggested_models: string[];
  configured_from_env: boolean;
  note: string | null;
}

export interface LlmProbeResult {
  ok: boolean;
  provider: string;
  models: string[];
  model_available: boolean | null;
  latency_ms: number | null;
  error: string | null;
  hint: string | null;
}

export interface ProviderInfo {
  name: string;
  label: string;
  kind: "local" | "cloud";
  configured: boolean;
  base_url: string | null;
  models: string[];
  note: string | null;
}

export interface ExportFormat {
  name: string;
  label: string;
  extension: string;
  media_type: string;
  binary: boolean;
  description: string;
}

export interface AssetInfo {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  kind: string;
  indexed: boolean;
  excerpt: string | null;
}

/** Server-sent events emitted during a turn. */
export type RunEventName =
  | "status"
  | "token"
  | "deck"
  | "slide"
  | "artifact"
  | "message"
  | "error"
  | "done";

export interface RunEvent {
  event: RunEventName;
  data: Record<string, any>;
}

/** A deck operation — the same edit language the agents emit. */
export interface DeckOperation {
  op: string;
  [key: string]: unknown;
}
