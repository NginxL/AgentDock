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
import { StrictMode } from "react";

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
  delete window.__AGENTDOCK_DESKTOP_TOKEN__;
  delete window.__AGENTDOCK_DESKTOP_LANGUAGE__;
  delete window.webkit;
  window.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});

describe("desktop connection and built-in usage", () => {
  it("restores the desktop language and keeps the native menu in sync", async () => {
    const postMessage = vi.fn();
    window.__AGENTDOCK_DESKTOP_TOKEN__ = "native-fixture-token";
    window.__AGENTDOCK_DESKTOP_LANGUAGE__ = "en";
    window.webkit = { messageHandlers: { agentdockLanguage: { postMessage } } };
    render(<App />);
    await screen.findByRole("heading", { name: "Workspace" });
    expect(postMessage).toHaveBeenCalledWith("en");
    fireEvent.click(screen.getByRole("button", { name: "切换为中文" }));
    expect(postMessage).toHaveBeenLastCalledWith("zh");
    expect(screen.getByRole("heading", { name: "协作工作台" })).toBeTruthy();
  });

  it("localizes expired cache guidance without hiding the last known quota", async () => {
    fetchMock.mockImplementation(async () =>
      response({
        ...state,
        quotas: [
          {
            provider: "codex",
            source: "AgentDock",
            status: "stale",
            error_code: "outdated_cache",
            error: "Cached quota is outdated. Refresh to read current limits.",
            windows: [{ label: "Weekly", remaining_percent: 95 }],
          },
        ],
      }),
    );
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
    expect(screen.getByText("待更新")).toBeTruthy();
    expect(
      screen.queryByText(
        "Cached quota is outdated. Refresh to read current limits.",
      ),
    ).toBeNull();
    expect(screen.getByText(/95%/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(screen.getByText("Update pending")).toBeTruthy();
  });

  it("connects from the native in-memory credential in StrictMode without persisting it", async () => {
    window.__AGENTDOCK_DESKTOP_TOKEN__ = "native-fixture-token";
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
    await screen.findByRole("heading", { name: "协作工作台" });
    expect(window.__AGENTDOCK_DESKTOP_TOKEN__).toBeUndefined();
    expect(window.location.href).not.toContain("native-fixture-token");
    expect(JSON.stringify(localStorage)).not.toContain("native-fixture-token");
    expect(document.body.textContent).not.toContain("native-fixture-token");
    expect(
      fetchMock.mock.calls.some(
        ([, options]) =>
          options?.headers?.Authorization === "Bearer native-fixture-token",
      ),
    ).toBe(true);
  });

  it("never exposes Keychain authorization and labels the local source time", async () => {
    fetchMock.mockImplementation(async () =>
      response({
        ...state,
        agents: [{ ...state.agents[0], provider: "claude" }],
        quotas: [
          {
            provider: "claude",
            source: "claude-desktop-snapshot",
            windows: [],
            status: "stale",
            fetched_at: "2026-01-01T00:00:00Z",
          },
        ],
      }),
    );
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
    expect(screen.queryByRole("button", { name: /连接 Claude/ })).toBeNull();
    expect(screen.getByText(/Claude 本地快照/)).toBeTruthy();
    expect(
      fetchMock.mock.calls.every(([path]) => path !== "/api/quotas/authorize"),
    ).toBe(true);
  });
});
async function connect() {
  fireEvent.change(screen.getByLabelText("访问令牌"), {
    target: { value: "example-admin-token-not-a-real-secret" },
  });
  fireEvent.click(screen.getByRole("button", { name: "进入工作台" }));
  await screen.findByRole("heading", { name: "协作工作台" });
  if (screen.queryByRole("option", { name: "Demo project" }))
    fireEvent.change(screen.getByLabelText("当前项目"), {
      target: { value: "project-a" },
    });
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
        environment_id: "local",
        project_id: "project-a",
        workspace: null,
        model: null,
        effort: null,
        permission_mode: "ask",
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
    fireEvent.click(screen.getByRole("button", { name: /^Review agent/ }));
    fireEvent.click(screen.getByRole("button", { name: "设置 Review agent" }));
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
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }));
    await screen.findByRole("button", { name: "设置 Custom helper" });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "保存设置" })).toBeNull(),
    );
    expect(current.agents[0].role).toBe("");
    expect(current.sessions[0].native_session_id).toBe(
      "existing-native-session",
    );
    expect(screen.getByRole("heading", { name: "First task" })).toBeTruthy();
    const call = fetchMock.mock.calls.find(
      ([path]) => path === "/api/agents/agent-a",
    )!;
    expect(JSON.parse(call[1].body)).toEqual({
      name: "Custom helper",
      role: "",
      environment_id: "local",
      model: null,
      effort: null,
      permission_mode: "ask",
    });
    expect(current.agents[0].provider).toBe("codex");
    fireEvent.click(screen.getByRole("button", { name: "设置 Custom helper" }));
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
    fireEvent.click(screen.getByRole("button", { name: /^Review agent/ }));
    fireEvent.click(screen.getByRole("button", { name: "设置 Review agent" }));
    fireEvent.change(screen.getByLabelText("角色说明（可选）"), {
      target: { value: "My unsaved role" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }));
    await screen.findByText("Temporary save failure");
    expect(
      (screen.getByLabelText("角色说明（可选）") as HTMLTextAreaElement).value,
    ).toBe("My unsaved role");
    expect(state.agents[0].role).toBe("Review changes");
    fireEvent.click(screen.getByRole("button", { name: "取消编辑 Agent" }));
    fireEvent.click(screen.getByRole("button", { name: "返回 Agent 列表" }));
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
    fireEvent.click(screen.getByRole("button", { name: /^Review agent/ }));
    fireEvent.click(screen.getByRole("button", { name: "设置 Review agent" }));
    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(
      screen.getByRole("heading", { name: "Edit agent · Review agent" }),
    ).toBeTruthy();
    expect(
      (screen.getByLabelText("Role (optional)") as HTMLTextAreaElement).value,
    ).toBe("Review changes");
    expect(screen.getByRole("button", { name: "Save settings" })).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: /^Agent A/ }));
    fireEvent.click(screen.getByRole("button", { name: "设置 Agent A" }));
    expect(
      (screen.getByRole("button", { name: "保存设置" }) as HTMLButtonElement)
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
    await screen.findByRole("heading", { name: "New helper", level: 1 });
    expect(window.location.hash).toBe("#/agents/agent-new?project=project-a");
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
    fireEvent.click(screen.getByRole("button", { name: /^Review agent/ }));
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
    fireEvent.click(screen.getByRole("button", { name: "退出工作台" }));
    expect(screen.getByLabelText("访问令牌").getAttribute("value")).toBe("");
    expect(screen.queryByText("Demo project")).toBeNull();
  });
  it("does not fetch usage implicitly and disables execution while runtime is off", async () => {
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: /^Review agent/ }));
    fireEvent.change(await screen.findByLabelText("给 Agent 的任务"), {
      target: { value: "Do work" },
    });
    expect(
      (screen.getByRole("button", { name: "运行任务" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
    expect(screen.queryByRole("button", { name: "读取额度" })).toBeNull();
    expect(screen.queryByText("执行未启用，自动刷新已暂停。")).toBeNull();
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
    if ((screen.getByLabelText("当前项目") as HTMLSelectElement).value === "")
      fireEvent.change(screen.getByLabelText("当前项目"), {
        target: {
          value: (screen.getByLabelText("当前项目") as HTMLSelectElement)
            .options[1]?.value,
        },
      });
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
    if ((screen.getByLabelText("当前项目") as HTMLSelectElement).value === "")
      fireEvent.change(screen.getByLabelText("当前项目"), {
        target: {
          value: (screen.getByLabelText("当前项目") as HTMLSelectElement)
            .options[1]?.value,
        },
      });
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
    if ((screen.getByLabelText("当前项目") as HTMLSelectElement).value === "")
      fireEvent.change(screen.getByLabelText("当前项目"), {
        target: {
          value: (screen.getByLabelText("当前项目") as HTMLSelectElement)
            .options[1]?.value,
        },
      });
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
  it("hides unconfigured providers and unrelated historical usage, and performs no quota probes", async () => {
    fetchMock.mockImplementation(async (path: string) =>
      response(
        path === "/api/metrics"
          ? {
              providers: { codex: { total_tokens: 99000000 } },
              total: { total_tokens: 99000000, sessions: 172 },
              agents: {},
            }
          : {
              ...state,
              projects: [],
              agents: [],
              sessions: [],
              runtime: { enabled: true, version: "0.3.0" },
              quotas: [
                {
                  provider: "claude",
                  windows: [],
                  status: "available",
                  source: "local",
                },
              ],
            },
      ),
    );
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
    expect(screen.getByText("暂无 Agent")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Codex" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Claude" })).toBeNull();
    expect(
      fetchMock.mock.calls.some(([p]) => p === "/api/quotas/refresh"),
    ).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Token 统计" }));
    expect(screen.getByText("暂无 Agent")).toBeTruthy();
    expect(screen.queryByText("99M")).toBeNull();
  });
  it("only refreshes the provider of a configured agent", async () => {
    fetchMock.mockImplementation(
      async (path: string, options?: RequestInit) => {
        if (path === "/api/quotas/refresh")
          return response({
            provider: JSON.parse(String(options?.body)).provider,
            windows: [],
            status: "unknown",
          });
        return response({
          ...state,
          runtime: { enabled: true, version: "0.3.0" },
        });
      },
    );
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([p]) => p === "/api/quotas/refresh"),
      ).toHaveLength(1),
    );
    const refresh = fetchMock.mock.calls.find(
      ([p]) => p === "/api/quotas/refresh",
    )!;
    expect(JSON.parse(String(refresh[1].body))).toEqual({ provider: "codex" });
    expect(screen.queryByRole("heading", { name: "Claude" })).toBeNull();
  });

  it("refreshes both quotas on every usage navigation without exposing refresh or connection buttons", async () => {
    fetchMock.mockImplementation(
      async (path: string, options?: RequestInit) => {
        if (path === "/api/quotas/refresh") {
          const { provider } = JSON.parse(String(options?.body));
          return response({
            provider,
            source: "AgentDock",
            status: "available",
            windows: [
              {
                label: "Weekly",
                remaining_percent: provider === "codex" ? 42 : 71,
              },
            ],
          });
        }
        return response({
          ...state,
          agents: [
            ...state.agents,
            {
              ...state.agents[0],
              id: "agent-b",
              provider: "claude",
              name: "Writer",
            },
          ],
          runtime: { ...state.runtime, enabled: true },
        });
      },
    );
    render(<App />);
    await connect();
    expect(
      fetchMock.mock.calls.some(([path]) => path === "/api/quotas/refresh"),
    ).toBe(false);
    const openUsage = () =>
      fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
    const calls = () =>
      fetchMock.mock.calls.filter(([path]) => path === "/api/quotas/refresh");
    openUsage();
    expect(await screen.findByText(/42%/)).toBeTruthy();
    expect(await screen.findByText(/71%/)).toBeTruthy();
    await waitFor(() => expect(screen.queryByText("更新中")).toBeNull());
    expect(
      calls().map(([, options]) => JSON.parse(String(options.body)).provider),
    ).toEqual(["codex", "claude"]);
    expect(screen.queryByRole("button", { name: "读取额度" })).toBeNull();
    expect(screen.queryByRole("button", { name: /连接 Claude/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "刷新工作台状态" })).toBeNull();
    openUsage();
    await waitFor(() => expect(calls()).toHaveLength(4));
    await waitFor(() => expect(screen.queryByText("更新中")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "协作工作台" }));
    openUsage();
    await waitFor(() => expect(calls()).toHaveLength(6));
    await waitFor(() => expect(screen.queryByText("更新中")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(screen.queryByText("Automatic refresh is on")).toBeNull();
    expect(calls()).toHaveLength(6);
  });

  it("coalesces repeated clicks, keeps unrelated controls enabled, and ignores late results after disconnect", async () => {
    const pending: ((value: Response) => void)[] = [];
    const signals: AbortSignal[] = [];
    fetchMock.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/quotas/refresh") {
        signals.push(options?.signal as AbortSignal);
        return new Promise<Response>((resolve) => pending.push(resolve));
      }
      return Promise.resolve(
        response({
          ...state,
          agents: [
            ...state.agents,
            {
              ...state.agents[0],
              id: "agent-b",
              provider: "claude",
              name: "Writer",
            },
          ],
          runtime: { ...state.runtime, enabled: true },
        }),
      );
    });
    render(<App />);
    await connect();
    for (let i = 0; i < 3; i++)
      fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
    expect(pending).toHaveLength(2);
    expect(screen.getAllByText("更新中")).toHaveLength(2);
    expect(
      (screen.getAllByRole("button", { name: "编辑" })[0] as HTMLButtonElement)
        .disabled,
    ).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "退出工作台" }));
    expect(signals.every((signal) => signal.aborted)).toBe(true);
    await act(async () => {
      pending.forEach((resolve, i) =>
        resolve(
          response({
            provider: i ? "claude" : "codex",
            windows: [{ label: "Weekly", remaining_percent: 82 }],
            status: "available",
            source: "AgentDock",
          }),
        ),
      );
    });
    expect(
      screen.getByRole("heading", { name: "连接本地工作台" }),
    ).toBeTruthy();
    expect(screen.queryByText(/82%/)).toBeNull();
  });

  it("updates a successful provider even if the other request fails and preserves its previous data", async () => {
    fetchMock.mockImplementation(
      async (path: string, options?: RequestInit) => {
        if (path === "/api/quotas/refresh") {
          const { provider } = JSON.parse(String(options?.body));
          if (provider === "codex") throw new Error("offline");
          return response({
            provider,
            source: "AgentDock",
            status: "available",
            windows: [{ label: "Weekly", remaining_percent: 55 }],
          });
        }
        return response({
          ...state,
          agents: [
            ...state.agents,
            {
              ...state.agents[0],
              id: "agent-b",
              provider: "claude",
              name: "Writer",
            },
          ],
          runtime: { ...state.runtime, enabled: true },
          quotas: [
            {
              provider: "codex",
              source: "AgentDock",
              status: "stale",
              windows: [{ label: "Weekly", remaining_percent: 42 }],
            },
          ],
        });
      },
    );
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
    expect(await screen.findByText(/55%/)).toBeTruthy();
    expect(screen.getByText(/42%/)).toBeTruthy();
    expect(
      await screen.findByText("额度更新失败，稍后自动重试。"),
    ).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: /^Review agent/ }));
    expect(await screen.findByText("任务排队中")).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: /^Review agent/ }));
    expect(await screen.findByText("任务排队中")).toBeTruthy();
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
      fireEvent.click(screen.getByRole("button", { name: /^Review agent/ }));
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
    fireEvent.click(screen.getByRole("button", { name: /^Review agent/ }));
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
    fireEvent.click(screen.getByRole("button", { name: /^Agent A/ }));
    expect(
      screen.getByRole("heading", { name: demoState("zh").sessions[0].title }),
    ).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "运行任务" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.change(screen.getByLabelText("当前项目"), {
      target: {
        value: (screen.getByLabelText("当前项目") as HTMLSelectElement)
          .options[1].value,
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "任务派工" }));
    expect(screen.getByText(/目标会话: 审阅搜索变更/)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "派发任务" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    if ((screen.getByLabelText("当前项目") as HTMLSelectElement).value === "")
      fireEvent.change(screen.getByLabelText("当前项目"), {
        target: {
          value: (screen.getByLabelText("当前项目") as HTMLSelectElement)
            .options[1]?.value,
        },
      });
    fireEvent.click(screen.getByRole("button", { name: "共享记忆" }));
    expect(
      (screen.getByRole("button", { name: "批准写入" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
    expect(screen.queryByRole("button", { name: "读取额度" })).toBeNull();
    expect(screen.queryByText("演示数据，不会读取实际额度。")).toBeNull();
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

describe("independent agents and usage", () => {
  it("creates an agent with native model settings without a project", async () => {
    const empty = {
      ...state,
      projects: [],
      agents: [],
      sessions: [],
      runtime: { enabled: true, version: "0.3.0" },
    };
    fetchMock.mockImplementation(async (path: string) =>
      response(
        path.startsWith("/api/models/")
          ? {
              models: [
                {
                  id: "fixture-model",
                  name: "Fixture",
                  efforts: ["low", "high"],
                },
              ],
            }
          : path === "/api/agents"
            ? { id: "new-agent" }
            : empty,
      ),
    );
    render(<App />);
    await connect();
    expect(screen.queryByRole("button", { name: "创建第一个项目" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "添加 Agent" }));
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "Personal assistant" },
    });
    await screen.findByRole("option", { name: "Fixture" });
    fireEvent.change(screen.getByLabelText("模型"), {
      target: { value: "fixture-model" },
    });
    fireEvent.change(screen.getByLabelText("思考强度"), {
      target: { value: "high" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建 Agent" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p]) => p === "/api/agents")).toBe(
        true,
      ),
    );
    const call = fetchMock.mock.calls.find(([p]) => p === "/api/agents")!;
    expect(JSON.parse(call[1].body)).toMatchObject({
      project_id: null,
      workspace: null,
      model: "fixture-model",
      effort: "high",
      provider: "codex",
    });
  });
  it("opens bilingual token statistics without a project or network in demo", async () => {
    window.history.replaceState({}, "", "/?demo=1");
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Token 统计" }));
    expect(screen.getByRole("heading", { name: "Token 统计" })).toBeTruthy();
    expect(screen.getByText("958K").getAttribute("title")).toBe("958,000");
    expect(screen.getByRole("heading", { name: "每日活跃" })).toBeTruthy();
    expect(screen.queryByText(/未关联 Agent 的历史会话/)).toBeNull();
    expect(screen.queryByText(/原生会话保留各自上下文/)).toBeNull();
    expect(screen.queryByText(/K = 千/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(
      screen.getByRole("heading", { name: "Token statistics" }),
    ).toBeTruthy();
    expect(screen.queryByText("累计 Token")).toBeNull();
    expect(
      screen.getByRole("heading", { name: "DAILY ACTIVITY" }),
    ).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
