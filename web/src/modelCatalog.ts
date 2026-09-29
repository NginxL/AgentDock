import { useEffect, useState } from "react";
import { request } from "./api";
import type { Provider } from "./types";

export type Model = { id: string; name: string; efforts: string[] };
type Entry = {
  models?: Model[];
  expires: number;
  pending?: Promise<Model[]>;
};

// Memory only, scoped to the connected workbench and exact provider/host pair.
// Closing a menu does not cancel the shared discovery already in progress.
const entries = new Map<string, Entry>();
let credential = "";
const MAX_AGE = 60_000;

export function clearModelCatalog() {
  entries.clear();
  credential = "";
}

function entryFor(token: string, provider: Provider, environment: string) {
  if (credential !== token) {
    clearModelCatalog();
    credential = token;
  }
  const key = JSON.stringify([provider, environment]);
  let entry = entries.get(key);
  if (!entry) {
    entry = { expires: 0 };
    entries.set(key, entry);
  }
  return entry;
}

function load(token: string, provider: Provider, environment: string) {
  const entry = entryFor(token, provider, environment);
  if (entry.models && Date.now() < entry.expires)
    return Promise.resolve(entry.models);
  if (entry.pending) return entry.pending;
  entry.pending = request<{ models: Model[] }>(
    token,
    `/api/models/${provider}?environment_id=${encodeURIComponent(environment)}`,
  )
    .then((value) => {
      if (!Array.isArray(value.models))
        throw new Error("Invalid model catalog");
      entry.models = value.models;
      entry.expires = Date.now() + MAX_AGE;
      return entry.models;
    })
    .finally(() => {
      entry.pending = undefined;
    });
  return entry.pending;
}

export function useModelCatalog(
  token: string,
  provider: Provider,
  environment: string,
  enabled: boolean,
  refreshKey?: unknown,
) {
  const key = JSON.stringify([token, provider, environment]);
  const [state, setState] = useState<{
    key: string;
    models: Model[];
    loading: boolean;
    failed: boolean;
  }>();
  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    const cached = entryFor(token, provider, environment).models;
    setState({ key, models: cached ?? [], loading: !cached, failed: false });
    void load(token, provider, environment)
      .then((models) => {
        if (!disposed) setState({ key, models, loading: false, failed: false });
      })
      .catch(() => {
        if (!disposed)
          setState({ key, models: cached ?? [], loading: false, failed: true });
      });
    return () => {
      disposed = true;
    };
  }, [key, token, provider, environment, enabled, refreshKey]);
  if (!enabled) return { models: [], loading: false, failed: false };
  if (state?.key === key) return state;
  const cached = entryFor(token, provider, environment).models;
  return { models: cached ?? [], loading: !cached, failed: false };
}
