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
import { ApiError, remainingPercent, request } from "./api";
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
  vi.unstubAllGlobals();
});
async function connect() {
  fireEvent.change(screen.getByLabelText("访问令牌"), {
    target: { value: "example-admin-token-not-a-real-secret" },
  });
  fireEvent.click(screen.getByRole("button", { name: "进入工作台" }));
  await screen.findByRole("heading", { name: "协作，从这里开始" });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

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
          .getByRole("button", { name: /New helper/ })
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
  it("sends a human mailbox message without executing the recipient", async () => {
    render(<App />);
    await connect();
    fireEvent.click(screen.getByRole("button", { name: "协作消息" }));
    fireEvent.change(screen.getByLabelText("消息内容"), {
      target: { value: "Please review when requested." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送到收件箱" }));
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
      sender_id: "human",
      recipient_id: "agent-a",
      body: "Please review when requested.",
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
