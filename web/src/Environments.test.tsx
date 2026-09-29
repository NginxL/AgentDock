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
import { clearModelCatalog } from "./modelCatalog";
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
  clearModelCatalog();
  vi.unstubAllGlobals();
});

it.each(["zh", "en"] as const)(
  "edits runtime location without replacing existing conversations (%s)",
  async (lang) => {
    const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
    const agent = {
      id: "helper",
      name: "Helper",
      provider: "claude" as const,
      project_id: null,
      role: "",
      environment_id: "local",
      workspace: "/local/project",
      model: "local-model",
      effort: "high",
      permission_mode: "ask" as const,
    };
    const session = {
      id: "old",
      agent_id: agent.id,
      project_id: null,
      title: "Original",
      status: "running",
      environment_id: "local",
      native_session_id: "original-native",
      created_at: "",
      updated_at: "",
    };
    const calls = vi.fn(async () => ({
      ok: true,
      json: async () => ({ models: [], events: [] }),
    }));
    vi.stubGlobal("fetch", calls);
    const mutate = vi.fn(async () => true);
    render(
      <Workspace
        state={{
          ...state,
          agents: [agent],
          sessions: [session],
          runs: [
            {
              id: "running",
              agent_id: agent.id,
              session_id: session.id,
              project_id: null,
              prompt: "Original task",
              status: "running",
              origin: "human",
              depth: 0,
              created_at: "",
              updated_at: "",
            },
          ],
        }}
        agents={[agent]}
        sessions={[session]}
        approvals={[]}
        token="fixture-edit"
        t={t}
        lang={lang}
        runtimeEnabled
        busy={false}
        mutate={mutate}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Helper/ }));
    const toggle = screen.getByRole("button", {
      name: t("设置 Helper", "Configure Helper"),
    });
    fireEvent.click(toggle);
    const runtime = screen.getByLabelText(
      t("设备", "Device"),
    ) as HTMLSelectElement;
    expect(runtime.disabled).toBe(false);
    const workspace = () =>
      screen.getByLabelText(
        t("工作目录（可留空）", "Working directory (optional)"),
      ) as HTMLInputElement;
    expect(workspace().disabled).toBe(true);
    fireEvent.change(runtime, { target: { value: "remote" } });
    expect(workspace().disabled).toBe(false);
    expect(workspace().value).toBe("");
    expect(
      (screen.getByLabelText(t("模型", "Model")) as HTMLSelectElement).value,
    ).toBe("");
    await waitFor(() =>
      expect(
        calls.mock.calls.some(
          (args: any[]) =>
            args[0] === "/api/models/claude?environment_id=remote",
        ),
      ).toBe(true),
    );
    // Changing one's mind restores the original defaults without a write.
    fireEvent.change(runtime, { target: { value: "local" } });
    expect(workspace().value).toBe("/local/project");
    expect(
      (screen.getByLabelText(t("模型", "Model")) as HTMLSelectElement).value,
    ).toBe("local-model");
    expect(mutate).not.toHaveBeenCalled();
    fireEvent.change(runtime, { target: { value: "remote" } });
    fireEvent.change(workspace(), { target: { value: "/remote/project" } });
    fireEvent.click(
      screen.getByRole("button", { name: t("保存设置", "Save settings") }),
    );
    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith(
        "/api/agents/helper",
        expect.objectContaining({
          environment_id: "remote",
          workspace: "/remote/project",
          model: null,
          effort: null,
        }),
        expect.any(Function),
      ),
    );
    expect(session.environment_id).toBe("local");
    expect(session.native_session_id).toBe("original-native");
    fireEvent.click(toggle);
    expect(screen.queryByLabelText(t("设备", "Device"))).toBeNull();
    fireEvent.click(toggle);
    fireEvent.click(
      screen.getByRole("button", {
        name: t("取消编辑 Agent", "Cancel editing agent"),
      }),
    );
    expect(screen.queryByLabelText(t("设备", "Device"))).toBeNull();
  },
);
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
  fireEvent.change(screen.getByLabelText("设备"), {
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
