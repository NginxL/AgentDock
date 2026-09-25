export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Same-origin only. Credentials live in React memory, never in URLs or browser storage. */
export async function request<T>(
  token: string,
  path: string,
  data?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  if (!path.startsWith("/api/") || path.includes("://"))
    throw new Error("Invalid API path");
  const response = await fetch(path, {
    method: data === undefined ? "GET" : "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
      ...(data === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: data === undefined ? undefined : JSON.stringify(data),
    credentials: "omit",
    cache: "no-store",
    redirect: "error",
    signal,
  });
  let result: unknown;
  try {
    result = await response.json();
  } catch {
    throw new ApiError(response.status, "Invalid server response");
  }
  if (!response.ok) {
    const message =
      typeof result === "object" &&
      result !== null &&
      "error" in result &&
      typeof result.error === "string"
        ? result.error
        : `HTTP ${response.status}`;
    throw new ApiError(response.status, message);
  }
  return result as T;
}

export function listOf<T>(items: T[] | Record<string, T> | undefined): T[] {
  return Array.isArray(items) ? items : Object.values(items ?? {});
}
export function remainingPercent(
  value: number | undefined | null,
): number | null {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(100, Math.max(0, value))
    : null;
}
