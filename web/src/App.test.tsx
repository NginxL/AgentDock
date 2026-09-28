import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import App from "./App";
import { QuotaWindow } from "./views/Usage";
import { conversationEvents, eventText } from "./ui";
import { ApiError, remainingPercent, request } from "./api";
import { demoState } from "./demo";
import type { DockState } from "./types";

const state: DockState = {
  projects: [
    { id: "project-a", name: "Demo project", path: "/example/workspace" },
  ],
  agents: [
    {
      id: "agent-a",
      project_id: "project-a",
      provider: "codex",
      name: "Review agent",
      role: "Review changes",
    },
  ],
  sessions: [
    {
      id: "session-a",
      project_id: "project-a",
      agent_id: "agent-a",
      title: "First task",
      status: "idle",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
  messages: [],
  memories: [
    {
      id: "memory-a",
      project_id: "project-a",
      key: "project.stack",
      content: "Original reviewed content",
      version: 3,
    },
  ],
  proposals: [],
  events: [],
  quotas: [],
  approvals: [],
  subscriptions: [],
  runtime: { enabled: false, version: "0.1.0" },
};
function response(value: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => value,
  } as Response;
}
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn(async (path: string) =>
    response(path.includes("/events?") ? { events: [] } : state),
  );
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});
async function connect() {
  fireEvent.change(screen.getByLabelText("访问令牌"), {
    target: { value: "example-admin-token-not-a-real-secret" },
  });
  fireEvent.click(screen.getByRole("button", { name: "进入工作台" }));
  await screen.findByRole("heading", { name: "协作工作台" });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("user-defined agent roles", () => {
  it.each(["codex", "claude"])(
    "creates %s agents without assigning a role",
    async (provider) => {
      render(<App />);
      await connect();
      fireEvent.click(screen.getByRole("button", { name: "添加 Agent" }));
      const name = screen.getByLabelText("名称") as HTMLInputElement;
      const role = screen.getByLabelText(
        "角色说明（可选）",
      ) as HTMLTextAreaElement;
      expect(name.value).toBe("");
      expect(role.value).toBe("");
      fireEvent.change(name, { target: { value: "My helper" } });
      fireEvent.change(role, { target: { value: "Research requirements" } });
      fireEvent.change(screen.getByLabelText("服务"), {
        target: { value: "claude" },
      });
      fireEvent.change(screen.getByLabelText("服务"), {
        target: { value: "codex" },
      });
      expect(role.value).toBe("Research requirements");
      fireEvent.change(screen.getByLabelText("服务"), {
        target: { value: provider },
      });
      fireEvent.change(role, { target: { value: "" } });
      fireEvent.click(screen.getByRole("button", { name: "创建 Agent" }));
      await waitFor(() =>
        expect(
          fetchMock.mock.calls.some(([path]) => path === "/api/agents"),
        ).toBe(true),
      );
      const call = fetchMock.mock.calls.find(
        ([path]) => path === "/api/agents",
      )!;
      expect(JSON.parse(call[1].body)).toEqual({
        project_id: "project-a",
        name: "My helper",
        provider,
        role: "",
      });
    },
  );

  it("saves a new name and clears the role while keeping the selected native session", async () => {
    let current = {
      ...state,
      sessions: [
        { ...state.sessions[0], native_session_id: "existing-native-session" },
      ],
    };
    fetchMock.mockImplementation(
      async (path: string, options?: RequestInit) => {
        if (path === "/api/agents/agent-a") {
          const agent = {
            ...current.agents[0],
            ...JSON.parse(options!.body as string),
          };
          current = { ...current, agents: [agent] };
          return response(agent);
        }
        return response(path.includes("/events?") ? { events: [] } : current);
      },
    );
    render(<App />);
    await connect();
    fireEvent.click(
      screen.getByRole("button", { name: "编辑 Review agent 的角色" }),
    );
    expect((screen.getByLabelText("服务") as HTMLSelectElement).disabled).toBe(
      true,
    );
    expect(
      (screen.getByLabelText("角色说明（可选）") as HTMLTextAreaElement).value,
    ).toBe("Review changes");
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "Custom helper" },
    });
    fireEvent.change(screen.getByLabelText("角色说明（可选）"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存角色" }));
    await screen.findByRole("button", { name: "编辑 Custom helper 的角色" });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "保存角色" })).toBeNull(),
    );
    expect(screen.getByText("未设置角色 · 按任务要求执行")).toBeTruthy();
    expect(screen.getByText("existing-native-session")).toBeTruthy();
    const call = fetchMock.mock.calls.find(
      ([path]) => path === "/api/agents/agent-a",
    )!;
    expect(JSON.parse(call[1].body)).toEqual({
      name: "Custom helper",
      role: "",
    });
    expect(current.agents[0].provider).toBe("codex");
    fireEvent.click(
      screen.getByRole("button", { name: "编辑 Custom helper 的角色" }),
    );
    expect(
      (screen.getByLabelText("角色说明（可选）") as HTMLTextAreaElement).value,
    ).toBe("");
  });

  it("keeps an unsuccessful edit as a draft and lets the user cancel without writing", async () => {
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/api/agents/agent-a")
        return response({ error: "Temporary save failure" }, 500);
      return response(path.includes("/events?") ? { events: [] } : state);
    });
    render(<App />);
    await connect();
    fireEvent.click(
      screen.getByRole("button", { name: "编辑 Review agent 的角色" }),
    );
    fireEvent.change(screen.getByLabelText("角色说明（可选）"), {
      target: { value: "My unsaved role" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存角色" }));
    await screen.findByText("Temporary save failure");
    expect(
      (screen.getByLabelText("角色说明（可选）") as HTMLTextAreaElement).value,
    ).toBe("My unsaved role");
    expect(screen.getByText("Review changes")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "取消编辑 Agent" }));
    fireEvent.click(screen.getByRole("button", { name: "添加 Agent" }));
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe("");
    expect(
      (screen.getByLabelText("角色说明（可选）") as HTMLTextAreaElement).value,
    ).toBe("");
    expect((screen.getByLabelText("服务") as HTMLSelectElement).disabled).toBe(
      false,
    );
    expect(
      fetchMock.mock.calls.filter(([path]) => path === "/api/agents/agent-a"),
    ).toHaveLength(1);
  });

  it("translates role controls without changing user content", async () => {
    render(<App />);
    await connect();
    fireEvent.click(
      screen.getByRole("button", { name: "编辑 Review agent 的角色" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(
      screen.getByRole("heading", { name: "Edit agent · Review agent" }),
    ).toBeTruthy();
    expect(
      (screen.getByLabelText("Role (optional)") as HTMLTextAreaElement).value,
    ).toBe("Review changes");
    expect(screen.getByRole("button", { name: "Save role" })).toBeTruthy();
    expect(screen.queryByText("角色说明（可选）")).toBeNull();
  });

  it("shows no fixed provider roles in either demo language and never saves demo edits", async () => {
    for (const lang of ["zh", "en"] as const) {
      expect(
        demoState(lang).agents.map((agent) => [agent.name, agent.role]),
      ).toEqual([
        ["Agent A", ""],
        ["Agent B", ""],
      ]);
    }
    window.history.replaceState({}, "", "/?demo=1");
    render(<App />);
    await screen.findByRole("heading", { name: "协作工作台" });
    fireEvent.click(
      screen.getByRole("button", { name: "编辑 Agent A 的角色" }),
    );
    expect(
      (screen.getByRole("button", { name: "保存角色" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("selection after delayed mutation refresh", () => {
  it("selects a new project only after its refreshed state is available", async () => {
    const project = {
      id: "project-new",
      name: "New project",
      path: "/example/new",
    };
    const refreshed = deferred<Response>();
    let created = false;
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/api/projects") {
        created = true;
        return response(project);
      }
      if (path === "/api/state")
        return created ? refreshed.promise : response(state);
      return response({ events: [] });
    });
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "新建项目" }));
    fireEvent.change(screen.getByLabelText("项目名称"), {
      target: { value: project.name },
    });
    fireEvent.change(screen.getByLabelText("工作目录（绝对路径）"), {
      target: { value: project.path },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建项目" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([path]) => path === "/api/state"),
      ).toHaveLength(2),
    );
    expect((screen.getByLabelText("当前项目") as HTMLSelectElement).value).toBe(
      "project-a",
    );
    await act(async () => {
      refreshed.resolve(
        response({ ...state, projects: [...state.projects, project] }),
      );
    });
    await waitFor(() =>
      expect(
        (screen.getByLabelText("当前项目") as HTMLSelectElement).value,
      ).toBe(project.id),
    );
    expect(screen.queryByRole("button", { name: /Review agent/ })).toBeNull();
  });

  it("keeps the newly created agent selected after delayed refresh", async () => {
    const agent = {
      id: "agent-new",
      project_id: "project-a",
      provider: "claude",
      name: "New helper",
      role: "Review",
    };
    const refreshed = deferred<Response>();
    let created = false;
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/api/agents") {
        created = true;
        return response(agent);
      }
      if (path === "/api/state")
        return created ? refreshed.promise : response(state);
      return response({ events: [] });
    });
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "添加 Agent" }));
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: agent.name },
    });
    fireEvent.change(screen.getByLabelText("服务"), {
      target: { value: "claude" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建 Agent" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([path]) => path === "/api/state"),
      ).toHaveLength(2),
    );
    await act(async () => {
      refreshed.resolve(
        response({ ...state, agents: [...state.agents, agent] }),
      );
    });
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: /New helper/, pressed: true })
          .getAttribute("aria-pressed"),
      ).toBe("true"),
    );
    expect(screen.queryByRole("button", { name: "运行任务" })).toBeNull();
  });

  it("ignores an older poll and sends the next task to the newly created session", async () => {
    const enabled = { ...state, runtime: { enabled: true, version: "0.1.0" } };
    const session = {
      ...state.sessions[0],
      id: "session-new",
      title: "New task",
    };
    const olderPoll = deferred<Response>();
    const refreshed = deferred<Response>();
    const intervalSpy = vi.spyOn(window, "setInterval");
    let stateReads = 0;
    let created = false;
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/api/sessions") {
        created = true;
        return response(session);
      }
      if (path === "/api/state") {
        stateReads += 1;
        if (stateReads === 1) return response(enabled);
        if (stateReads === 2) return olderPoll.promise;
        if (stateReads === 3) return refreshed.promise;
        return response({ ...enabled, sessions: [...state.sessions, session] });
      }
      if (path.endsWith("/run"))
        return response({ id: "run-new", status: "running" });
      return response({ events: [] });
    });
    render(<App />);
    await connect();
    await screen.findByLabelText("给 Agent 的任务");
    const poll = intervalSpy.mock.calls.find(
      ([, delay]) => delay === 8000,
    )?.[0] as () => Promise<void>;
    expect(poll).toBeTypeOf("function");
    act(() => {
      void poll();
    });
    fireEvent.change(screen.getByLabelText("新会话标题"), {
      target: { value: session.title },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建会话" }));
    await waitFor(() => expect(created && stateReads === 3).toBe(true));
    expect(
      (screen.getByRole("button", { name: "运行任务" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    await act(async () => {
      refreshed.resolve(
        response({ ...enabled, sessions: [...state.sessions, session] }),
      );
    });
    await screen.findByRole("heading", { name: session.title });
    await act(async () => {
      olderPoll.resolve(response(enabled));
    });
    expect(screen.getByRole("heading", { name: session.title })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("给 Agent 的任务"), {
      target: { value: "Run in the new session only" },
    });
    fireEvent.click(screen.getByRole("button", { name: "运行任务" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([path]) => path === "/api/sessions/session-new/run",
        ),
      ).toBe(true),
    );
    expect(
      fetchMock.mock.calls.some(
        ([path]) => path === "/api/sessions/session-a/run",
      ),
    ).toBe(false);
  });
});

describe("connection boundaries", () => {
  it("starts in Chinese without any network call, execution, or quota read", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "连接本地工作台" }),
    ).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(document.documentElement.lang).toBe("zh-CN");
  });
  it("switches language without connecting", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(
      screen.getByRole("heading", { name: "Connect your local workspace" }),
    ).toBeTruthy();
    expect(document.documentElement.lang).toBe("en");
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("keeps the token out of browser storage and erases the UI on disconnect", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    render(<App />);
    await connect();
    expect(storage).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/state");
    expect(
      (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].headers,
    ).toMatchObject({
      Authorization: "Bearer example-admin-token-not-a-real-secret",
    });
    expect(document.body.textContent).not.toContain("example-admin-token");
    fireEvent.click(screen.getByRole("button", { name: "断开连接" }));
    expect(screen.getByLabelText("访问令牌").getAttribute("value")).toBe("");
    expect(screen.queryByText("Demo project")).toBeNull();
  });
  it("does not fetch usage implicitly and disables execution while runtime is off", async () => {
    render(<App />);
    await connect();
    fireEvent.change(await screen.findByLabelText("给 Agent 的任务"), {
      target: { value: "Do work" },
    });
    expect(
      (screen.getByRole("button", { name: "运行任务" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
    expect(
      screen
        .getAllByRole("button", { name: "读取额度" })
        .every((button) => (button as HTMLButtonElement).disabled),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.some(([path]) => /quotas|\/run$/.test(String(path))),
    ).toBe(false);
  });
});

describe("reviewed memory and messages", () => {
  it("uses compare-and-swap version and preserves the draft after a conflict", async () => {
    fetchMock.mockImplementation(async (path: string) =>
      path === "/api/memories"
        ? response({ error: "Version conflict" }, 409)
        : response(path.includes("/events?") ? { events: [] } : state),
    );
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "共享记忆" }));
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.change(screen.getByLabelText("内容"), {
      target: { value: "Keep this draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存已审阅记忆" }));
    await screen.findByRole("alert");
    const call = fetchMock.mock.calls.find(
      ([path]) => path === "/api/memories",
    ) as unknown as [string, RequestInit];
    expect(JSON.parse(call[1].body as string)).toEqual({
      project_id: "project-a",
      key: "project.stack",
      content: "Keep this draft",
      expected_version: 3,
    });
    expect((screen.getByLabelText("内容") as HTMLTextAreaElement).value).toBe(
      "Keep this draft",
    );
    expect(screen.getByRole("alert").textContent).toContain("操作未应用");
  });
  it("disables dispatch when execution is off", async () => {
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "任务派工" }));
    fireEvent.change(screen.getByLabelText("任务说明"), {
      target: { value: "Review the change" },
    });
    const button = screen.getByRole("button", {
      name: "派发任务",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(
      fetchMock.mock.calls.some(([path]) => path === "/api/messages"),
    ).toBe(false);
  });
  it("dispatches to a selected native session with an idempotency key", async () => {
    fetchMock.mockImplementation(async (path: string) =>
      response(
        path.includes("/events?")
          ? { events: [] }
          : { ...state, runtime: { enabled: true, version: "0.2.0" } },
      ),
    );
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "任务派工" }));
    fireEvent.change(screen.getByLabelText("目标会话"), {
      target: { value: "session-a" },
    });
    fireEvent.change(screen.getByLabelText("任务说明"), {
      target: { value: "Review this change." },
    });
    fireEvent.click(screen.getByRole("button", { name: "派发任务" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([path]) => path === "/api/messages"),
      ).toBe(true),
    );
    const call = fetchMock.mock.calls.find(
      ([path]) => path === "/api/messages",
    ) as unknown as [string, RequestInit];
    expect(JSON.parse(call[1].body as string)).toEqual({
      project_id: "project-a",
      recipient_id: "agent-a",
      recipient_session_id: "session-a",
      body: "Review this change.",
      idempotency_key: expect.any(String),
    });
    expect(
      fetchMock.mock.calls.some(([path]) => String(path).endsWith("/run")),
    ).toBe(false);
  });
  it("renders untrusted memory as literal text, never markup", async () => {
    const hostile = '<img src=x onerror="alert(1)">';
    fetchMock.mockImplementation(async (path: string) =>
      response(
        path.includes("/events?")
          ? { events: [] }
          : {
              ...state,
              memories: [{ ...state.memories[0], content: hostile }],
            },
      ),
    );
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "共享记忆" }));
    expect(screen.getByText(hostile)).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
  });
  it("rejects stale proposals in the UI instead of overwriting reviewed memory", async () => {
    fetchMock.mockImplementation(async (path: string) =>
      response(
        path.includes("/events?")
          ? { events: [] }
          : {
              ...state,
              proposals: [
                {
                  id: "proposal-a",
                  project_id: "project-a",
                  agent_id: "agent-a",
                  key: "project.stack",
                  content: "Old suggestion",
                  expected_version: 2,
                  status: "pending",
                  created_at: "2026-01-01T00:00:00Z",
                },
              ],
            },
      ),
    );
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "共享记忆" }));
    expect(
      (screen.getByRole("button", { name: "批准写入" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: "拒绝提案" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });
});

