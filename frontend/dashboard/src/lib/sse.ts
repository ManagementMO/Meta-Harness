// EventSource wrapper for the multiplexed SSE channel that the backend
// exposes at GET /runs/{run_id}/stream. The 11 event types are the
// closed allowlist from streaming.py; backend rejects unknowns with a
// 500 so dashboard typings can stay tight.

import { API_BASE_URL } from "./api";

export type StreamingEventType =
  | "state-update"
  | "checkpoint-written"
  | "candidate-created"
  | "validate-result"
  | "eval-result"
  | "frontier-updated"
  | "iteration-complete"
  | "fork-created"
  | "branch-cancelled"
  | "memory-pattern-stored"
  | "error";

export type StreamingEvent<T = Record<string, unknown>> = {
  type: StreamingEventType;
  id: string;
  data: T;
};

export type StreamHandle = {
  close: () => void;
};

export function subscribeToRun(
  runId: string,
  handlers: Partial<Record<StreamingEventType, (e: StreamingEvent) => void>> &
    { onOpen?: () => void; onError?: (e: Event) => void },
): StreamHandle {
  const url = `${API_BASE_URL}/runs/${encodeURIComponent(runId)}/stream`;
  const source = new EventSource(url);
  if (handlers.onOpen) source.addEventListener("open", handlers.onOpen);
  if (handlers.onError) source.addEventListener("error", handlers.onError);

  for (const [type, handler] of Object.entries(handlers) as [
    string,
    (e: StreamingEvent) => void,
  ][]) {
    if (type === "onOpen" || type === "onError") continue;
    source.addEventListener(type, (raw) => {
      const evt = raw as MessageEvent<string>;
      try {
        handler({
          type: type as StreamingEventType,
          id: evt.lastEventId,
          data: JSON.parse(evt.data),
        });
      } catch {
        /* malformed payload — drop */
      }
    });
  }
  return { close: () => source.close() };
}
