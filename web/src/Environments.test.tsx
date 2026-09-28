import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import Usage from "./views/Usage";
import Workspace from "./views/Workspace";
import type { DockState } from "./types";
const state: DockState = {
  projects: [],
  agents: [],
  sessions: [],
  messages: [],
  memories: [],
  proposals: [],
  events: [],
  quotas: [],
  approvals: [],
  subscriptions: [],
  runtime: { enabled: true, version: "0.3.0" },
  environments: [
    { id: "local", name: "This Mac", kind: "local", status: "connected" },
    {
      id: "remote",
      name: "Devbox",
      kind: "ssh",
      ssh_host: "devbox",
      status: "connected",
    },
  ],
};
const t = (zh: string) => zh;
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("keeps the same provider's local and remote quota cards separate", () => {
  const agents = [
    {
      id: "a",
      name: "Local helper",
      provider: "codex" as const,
      project_id: null,
      role: "",
    },
    {
      id: "b",
      name: "Remote helper",
      provider: "codex" as const,
      project_id: null,
      role: "",
      environment_id: "remote",
    },
  ];
  render(
    <Usage
      agents={agents}
      t={t}
      lang="zh"
      quotas={[
        {
          provider: "codex",
          status: "available",
          source: "test",
          windows: [{ label: "Quota", remaining_percent: 80 }],
        },
        {
          provider: "codex",
          environment_id: "remote",
          status: "available",
          source: "ssh",
          windows: [{ label: "Quota", remaining_percent: 20 }],
        },
      ]}
      subscriptions={[]}
      onAddAgent={() => {}}
      refreshing={false}
      refreshFailed={false}
      busy={false}
      mutate={async () => true}
    />,
  );
  const local = screen.getByText("Local helper").closest("section")!;
  const remote = screen.getByText("Remote helper").closest("section")!;
  expect(within(local).getByText("80%")).toBeTruthy();
  expect(within(local).queryByText("20%")).toBeNull();
  expect(within(remote).getByText("20%")).toBeTruthy();
  expect(screen.queryByText("Devbox")).toBeNull();
  expect(screen.queryByText("本机")).toBeNull();
});
it("discovers models on the selected environment and binds a new independent agent to it", async () => {
  const calls = vi.fn(async () => ({
    ok: true,
    json: async () => ({ models: [] }),
  }));
  vi.stubGlobal("fetch", calls);
  const mutate = vi.fn(async () => true);
  render(
    <Workspace
      state={state}
      agents={[]}
      sessions={[]}
      approvals={[]}
      token="fixture"
      t={t}
      lang="zh"
      runtimeEnabled
      busy={false}
      mutate={mutate}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "添加 Agent" }));
  fireEvent.change(screen.getByLabelText("运行位置"), {
    target: { value: "remote" },
  });
  await waitFor(() =>
    expect(
      calls.mock.calls.some(
        (args: any[]) => args[0] === "/api/models/codex?environment_id=remote",
      ),
    ).toBe(true),
  );
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "Remote coder" },
  });
  fireEvent.click(screen.getByRole("button", { name: "创建 Agent" }));
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith(
      "/api/agents",
      expect.objectContaining({
        environment_id: "remote",
        provider: "codex",
        project_id: null,
      }),
      expect.any(Function),
    ),
  );
});