describe("usage semantics and transport", () => {
  it("labels cached quota as outdated and requires an explicit fetch", async () => {
    fetchMock.mockImplementation(async (path: string) =>
      response(
        path.includes("/events?")
          ? { events: [] }
          : {
              ...state,
              runtime: { enabled: true, version: "0.1.0" },
              quotas: [
                {
                  provider: "codex",
                  status: "stale",
                  source: "AgentMeter",
                  windows: [{ label: "Weekly", remaining_percent: 42 }],
                  fetched_at: "2026-01-01T00:00:00Z",
                },
              ],
            },
      ),
    );
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
    expect(screen.getByText("缓存已过期")).toBeTruthy();
    expect(
      fetchMock.mock.calls.some(([path]) => path === "/api/quotas/refresh"),
    ).toBe(false);
    fireEvent.click(screen.getAllByRole("button", { name: "读取额度" })[0]);
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([path]) => path === "/api/quotas/refresh"),
      ).toBe(true),
    );
    const call = fetchMock.mock.calls.find(
      ([path]) => path === "/api/quotas/refresh",
    ) as unknown as [string, RequestInit];
    expect(JSON.parse(call[1].body as string)).toEqual({ provider: "codex" });
  });
  it("distinguishes unknown quota from an actual zero remaining", () => {
    const { rerender } = render(
      <QuotaWindow
        t={(zh) => zh}
        lang="zh"
        window={{ label: "Weekly", remaining_percent: null }}
      />,
    );
    expect(screen.getByText("未知")).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
    rerender(
      <QuotaWindow
        t={(zh) => zh}
        lang="zh"
        window={{ label: "Weekly", remaining_percent: 0 }}
      />,
    );
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe(
      "0",
    );
    expect(screen.queryByText("未知")).toBeNull();
  });
  it("clamps valid percentages and rejects invalid values", () => {
    expect(remainingPercent(undefined)).toBeNull();
    expect(remainingPercent(Number.NaN)).toBeNull();
    expect(remainingPercent(-5)).toBe(0);
    expect(remainingPercent(102)).toBe(100);
  });
  it("restricts API paths and sends no ambient browser credentials", async () => {
    await expect(
      request("token", "https://external.invalid/api/state"),
    ).rejects.toThrow("Invalid API path");
    expect(fetchMock).not.toHaveBeenCalled();
    await request("token", "/api/state");
    const call = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(call[1].credentials).toBe("omit");
    expect(call[1].cache).toBe("no-store");
    expect(call[1].redirect).toBe("error");
  });
  it("keeps HTTP conflict status available to callers", async () => {
    fetchMock.mockResolvedValue(response({ error: "Conflict" }, 409));
    try {
      await request("token", "/api/memories", {});
      throw new Error("Expected failure");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).status).toBe(409);
    }
  });
});

