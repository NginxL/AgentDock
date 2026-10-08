import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  clearModelCatalog,
  useModelCatalog,
  prewarmModels,
} from "./modelCatalog";

const models = [{ id: "model-a", name: "Model A", efforts: ["high"] }];
const response = (value = models) => ({
  ok: true,
  json: async () => ({ models: value }),
});
afterEach(() => {
  cleanup();
  clearModelCatalog();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("isolates model results by subscription account and login generation", async () => {
  const fetch = vi.fn(async (path: string) =>
    response([{ id: path, name: path, efforts: [] }]),
  );
  vi.stubGlobal("fetch", fetch);
  const view = renderHook(
    ({ account, generation }) =>
      useModelCatalog(
        "token",
        "codex",
        "local",
        true,
        undefined,
        account,
        generation,
      ),
    { initialProps: { account: "first", generation: 1 } },
  );
  await waitFor(() => expect(view.result.current.loading).toBe(false));
  expect(view.result.current.models[0].id).toContain("account_id=first");
  view.rerender({ account: "second", generation: 1 });
  expect(view.result.current.models).toEqual([]);
  await waitFor(() =>
    expect(view.result.current.models[0].id).toContain("account_id=second"),
  );
  view.rerender({ account: "second", generation: 2 });
  expect(view.result.current.models).toEqual([]);
  await waitFor(() => expect(view.result.current.loading).toBe(false));
  expect(fetch).toHaveBeenCalledTimes(3);
});

it("shares one in-flight read across menus and conversations", async () => {
  let finish!: (value: ReturnType<typeof response>) => void;
  const fetch = vi.fn(
    () =>
      new Promise<ReturnType<typeof response>>((resolve) => {
        finish = resolve;
      }),
  );
  vi.stubGlobal("fetch", fetch);
  const first = renderHook(
    ({ open }) => useModelCatalog("token", "codex", "remote", true, open),
    { initialProps: { open: false } },
  );
  first.rerender({ open: true });
  first.rerender({ open: false });
  first.unmount();
  const second = renderHook(() =>
    useModelCatalog("token", "codex", "remote", true),
  );
  expect(fetch).toHaveBeenCalledTimes(1);
  await act(async () => finish(response()));
  await waitFor(() => expect(second.result.current.models).toEqual(models));
  const reopened = renderHook(() =>
    useModelCatalog("token", "codex", "remote", true),
  );
  expect(reopened.result.current.models).toEqual(models);
  expect(reopened.result.current.loading).toBe(false);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("keeps host, provider and workbench credentials separate", async () => {
  const fetch = vi.fn(async (_path: string) => response());
  vi.stubGlobal("fetch", fetch);
  const view = renderHook(
    ({ token, environment, provider }) =>
      useModelCatalog(token, provider, environment, true),
    {
      initialProps: {
        token: "first",
        environment: "local",
        provider: "codex" as "codex" | "claude",
      },
    },
  );
  await waitFor(() => expect(view.result.current.models).toEqual(models));
  for (const props of [
    { token: "first", environment: "devbox", provider: "codex" as const },
    { token: "first", environment: "devbox", provider: "claude" as const },
    { token: "second", environment: "devbox", provider: "claude" as const },
  ]) {
    view.rerender(props);
    expect(view.result.current.models).toEqual([]);
    await waitFor(() => expect(view.result.current.models).toEqual(models));
  }
  expect(fetch.mock.calls.map((c) => c[0])).toEqual([
    "/api/models/codex?environment_id=local",
    "/api/models/codex?environment_id=devbox",
    "/api/models/claude?environment_id=devbox",
    "/api/models/claude?environment_id=devbox",
  ]);
});

it("refreshes expired metadata without blanking the list and retries failures", async () => {
  const clock = vi.spyOn(Date, "now").mockReturnValue(1_000);
  const fetch = vi.fn(async (_path: string) => response());
  vi.stubGlobal("fetch", fetch);
  const view = renderHook(
    ({ visit }) => useModelCatalog("token", "codex", "remote", true, visit),
    { initialProps: { visit: 0 } },
  );
  await waitFor(() => expect(view.result.current.models).toEqual(models));
  clock.mockReturnValue(62_000);
  fetch.mockRejectedValueOnce(new Error("offline"));
  view.rerender({ visit: 1 });
  expect(view.result.current.models).toEqual(models);
  expect(view.result.current.loading).toBe(false);
  await waitFor(() => expect(view.result.current.failed).toBe(true));
  view.rerender({ visit: 2 });
  await waitFor(() => expect(view.result.current.failed).toBe(false));
  expect(fetch).toHaveBeenCalledTimes(3);
});

it("invalidates on reconnect and never prefetches in review or demo mode", async () => {
  const fetch = vi.fn(async (_path: string) => response());
  vi.stubGlobal("fetch", fetch);
  const view = renderHook(
    ({ enabled, visit }) =>
      useModelCatalog("token", "codex", "remote", enabled, visit),
    { initialProps: { enabled: false, visit: 0 } },
  );
  expect(fetch).not.toHaveBeenCalled();
  view.rerender({ enabled: true, visit: 0 });
  await waitFor(() => expect(view.result.current.models).toEqual(models));
  clearModelCatalog();
  view.rerender({ enabled: true, visit: 1 });
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
});

it("prewarms configured pairs once and shares the result with the first menu", async () => {
  const fetch = vi.fn(async () => response());
  vi.stubGlobal("fetch", fetch);
  await prewarmModels("token", [
    { provider: "codex", environment: "devbox" },
    { provider: "codex", environment: "devbox" },
    { provider: "claude", environment: "local" },
  ]);
  expect(fetch).toHaveBeenCalledTimes(2);
  const menu = renderHook(() =>
    useModelCatalog("token", "codex", "devbox", true),
  );
  expect(menu.result.current.models).toEqual(models);
  expect(menu.result.current.loading).toBe(false);
  expect(fetch).toHaveBeenCalledTimes(2);
});
