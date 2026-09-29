import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import Workspace from "./views/Workspace";
import type { Agent, DockState, Language, Provider } from "./types";

afterEach(cleanup);
const state: DockState = {
  projects: [],
  agents: [],
  sessions: [],
  runs: [],
  messages: [],
  memories: [],
  proposals: [],
  events: [],
  quotas: [],
  approvals: [],
  subscriptions: [],
  runtime: { enabled: true, version: "0.3.0" },
  environments: [
    { id: "remote", name: "Devbox", kind: "ssh", status: "connected" },
  ],
};
function setup(
  lang: Language = "zh",
  agents: Agent[] = [],
  extra: Partial<DockState> = {},
) {
  const mutate = vi.fn(async () => true);
  render(
    <Workspace
      t={(zh, en) => (lang === "zh" ? zh : en)}
      lang={lang}
      state={{ ...state, ...extra, agents }}
      agents={agents}
      sessions={[]}
      approvals={[]}
      token="fixture"
      demo
      runtimeEnabled
      busy={false}
      mutate={mutate}
    />,
  );
  if (agents.length)
    fireEvent.click(
      screen.getByRole("button", { name: new RegExp("^" + agents[0].name) }),
    );
  return mutate;
}

it.each<[Provider, string]>([
  ["codex", "local"],
  ["claude", "local"],
  ["codex", "remote"],
  ["claude", "remote"],
])(
  "creates %s on %s with an explicitly selected permission mode",
  async (provider, environment) => {
    const mutate = setup();
    fireEvent.click(screen.getByRole("button", { name: "添加 Agent" }));
    const permissions = screen.getByLabelText("访问权限") as HTMLSelectElement;
    expect(permissions.value).toBe("ask");
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "My helper" },
    });
    fireEvent.click(screen.getByRole("combobox", { name: "服务" }));
    fireEvent.click(
      screen.getByRole("option", {
        name: provider === "claude" ? "Claude Code" : "Codex",
      }),
    );
    fireEvent.change(screen.getByLabelText("设备"), {
      target: { value: environment },
    });
    fireEvent.change(permissions, { target: { value: "full_access" } });
    expect(screen.getByText(/Agent 可在所选环境中读写文件/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "创建 Agent" }));
    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith(
        "/api/agents",
        expect.objectContaining({
          provider,
          environment_id: environment,
          permission_mode: "full_access",
        }),
        expect.any(Function),
      ),
    );
  },
);

it("loads saved permissions, permits downgrading, and resets new agents to the default", async () => {
  const mutate = setup("en", [
    {
      id: "a",
      name: "Helper",
      provider: "claude",
      project_id: null,
      role: "",
      permission_mode: "full_access",
    },
  ]);
  fireEvent.click(screen.getByRole("button", { name: "Configure Helper" }));
  const permissions = screen.getByLabelText(
    "Access permissions",
  ) as HTMLSelectElement;
  expect(permissions.value).toBe("full_access");
  expect(screen.getByRole("option", { name: "Full access" })).toBeTruthy();
  expect(
    screen.getByText(/System account and organization policies still apply/),
  ).toBeTruthy();
  fireEvent.change(permissions, { target: { value: "ask" } });
  fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith(
      "/api/agents/a",
      expect.objectContaining({ permission_mode: "ask" }),
      expect.any(Function),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Back to agents" }));
  fireEvent.click(screen.getByRole("button", { name: "Add agent" }));
  expect(
    (screen.getByLabelText("Access permissions") as HTMLSelectElement).value,
  ).toBe("ask");
});

it.each(["queued", "running"])(
  "disables permission edits during a %s task",
  (status) => {
    setup(
      "zh",
      [
        {
          id: "a",
          name: "Helper",
          provider: "codex",
          project_id: null,
          role: "",
        },
      ],
      {
        runs: [
          {
            id: "r",
            agent_id: "a",
            session_id: "s",
            project_id: null,
            prompt: "Task",
            status,
            origin: "human",
            depth: 0,
            created_at: "",
            updated_at: "",
          },
        ],
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "设置 Helper" }));
    expect(
      (screen.getByLabelText("访问权限") as HTMLSelectElement).disabled,
    ).toBe(true);
  },
);