describe("native session workflow", () => {
  const runningState: DockState = {
    ...state,
    runtime: { enabled: true, version: "0.2.0" },
    sessions: [
      {
        ...state.sessions[0],
        status: "running",
        native_session_id: "native-demo-123",
      },
    ],
    runs: [
      {
        id: "run-queued",
        session_id: "session-a",
        project_id: "project-a",
        agent_id: "agent-a",
        prompt: "A queued task",
        status: "queued",
        origin: "human",
        depth: 0,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ],
  };
  it("continues the selected session by queuing work while a run is active", async () => {
    fetchMock.mockImplementation(async (path: string) =>
      response(path.includes("/events?") ? { events: [] } : runningState),
    );
    render(<App />);
    await connect();
    expect(await screen.findByText("native-demo-123")).toBeTruthy();
    const prompt = screen.getByLabelText(
      "给 Agent 的任务",
    ) as HTMLTextAreaElement;
    expect(prompt.disabled).toBe(false);
    fireEvent.change(prompt, { target: { value: "Continue after this task" } });
    fireEvent.click(screen.getByRole("button", { name: "加入队列" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([path]) => path === "/api/sessions/session-a/run",
        ),
      ).toBe(true),
    );
  });
  it("cancels the exact queued run without cancelling the whole session", async () => {
    fetchMock.mockImplementation(async (path: string) =>
      response(path.includes("/events?") ? { events: [] } : runningState),
    );
    render(<App />);
    await connect();
    fireEvent.click(await screen.findByText("执行记录"));
    fireEvent.click(screen.getByRole("button", { name: /^取消$/ }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([path]) => path === "/api/runs/run-queued/cancel",
        ),
      ).toBe(true),
    );
    expect(
      fetchMock.mock.calls.some(
        ([path]) => path === "/api/sessions/session-a/cancel",
      ),
    ).toBe(false);
  });
  it.each([
    { side: "recipient", delivery: "waiting", reply: undefined },
    { side: "sender", delivery: "queued", reply: undefined },
    { side: "sender", delivery: "running", reply: undefined },
    { side: "sender", delivery: "waiting", reply: undefined },
    { side: "sender", delivery: "completed", reply: "queued" },
    { side: "sender", delivery: "completed", reply: "running" },
  ])(
    "cancels pending session work for $side delivery $delivery / reply $reply without an active session run",
    async ({ side, delivery, reply }) => {
      const waitingState: DockState = {
        ...state,
        runtime: { enabled: true, version: "0.2.0" },
        messages: [
          {
            id: "delivery",
            project_id: "project-a",
            sender_id: "agent-a",
            recipient_id: "agent-a",
            body: "A child task is still pending",
            status: delivery,
            sender_session_id:
              side === "sender" ? "session-a" : "session-other",
            recipient_session_id:
              side === "recipient" ? "session-a" : "session-other",
            reply_run_id: reply ? "reply-pending" : undefined,
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
        runs: reply
          ? [
              {
                ...runningState.runs![0],
                id: "reply-pending",
                session_id: "session-other",
                status: reply,
                origin: "reply",
              },
            ]
          : [],
      };
      fetchMock.mockImplementation(async (path: string) =>
        response(path.includes("/events?") ? { events: [] } : waitingState),
      );
      render(<App />);
      await connect();
      fireEvent.click(
        await screen.findByRole("button", { name: "取消会话任务" }),
      );
      await waitFor(() =>
        expect(
          fetchMock.mock.calls.some(
            ([path]) => path === "/api/sessions/session-a/cancel",
          ),
        ).toBe(true),
      );
    },
  );
  it("distinguishes a waiting delegation from a completed delivery", async () => {
    fetchMock.mockImplementation(async (path: string) =>
      response(
        path.includes("/events?")
          ? { events: [] }
          : {
              ...state,
              messages: [
                {
                  id: "delivery",
                  project_id: "project-a",
                  sender_id: "human",
                  recipient_id: "agent-a",
                  body: "Nested review",
                  status: "waiting",
                  recipient_session_id: "session-a",
                  run_id: "run-finished",
                  result: "Delegated the next step to another agent",
                  created_at: "2026-01-01T00:00:00Z",
                },
              ],
              runs: [
                {
                  ...runningState.runs![0],
                  id: "run-finished",
                  status: "completed",
                },
              ],
            },
      ),
    );
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "任务派工" }));
    expect(screen.getByText("等待协作结果")).toBeTruthy();
    expect(screen.queryByText("已回传")).toBeNull();
    expect(screen.getByText("当前进展")).toBeTruthy();
    expect(screen.queryByText("执行结果")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "取消任务" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([path]) => path === "/api/runs/run-finished/cancel",
        ),
      ).toBe(true),
    );
  });
});

