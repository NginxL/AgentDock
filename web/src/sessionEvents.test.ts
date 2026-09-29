import { afterEach, expect, it, vi } from "vitest";
import { followSession } from "./sessionEvents";
import type { AgentEvent } from "./types";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
const event = (seq: number, kind = "agent_message_chunk"): AgentEvent => ({
  id: `e${seq}`,
  seq,
  session_id: "s",
  project_id: null,
  kind,
  payload: { text: "你好" },
  created_at: "",
});
function source() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(value) {
      controller = value;
    },
  });
  return {
    body,
    controller,
    send: (events: AgentEvent[]) =>
      controller.enqueue(
        new TextEncoder().encode(`data: ${JSON.stringify({ events })}\n\n`),
      ),
  };
}
const history = (events: AgentEvent[] = []) => ({
  ok: true,
  json: async () => ({ events }),
});
const response = (body: ReadableStream<Uint8Array>) => ({
  ok: true,
  status: 200,
  headers: new Headers({ "Content-Type": "text/event-stream" }),
  body,
});

it("uses bearer headers, resumes after history and streams split Unicode frames", async () => {
  const stream = source();
  const stop = new AbortController();
  const batches: AgentEvent[][] = [];
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(history([event(1)]))
    .mockResolvedValue(response(stream.body));
  vi.stubGlobal("fetch", fetch);
  const done = followSession(
    "secret",
    "s",
    stop.signal,
    (e) => batches.push(e),
    () => {},
  );
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(fetch.mock.calls[1][0]).toBe("/api/sessions/s/events/stream?after=1");
  expect(fetch.mock.calls[1][1].headers.Authorization).toBe("Bearer secret");
  const bytes = new TextEncoder().encode(
    `data: ${JSON.stringify({ events: [event(1), event(2, "assistant_message")] })}\n\n`,
  );
  for (const byte of bytes) stream.controller.enqueue(Uint8Array.of(byte));
  await vi.waitFor(() =>
    expect(batches.flat().map((e) => e.seq)).toEqual([1, 2]),
  );
  stop.abort();
  stream.controller.close();
  await done;
  expect(batches.flat()[1].payload).toEqual({ text: "你好" });
});

it("reconnects from last accepted event without reloading or duplicating history", async () => {
  vi.useFakeTimers();
  const first = source();
  const second = source();
  const stop = new AbortController();
  const received: AgentEvent[] = [];
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(history())
    .mockResolvedValueOnce(response(first.body))
    .mockResolvedValue(response(second.body));
  vi.stubGlobal("fetch", fetch);
  const done = followSession(
    "token",
    "s",
    stop.signal,
    (e) => received.push(...e),
    () => {},
  );
  await vi.advanceTimersByTimeAsync(0);
  first.send([event(1)]);
  first.controller.close();
  await vi.advanceTimersByTimeAsync(1010);
  expect(fetch.mock.calls[2][0]).toBe("/api/sessions/s/events/stream?after=1");
  second.send([event(1), event(2, "run_finished")]);
  await vi.advanceTimersByTimeAsync(0);
  expect(received.map((e) => e.seq)).toEqual([1, 2]);
  stop.abort();
  second.controller.close();
  await done;
});

it("falls back to cursor polling on an older server and cancels retry timers", async () => {
  vi.useFakeTimers();
  const stop = new AbortController();
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(history())
    .mockResolvedValueOnce({ ok: false, status: 404 })
    .mockResolvedValue(history([event(1)]));
  vi.stubGlobal("fetch", fetch);
  const onEvents = vi.fn();
  const done = followSession("token", "s", stop.signal, onEvents, () => {});
  await vi.advanceTimersByTimeAsync(1100);
  expect(onEvents).toHaveBeenCalledWith([event(1)]);
  stop.abort();
  await done;
  const calls = fetch.mock.calls.length;
  await vi.advanceTimersByTimeAsync(5000);
  expect(fetch).toHaveBeenCalledTimes(calls);
});

it("does not retry an authentication failure or show another session's events", async () => {
  const stop = new AbortController();
  const onEvents = vi.fn();
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(history())
    .mockResolvedValue({ ok: false, status: 401 });
  vi.stubGlobal("fetch", fetch);
  await followSession("token", "s", stop.signal, onEvents, () => {});
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(onEvents).not.toHaveBeenCalled();
});
