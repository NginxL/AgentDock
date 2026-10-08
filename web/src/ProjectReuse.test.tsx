import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import App from "./App";
import type { DockState } from "./types";
import { agentTPS, type Metrics, type Meter } from "./metrics";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  delete window.__AGENTDOCK_DESKTOP_TOKEN__;
  window.history.replaceState(null, "", "/");
});

it("keeps project TPS separate from other projects and everyday usage", () => {
  const meter = (n: number): Meter => ({
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    total_tokens: 0,
    sessions: 1,
    active_sessions: 1,
    current_tps: n,
    average_tps: n,
    points: Array(60).fill(n),
    updated_at: 1,
  });
  const metrics = {
    total: meter(100),
    agents: { base: meter(10), cr: meter(20), coding: meter(70) },
  } as unknown as Metrics;
  expect(agentTPS(metrics, ["cr"])?.current_tps).toBe(20);
  expect(agentTPS(metrics, ["coding"])?.active_sessions).toBe(1);
  expect(agentTPS(metrics, ["cr", "coding"])?.points[0]).toBe(90);
  expect(agentTPS(metrics, ["missing"])).toBeUndefined();
  metrics.agents.cr.current_tps = null;
  expect(agentTPS(metrics, ["cr"])?.current_tps).toBeNull();
});

async function setup(hash = "#/conversations") {
  window.history.replaceState(null, "", "/" + hash);
  const state: DockState = {
    runtime: { enabled: true, version: "0.3.0" },
    projects: ["A", "B"].map((id) => ({
      id,
      name: `Project ${id}`,
      path: `/fixture/${id}`,
    })),
    agents: [
      {
        id: "base",
        name: "My Codex",
        project_id: null,
        provider: "codex",
        role: "General",
      },
      {
        id: "cr",
        name: "cr",
        project_id: "A",
        source_agent_id: "base",
        provider: "codex",
        role: "Review",
      },
      {
        id: "coding",
        name: "coding",
        project_id: "B",
        source_agent_id: "base",
        provider: "codex",
        role: "Implement",
      },
    ],
    sessions: [
      {
        id: "daily",
        title: "Everyday question",
        agent_id: "base",
        project_id: null,
      },
      {
        id: "a-chat",
        title: "Review request",
        agent_id: "cr",
        project_id: "A",
      },
      {
        id: "b-chat",
        title: "Feature request",
        agent_id: "coding",
        project_id: "B",
      },
    ].map((s, i) => ({
      ...s,
      status: "idle",
      created_at: "2026-09-29T10:00:00Z",
      updated_at: `2026-09-29T1${i}:00:00Z`,
    })),
    runs: [],
    messages: [],
    events: [],
    approvals: [],
    memories: [],
    proposals: [],
    quotas: [],
    subscriptions: [],
  };
  const writes: [string, any][] = [];
  const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    let result: any = { events: [], models: [] };
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      writes.push([path, body]);
      if (path.endsWith("/agents")) {
        const project = path.split("/")[3];
        result = {
          ...state.agents[0],
          ...body,
          id: `member-${project}`,
          project_id: project,
        };
        state.agents = [...state.agents, result];
      } else if (path === "/api/sessions") {
        const agent = state.agents.find((a) => a.id === body.agent_id)!;
        result = {
          ...state.sessions[0],
          ...body,
          id: "new-chat",
          project_id: agent.project_id,
        };
        state.sessions = [...state.sessions, result];
      }
    }
    if (path === "/api/state") result = { ...state };
    return { ok: true, json: async () => result };
  });
  vi.stubGlobal("fetch", fetchMock);
  window.__AGENTDOCK_DESKTOP_TOKEN__ = "project-reuse-fixture";
  render(<App />);
  await screen.findByRole("navigation", { name: "主导航" });
  return { state, writes, fetchMock };
}

it("reuses one configured agent with separate names and roles in two projects", async () => {
  const { state, writes } = await setup("#/projects?project=A&view=agents");
  for (const [project, name, role] of [
    ["A", "reviewer", "Review A"],
    ["B", "builder", "Build B"],
  ]) {
    if (project === "B") {
      fireEvent.click(screen.getByRole("button", { name: "返回 Agent 列表" }));
      fireEvent.change(screen.getByLabelText("切换项目"), {
        target: { value: project },
      });
    }
    fireEvent.click(screen.getByRole("button", { name: "添加 Agent" }));
    fireEvent.change(screen.getByLabelText("使用 Agent"), {
      target: { value: "base" },
    });
    fireEvent.change(screen.getByLabelText("项目内名称"), {
      target: { value: name },
    });
    fireEvent.change(screen.getByLabelText("项目职责（可选）"), {
      target: { value: role },
    });
    fireEvent.click(screen.getByRole("button", { name: "添加到项目" }));
    await screen.findByRole("heading", { name, level: 1 });
    expect(writes.at(-1)).toEqual([
      `/api/projects/${project}/agents`,
      { source_agent_id: "base", name, role },
    ]);
  }
  expect(state.agents[0].name).toBe("My Codex");
  expect(state.sessions.filter((s) => !s.project_id)).toHaveLength(1);
});

