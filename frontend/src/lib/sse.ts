import type { LogEvent } from "./types";

export type LogHandler = (event: LogEvent) => void;
export type DoneHandler = () => void;
export type ErrorHandler = (err: Error) => void;

export interface LogStreamOptions {
  maxRetries?: number;
  baseDelayMs?: number;
  getStatus?: () => Promise<{ stage: string }>;
  onReconnect?: (attempt: number) => void;
}

const TERMINAL_STAGES = new Set(["done", "failed", "stopped"]);

export function openLogStream(
  url: string,
  onLog: LogHandler,
  onEnd: DoneHandler,
  onError: ErrorHandler,
  options: LogStreamOptions = {},
): () => void {
  const maxRetries = options.maxRetries ?? 10;
  const baseDelayMs = options.baseDelayMs ?? 2000;
  let es: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;
  let retryCount = 0;

  function cleanupEs() {
    try {
      es?.close();
    } catch {
      /* ignore */
    }
    es = null;
  }

  function close() {
    if (closed) return;
    closed = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    cleanupEs();
  }

  function scheduleReconnect() {
    if (closed) return;
    if (retryCount >= maxRetries) {
      close();
      onError(new Error("SSE stream error"));
      return;
    }
    const delay = Math.min(baseDelayMs * 2 ** retryCount, 30000);
    retryCount += 1;
    try {
      options.onReconnect?.(retryCount);
    } catch {
      /* ignore */
    }
    reconnectTimer = setTimeout(() => {
      if (!closed) connect();
    }, delay);
  }

  async function handleStreamError() {
    if (closed) return;
    cleanupEs();
    if (options.getStatus) {
      try {
        const s = await options.getStatus();
        if (closed) return;
        if (s.stage === "done") {
          close();
          onEnd();
          return;
        }
        if (TERMINAL_STAGES.has(s.stage)) {
          close();
          onError(new Error(`Analysis ${s.stage}`));
          return;
        }
      } catch {
        /* status fetch failed - fall through to reconnect */
      }
      if (closed) return;
    }
    scheduleReconnect();
  }

  function connect() {
    if (closed) return;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    es = new EventSource(url);

    es.addEventListener("log", (ev) => {
      try {
        const data = JSON.parse((ev as MessageEvent).data);
        retryCount = 0;
        onLog(data as LogEvent);
      } catch (e) {
        close();
        onError(e as Error);
      }
    });
    es.addEventListener("end", () => {
      close();
      onEnd();
    });
    es.onerror = () => {
      void handleStreamError();
    };
  }

  connect();
  return close;
}