describe("offline demonstration", () => {
  it("uses only fictional fixtures across pages and language changes with no network or storage writes", async () => {
    window.history.replaceState({}, "", "/?demo=1");
    const storage = vi.spyOn(Storage.prototype, "setItem");
    render(<App />);
    await screen.findByRole("heading", { name: "协作工作台" });
    expect(screen.getByText(/演示模式/)).toBeTruthy();
    expect(screen.getByText("demo-native-codex-01")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "运行任务" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "任务派工" }));
    expect(screen.getByText(/目标会话: 审阅搜索变更/)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "派发任务" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "共享记忆" }));
    expect(
      (screen.getByRole("button", { name: "批准写入" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
    expect(
      screen
        .getAllByRole("button", { name: "读取额度" })
        .every((b) => (b as HTMLButtonElement).disabled),
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    await screen.findAllByText("5-hour window");
    expect(document.documentElement.lang).toBe("en");
    expect(screen.queryByText("每周额度")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(storage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Exit demo" }));
    expect(screen.getByLabelText("Access token")).toBeTruthy();
  });
});

describe("streamed conversation rendering", () => {
  it("merges partial text without mixing runs and replaces only the completed run’s preview", () => {
    const event = (id: string, kind: string, text: string, run_id: string) => ({
      id,
      kind,
      payload: { text, run_id },
      seq: Number(id),
      project_id: "p",
      session_id: "s",
      created_at: "2026-01-01T00:00:00Z",
    });
    const partials = [
      event("1", "agent_message_chunk", "Hello ", "r1"),
      event("2", "agent_message_chunk", "world", "r1"),
      event("3", "agent_message_chunk", "Second run", "r2"),
    ];
    const merged = conversationEvents(partials);
    expect(merged.map((e) => eventText(e.payload))).toEqual([
      "Hello world",
      "Second run",
    ]);
    expect(partials).toHaveLength(3);
    const completed = conversationEvents([
      ...partials,
      event("4", "assistant_message", "Hello world!", "r1"),
    ]);
    expect(completed.map((e) => eventText(e.payload))).toEqual([
      "Second run",
      "Hello world!",
    ]);
  });
});