it("toggles the project picker closed and keeps the close button", async () => {
  await setup("#/projects?project=A&view=agents");
  const add = screen.getByRole("button", { name: "添加 Agent" });
  fireEvent.click(add);
  expect(screen.getByLabelText("使用 Agent")).toBeTruthy();
  fireEvent.click(add);
  expect(screen.queryByLabelText("使用 Agent")).toBeNull();
  fireEvent.click(add);
  fireEvent.click(screen.getByRole("button", { name: "取消添加 Agent" }));
  expect(screen.queryByLabelText("使用 Agent")).toBeNull();
});

it("shows project and everyday conversations, filters them, and opens the right agent scope", async () => {
  await setup();
  const items = screen.getAllByRole("button", { name: /question|request/ });
  expect(items.map((b) => b.textContent?.split("待命")[0])).toEqual(
    expect.arrayContaining([
      expect.stringContaining("Everyday question"),
      expect.stringContaining("Review request"),
      expect.stringContaining("Feature request"),
    ]),
  );
  fireEvent.change(screen.getByLabelText("对话范围"), {
    target: { value: "A" },
  });
  expect(
    screen.queryByRole("button", { name: /^Everyday question/ }),
  ).toBeNull();
  expect(screen.queryByRole("button", { name: /^Feature request/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /^Review request/ }));
  expect(window.location.hash).toBe("#/conversations?session=a-chat");
  expect(screen.getByRole("heading", { name: "Review request" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "会话" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "打开 Agent" }));
  expect(window.location.hash).toBe("#/agents/cr?project=A");
});

it("switches drafts without mixing recipients and sends everyday messages only to the everyday session", async () => {
  const { writes } = await setup("#/conversations?session=a-chat");
  fireEvent.change(screen.getByLabelText("给 Agent 的任务"), {
    target: { value: "Review draft" },
  });
  fireEvent.click(screen.getByRole("button", { name: /^Everyday question/ }));
  expect(
    (screen.getByLabelText("给 Agent 的任务") as HTMLTextAreaElement).value,
  ).toBe("");
  fireEvent.change(screen.getByLabelText("给 Agent 的任务"), {
    target: { value: "Daily draft" },
  });
  fireEvent.click(screen.getByRole("button", { name: /^Review request/ }));
  expect(
    (screen.getByLabelText("给 Agent 的任务") as HTMLTextAreaElement).value,
  ).toBe("Review draft");
  fireEvent.click(screen.getByRole("button", { name: /^Everyday question/ }));
  fireEvent.keyDown(screen.getByLabelText("给 Agent 的任务"), {
    key: "Enter",
    code: "Enter",
  });
  await waitFor(() =>
    expect(writes).toContainEqual([
      "/api/sessions/daily/run",
      { prompt: "Daily draft" },
    ]),
  );
  expect(writes.some(([path]) => path.includes("a-chat"))).toBe(false);
});

it("preserves an open conversation and its unsent draft while filtering and grouping the sidebar", async () => {
  await setup("#/conversations?session=a-chat");
  fireEvent.change(screen.getByLabelText("给 Agent 的任务"), {
    target: { value: "Keep this review draft" },
  });
  fireEvent.change(screen.getByLabelText("对话范围"), {
    target: { value: "daily" },
  });
  fireEvent.click(screen.getByRole("button", { name: "按 Agent 分组" }));
  fireEvent.click(
    screen.getByRole("button", { name: "仅显示最近 24 小时活跃的对话" }),
  );
  expect(
    (screen.getByLabelText("给 Agent 的任务") as HTMLTextAreaElement).value,
  ).toBe("Keep this review draft");
  expect(screen.getByRole("heading", { name: "Review request" })).toBeTruthy();
  expect(window.location.hash).toBe("#/conversations?session=a-chat");
});

it("creates a daily conversation without project membership and restores selection through browser history", async () => {
  const { state, writes } = await setup();
  fireEvent.click(screen.getByRole("button", { name: "新建对话" }));
  const form = screen
    .getByRole("button", { name: "创建对话" })
    .closest("form")!;
  expect(within(form).queryByRole("option", { name: "cr" })).toBeNull();
  fireEvent.change(within(form).getByLabelText("Agent"), {
    target: { value: "base" },
  });
  fireEvent.click(screen.getByRole("button", { name: "创建对话" }));
  await screen.findByRole("heading", { name: "新对话" });
  expect(writes[0]).toEqual([
    "/api/sessions",
    { agent_id: "base", title: "新对话" },
  ]);
  expect(state.sessions.at(-1)?.project_id).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /^Everyday question/ }));
  act(() => window.history.back());
  await screen.findByRole("heading", { name: "新对话" });
  act(() => window.history.forward());
  await screen.findByRole("heading", { name: "Everyday question" });
  fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
  expect(screen.getByLabelText("Conversation scope")).toBeTruthy();
});

it("does not fall back to another conversation when a bookmarked session is missing", async () => {
  await setup("#/conversations?session=missing");
  expect(screen.getByText("选择或新建对话")).toBeTruthy();
  expect(screen.queryByLabelText("给 Agent 的任务")).toBeNull();
});
