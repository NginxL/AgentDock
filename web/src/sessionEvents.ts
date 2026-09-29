import { ApiError, request } from "./api";
import type { AgentEvent } from "./types";

function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    const done = () => {
      window.clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    };
    const timer = window.setTimeout(done, ms);
    signal.addEventListener("abort", done, { once: true });
    if (signal.aborted) done();
  });
}

/** History is authoritative. The authenticated stream resumes from its durable cursor. */
export async function followSession(
  token: string,
  session: string,
  signal: AbortSignal,
  onEvents: (events: AgentEvent[]) => void,
  onStatus: (failed: boolean) => void,
) {
  const path = `/api/sessions/${encodeURIComponent(session)}/events`;
  let cursor = 0;
  let streaming = true;
  let batch: AgentEvent[] = [];
  let timer: number | undefined;
  const flush = () => {
    window.clearTimeout(timer);
    timer = undefined;
    if (batch.length && !signal.aborted) onEvents(batch);
    batch = [];
  };
  const accept = (value: { events: AgentEvent[] }) => {
    if (!Array.isArray(value.events)) throw new Error("Invalid event list");
    for (const event of value.events) {
      if (!Number.isSafeInteger(event.seq) || event.session_id !== session)
        throw new Error("Invalid session event");
      if (event.seq <= cursor) continue;
      cursor = event.seq;
      batch.push(event);
    }
    if (
      batch.some(
        (e) => e.kind === "run_finished" || e.kind === "assistant_message",
      )
    )
      flush();
    else if (timer === undefined) timer = window.setTimeout(flush, 30);
    onStatus(false);
  };
  async function history() {
    while (!signal.aborted) {
      const value = await request<{ events: AgentEvent[] }>(
        token,
        `${path}?after=${cursor}`,
        undefined,
        signal,
      );
      if (signal.aborted) return;
      const previous = cursor;
      accept(value);
      if (value.events.length < 500 || cursor === previous) return;
    }
  }
  try {
    // Drain history before subscribing. The server's cursor also closes this race.
    while (!signal.aborted) {
      try {
        await history();
        break;
      } catch (error) {
        if (signal.aborted) return;
        onStatus(true);
        if (error instanceof ApiError && [401, 403, 404].includes(error.status))
          return;
        await delay(1000, signal);
      }
    }
    flush();
    while (!signal.aborted) {
      try {
        if (!streaming) {
          await delay(1000, signal);
          if (!signal.aborted) await history();
          continue;
        }
        const response = await fetch(`${path}/stream?after=${cursor}`, {
          headers: {
            Authorization: `Bearer ${token}`,
            Accept: "text/event-stream",
          },
          credentials: "omit",
          cache: "no-store",
          redirect: "error",
          signal,
        });
        if (signal.aborted) {
          await response.body?.cancel();
          return;
        }
        if (
          [404, 405, 501].includes(response.status) ||
          (response.ok && !response.body)
        ) {
          await response.body?.cancel();
          streaming = false;
          continue;
        }
        if (!response.ok)
          throw new ApiError(response.status, "Event stream unavailable");
        if (
          !response.headers.get("Content-Type")?.startsWith("text/event-stream")
        ) {
          await response.body?.cancel();
          throw new Error("Invalid stream type");
        }
        const reader = response.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        try {
          while (!signal.aborted) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            buffer = buffer.replace(/\r\n/g, "\n");
            let end: number;
            while ((end = buffer.indexOf("\n\n")) >= 0) {
              const frame = buffer.slice(0, end);
              buffer = buffer.slice(end + 2);
              if (frame.length > 2_097_152)
                throw new Error("Event frame too large");
              const data = frame
                .split("\n")
                .filter((line) => line.startsWith("data:"))
                .map((line) => line.slice(5).trimStart())
                .join("\n");
              if (data) accept(JSON.parse(data));
            }
            if (buffer.length > 2_097_152)
              throw new Error("Event frame too large");
          }
        } finally {
          await reader.cancel().catch(() => {});
          reader.releaseLock();
        }
        if (!signal.aborted) throw new Error("Event stream disconnected");
      } catch (error) {
        if (signal.aborted) return;
        flush();
        onStatus(true);
        if (error instanceof ApiError && [401, 403, 404].includes(error.status))
          return;
        await delay(1000, signal);
      }
    }
  } catch {
    if (!signal.aborted) onStatus(true);
  } finally {
    flush();
  }
}
