import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import Workspace from "./views/Workspace";
import { clearModelCatalog } from "./modelCatalog";
import type { DockState, Mutate } from "./types";

afterEach(() => {
  cleanup();
  clearModelCatalog();
  vi.unstubAllGlobals();
});
const agent = {
  id: "a",
  name: "Helper",
  provider: "codex" as const,
  project_id: null,
  role: "",
};
const session = {
  id: "s",
  agent_id: "a",
  title: "Chat",
  project_id: null,
  status: "idle",
  created_at: "",
  updated_at: "",
};
const state: DockState = {
  runtime: { enabled: true, version: "0.3.0" },
  projects: [],
  agents: [agent],
  sessions: [session],
  runs: [],
  messages: [],
  memories: [],
  proposals: [],
  events: [],
  quotas: [],
  subscriptions: [],
  approvals: [],
};
function setup(
  mutate: Mutate = vi.fn(async () => true),
  enabled = true,
  busy = false,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ events: [], models: [] }),
    })),
  );
  render(
    <Workspace
      state={state}
      agents={[agent]}
      sessions={[session]}
      approvals={[]}
      token="fixture"
      t={(zh) => zh}
      lang="zh"
      runtimeEnabled={enabled}
      busy={busy}
      mutate={mutate}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /^Helper/ }));
  return {
    mutate,
    input: screen.getByLabelText("给 Agent 的任务") as HTMLTextAreaElement,
  };
}

it("sends on Enter once and preserves draft until a successful response", async () => {
  let resolve!: (ok: boolean) => void;
  const mutate = vi.fn<Mutate>(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const { input } = setup(mutate);
  fireEvent.change(input, { target: { value: " hello " } });
  fireEvent.keyDown(input, { key: "Enter" });
  fireEvent.keyDown(input, { key: "Enter" });
  fireEvent.keyDown(input, { key: "Enter", repeat: true });
  expect(mutate).toHaveBeenCalledTimes(1);
  expect(mutate).toHaveBeenCalledWith(
    "/api/sessions/s/run",
    { prompt: "hello" },
    expect.any(Function),
  );
  expect(input.value).toBe(" hello ");
  resolve(false);
  await waitFor(() => expect(input.disabled).toBe(false));
});

it("keeps Shift+Enter and IME confirmation out of the submit path", () => {
  const { input, mutate } = setup();
  fireEvent.change(input, { target: { value: "你好" } });
  expect(fireEvent.keyDown(input, { key: "Enter", shiftKey: true })).toBe(true);
  expect(fireEvent.keyDown(input, { key: "Enter", isComposing: true })).toBe(
    true,
  );
  expect(fireEvent.keyDown(input, { key: "Enter", keyCode: 229 })).toBe(true);
  fireEvent.compositionStart(input);
  expect(fireEvent.keyDown(input, { key: "Enter" })).toBe(true);
  fireEvent.compositionEnd(input);
  expect(mutate).not.toHaveBeenCalled();
});

it.each([
  [false, false],
  [true, true],
  [true, false],
])(
  "does not send disabled or empty input (enabled=%s, busy=%s)",
  (enabled, busy) => {
    const { input, mutate } = setup(undefined, enabled, busy);
    fireEvent.change(input, {
      target: { value: enabled && !busy ? "  " : "draft" },
    });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.submit(input.form!);
    expect(mutate).not.toHaveBeenCalled();
  },
);
