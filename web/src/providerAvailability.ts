import { useEffect, useState } from "react";
import { request } from "./api";
import type { ProviderAvailability } from "./types";

const demoProviders: ProviderAvailability = {
  codex: { available: true },
  claude: { available: true },
};

export function useProviderAvailability(
  token: string,
  environment: string,
  enabled: boolean,
  demo: boolean,
  refreshKey?: string,
) {
  const [revision, setRevision] = useState(0);
  const key = JSON.stringify([token, environment, refreshKey, revision]);
  const [result, setResult] = useState<{
    key: string;
    providers: ProviderAvailability;
    failed: boolean;
  }>();
  useEffect(() => {
    if (!enabled || demo) return;
    const controller = new AbortController();
    request<{ environment_id: string; providers: ProviderAvailability }>(
      token,
      `/api/providers?environment_id=${encodeURIComponent(environment)}`,
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (
          value.environment_id !== environment ||
          !value.providers ||
          typeof value.providers !== "object"
        )
          throw new Error("Invalid provider discovery");
        if (!controller.signal.aborted)
          setResult({ key, providers: value.providers, failed: false });
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setResult({ key, providers: {}, failed: true });
      });
    return () => controller.abort();
  }, [token, environment, enabled, demo, key]);
  return {
    providers: demo
      ? demoProviders
      : enabled && result?.key === key
        ? result.providers
        : undefined,
    loading: enabled && !demo && result?.key !== key,
    failed: !demo && enabled && result?.key === key && result.failed,
    refresh: () => setRevision((value) => value + 1),
  };
}
