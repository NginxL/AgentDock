import { useEffect, useMemo } from "react";
import { QueryClient } from "@tanstack/react-query";

/** A connection owns its in-memory cache. Authentication never enters query keys. */
export function useConnectionQueries(credential: string) {
  const client = useMemo(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            gcTime: 60_000,
            refetchOnWindowFocus: false,
          },
          mutations: { retry: false },
        },
      }),
    [credential],
  );
  useEffect(() => () => client.clear(), [client]);
  return client;
}
