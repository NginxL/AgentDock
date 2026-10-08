/** Global notifications contain only a version, authenticated without URL tokens. */
export async function watchState(
  token: string,
  signal: AbortSignal,
  changed: (version: string) => void,
) {
  const response = await fetch("/api/state/stream", {
    headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
    credentials: "omit",
    cache: "no-store",
    redirect: "error",
    signal,
  });
  if (
    !response.ok ||
    !response.body ||
    !response.headers.get("Content-Type")?.startsWith("text/event-stream")
  ) {
    throw new Error("State notifications unavailable");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (!signal.aborted) {
      const result = await reader.read();
      if (result.done) break;
      buffer += decoder.decode(result.value, { stream: true });
      if (buffer.length > 8192) throw new Error("State notification too large");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const line = frame
          .split("\n")
          .find((value) => value.startsWith("data: "));
        if (!line) continue;
        const payload = JSON.parse(line.slice(6));
        if (typeof payload.version === "string") changed(payload.version);
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
