import { useEffect } from "react";
import { QueryClient, useQuery } from "@tanstack/react-query";
import { request } from "./api";
import type { Provider } from "./types";

export type Model = { id: string; name: string; efforts: string[] };
// Credentials remain in closures; keys and the memory-only cache contain no tokens.
let credential = "";
const client = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      staleTime: 60_000,
      gcTime: 300_000,
      refetchOnWindowFocus: false,
    },
  },
});
export function clearModelCatalog() {
  client.clear();
  credential = "";
}
function entryFor(
  token: string,
  provider: Provider,
  environment: string,
  account?: string | null,
  generation?: number,
) {
  if (credential !== token) {
    clearModelCatalog();
    credential = token;
  }
  return [
    "models",
    provider,
    environment,
    account ?? null,
    generation ?? 0,
  ] as const;
}
function options(
  token: string,
  provider: Provider,
  environment: string,
  account?: string | null,
  generation?: number,
) {
  return {
    queryKey: entryFor(token, provider, environment, account, generation),
    queryFn: async () => {
      const value = await request<{ models: Model[] }>(
        token,
        `/api/models/${provider}?environment_id=${encodeURIComponent(environment)}${account ? `&account_id=${encodeURIComponent(account)}` : ""}`,
      );
      if (!Array.isArray(value.models))
        throw new Error("Invalid model catalog");
      return value.models;
    },
  };
}
function load(
  token: string,
  provider: Provider,
  environment: string,
  account?: string | null,
  generation?: number,
) {
  return client.fetchQuery(
    options(token, provider, environment, account, generation),
  );
}

/** Warm only configured connections; keep results in memory and coalesce with menus. */
export async function prewarmModels(
  token: string,
  connections: {
    provider: Provider;
    environment: string;
    account?: string | null;
    generation?: number;
  }[],
) {
  const unique = [
    ...new Map(
      connections.map((c) => [
        JSON.stringify([
          c.provider,
          c.environment,
          c.account ?? null,
          c.generation ?? 0,
        ]),
        c,
      ]),
    ).values(),
  ];
  if (unique.length)
    entryFor(
      token,
      unique[0].provider,
      unique[0].environment,
      unique[0].account,
      unique[0].generation,
    );
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(2, unique.length) }, async () => {
      while (next < unique.length && credential === token) {
        const connection = unique[next++];
        try {
          await load(
            token,
            connection.provider,
            connection.environment,
            connection.account,
            connection.generation,
          );
        } catch {
          /* Retry on next visit or refresh. */
        }
      }
    }),
  );
}

export function useModelCatalog(
  token: string,
  provider: Provider,
  environment: string,
  enabled: boolean,
  refreshKey?: unknown,
  account?: string | null,
  generation?: number,
) {
  const query = useQuery(
    { ...options(token, provider, environment, account, generation), enabled },
    client,
  );
  useEffect(() => {
    if (enabled)
      void load(token, provider, environment, account, generation).catch(
        () => {},
      );
  }, [token, provider, environment, enabled, refreshKey, account, generation]);
  return {
    models: enabled ? (query.data ?? []) : [],
    loading: enabled && query.isPending,
    failed: enabled && query.isError,
  };
}
