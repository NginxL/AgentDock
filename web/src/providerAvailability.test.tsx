import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { useProviderAvailability } from "./providerAvailability";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("does not substitute local providers while a remote device is loading", async () => {
  let local!: (value: Response) => void;
  let remote!: (value: Response) => void;
  const fetcher = vi.fn(
    (path: string) =>
      new Promise<Response>((resolve) => {
        if (path.includes("environment_id=local")) local = resolve;
        else remote = resolve;
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  const { result, rerender } = renderHook(
    ({ device }) => useProviderAvailability("token", device, true, false),
    { initialProps: { device: "local" } },
  );
  rerender({ device: "remote" });
  await act(async () =>
    local(
      new Response(
        JSON.stringify({
          environment_id: "local",
          providers: { codex: { available: true } },
        }),
      ),
    ),
  );
  expect(result.current.providers).toBeUndefined();
  expect(result.current.loading).toBe(true);
  await act(async () =>
    remote(
      new Response(
        JSON.stringify({
          environment_id: "remote",
          providers: { gemini: { available: true } },
        }),
      ),
    ),
  );
  await waitFor(() =>
    expect(result.current.providers?.gemini?.available).toBe(true),
  );
  expect(result.current.providers?.codex).toBeUndefined();
  expect(result.current.loading).toBe(false);
});

it("fails closed and refreshes after installation without making demo requests", async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new Error("offline"));
  vi.stubGlobal("fetch", fetcher);
  const { result, rerender } = renderHook(
    ({ demo }) => useProviderAvailability("token", "local", true, demo),
    { initialProps: { demo: true } },
  );
  expect(fetcher).not.toHaveBeenCalled();
  rerender({ demo: false });
  await waitFor(() => expect(result.current.failed).toBe(true));
  expect(result.current.providers).toEqual({});
  fetcher.mockResolvedValue(
    new Response(
      JSON.stringify({
        environment_id: "local",
        providers: { qwen: { available: true } },
      }),
    ),
  );
  act(() => result.current.refresh());
  expect(result.current.loading).toBe(true);
  await waitFor(() =>
    expect(result.current.providers?.qwen?.available).toBe(true),
  );
});
