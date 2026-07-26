/**
 * Saving files, in the desktop shell and in a browser.
 *
 * `<a download href="…">` is not enough. In the desktop build the page runs in
 * an embedded WebView2, which hands downloads to the host application — and if
 * the host ignores them, the click does nothing at all: no file, no error, no
 * prompt. Browsers honour the attribute but give no way to report a failure.
 *
 * So: the desktop asks Python to fetch and save (native dialog included), and
 * the browser fetches a blob and clicks a synthetic link. Both report back.
 */

import { API_ORIGIN } from "./api";

interface BridgeResult {
  ok?: boolean;
  cancelled?: boolean;
  error?: string;
  path?: string;
  name?: string;
  bytes?: number;
}

interface DesktopBridge {
  is_desktop: () => Promise<boolean>;
  save_download: (apiPath: string, suggestedName: string) => Promise<BridgeResult>;
  reveal: (path: string) => Promise<BridgeResult>;
}

declare global {
  interface Window {
    pywebview?: { api?: Partial<DesktopBridge> };
  }
}

/** The desktop bridge, or null in a browser. */
export function bridge(): DesktopBridge | null {
  const api = typeof window !== "undefined" ? window.pywebview?.api : undefined;
  return api && typeof api.save_download === "function" ? (api as DesktopBridge) : null;
}

export function isDesktop(): boolean {
  return bridge() !== null;
}

export interface SaveOutcome {
  status: "saved" | "downloaded" | "cancelled" | "error";
  /** Absolute path, desktop only — enables "Show in folder". */
  path?: string;
  name?: string;
  message?: string;
}

/**
 * Save a file the API produces.
 *
 * @param apiPath  Path under `/api/v1/`, e.g. `/api/v1/presentations/x/download?format=pptx`.
 * @param filename Suggested name; the server's own filename wins if it sends one.
 */
export async function saveApiFile(apiPath: string, filename: string): Promise<SaveOutcome> {
  const desktop = bridge();
  if (desktop) {
    try {
      const result = await desktop.save_download(apiPath, filename);
      if (result.cancelled) return { status: "cancelled" };
      if (result.ok) return { status: "saved", path: result.path, name: result.name };
      return { status: "error", message: result.error ?? "The file could not be saved." };
    } catch (error) {
      return { status: "error", message: (error as Error).message };
    }
  }
  return browserDownload(`${API_ORIGIN}${apiPath}`, filename);
}

/** Fetch to a blob and click a synthetic link, so failures are visible. */
async function browserDownload(url: string, filename: string): Promise<SaveOutcome> {
  let response: Response;
  try {
    response = await fetch(url);
  } catch (error) {
    return { status: "error", message: (error as Error).message };
  }
  if (!response.ok) {
    return { status: "error", message: `The server returned ${response.status}.` };
  }

  const name = filenameFromHeaders(response.headers) ?? filename;
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = name;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    // Revoking immediately can cancel the download in some browsers.
    setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
  }
  return { status: "downloaded", name };
}

function filenameFromHeaders(headers: Headers): string | null {
  const disposition = headers.get("content-disposition");
  if (!disposition) return null;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  return match ? decodeURIComponent(match[1]) : null;
}

/** Show a saved file in the system file manager. Desktop only. */
export async function revealFile(path: string): Promise<boolean> {
  const desktop = bridge();
  if (!desktop) return false;
  try {
    return Boolean((await desktop.reveal(path)).ok);
  } catch {
    return false;
  }
}
