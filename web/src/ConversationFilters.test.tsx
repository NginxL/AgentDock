import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import Conversations from "./views/Conversations";
import type { DockState, Session } from "./types";

vi.mock("./views/Workspace", () => ({
  default: () => <div>Conversation content</div>,
}));
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});
const at = Date.parse("2026-09-30T12:00:00Z");
const recentLabel = "仅显示最近 24 小时活跃的对话";
const t = (zh: string) => zh;

function fixture(): DockState {
  const sessions = [
    ["daily-new", "base", null, "2026-09-30T19:00:00+08:00"],
    ["a-new", "a", "A", "2026-09-30T10:00:00Z"],
    ["daily-old", "base", null, "2026-09-28T12:00:00Z"],
    ["b-edge", "b", "B", "2026-09-29T12:00:00Z"],
    ["a-edge-old", "a", "A", "2026-09-29T11:59:59Z"],
  ].map(([id, agent_id, project_id, updated_at]) => ({
    id,
    title: id,
    agent_id,
    project_id,
    updated_at,
    created_at: updated_at,
    status: "completed",
  })) as Session[];
  return {
    runtime: { enabled: false, version: "0.3.0" },
    agents: [
      {
        id: "base",
        name: "Codex",
        project_id: null,
        provider: "codex",
        role: "",
      },
      {
        id: "a",
        name: "Codex",
        project_id: "A",
        source_agent_id: "base",
        provider: "codex",
        role: "",
      },
      {
        id: "b",
        name: "Codex",
        project_id: "B",
        source_agent_id: "base",
        provider: "codex",
        role: "",
      },
    ],
    projects: ["A", "B"].map((id) => ({
      id,
      name: `Project ${id}`,
      path: "/fixture",
    })),
    sessions,
    runs: [],
    messages: [],
    events: [],
    approvals: [],
    memories: [],
    proposals: [],
    quotas: [],
    subscriptions: [],
  };
}
function setup(state = fixture()) {
  vi.useFakeTimers();
  vi.setSystemTime(at);
  const select = vi.fn();
  const props = {
    state,
    sessionID: "",
    onSelect: select,
    onAgent: vi.fn(),
    token: "",
    demo: true,
    busy: false,
    mutate: vi.fn(),
    lang: "zh" as const,
    t,
  };
  const view = render(<Conversations {...props} />);
  return { ...view, props, select };
}
function listTitles() {
  return Array.from(
    document.querySelectorAll(".conversation-index-item strong"),
    (node) => node.textContent,
  );
}
function openAgents() {
  fireEvent.click(screen.getByRole("button", { name: "按 Agent 筛选对话" }));
  return screen.getByRole("group", { name: "按 Agent 筛选对话" });
}

it("filters by agent identity across identical names, with multi-select and reset", () => {
  setup();
  const filter = openAgents();
  fireEvent.click(
    within(filter).getByRole("checkbox", { name: "Codex Project A" }),
  );
  expect(listTitles()).toEqual(["a-new", "a-edge-old"]);
  fireEvent.click(
    within(filter).getByRole("checkbox", { name: "Codex 日常对话" }),
  );
  expect(listTitles()).toEqual([
    "daily-new",
    "a-new",
    "a-edge-old",
    "daily-old",
  ]);
  fireEvent.click(within(filter).getByRole("button", { name: "全部 Agent" }));
  expect(listTitles()).toHaveLength(5);
});

it("supports second-click, close, Escape and outside dismissal of the agent filter", () => {
  setup();
  const trigger = screen.getByRole("button", { name: "按 Agent 筛选对话" });
  openAgents();
  expect(document.activeElement).toBe(
    screen.getByRole("button", { name: "全部 Agent" }),
  );
  fireEvent.click(trigger);
  expect(screen.queryByRole("checkbox")).toBeNull();
  openAgents();
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  expect(document.activeElement).toBe(trigger);
  openAgents();
  fireEvent.click(screen.getByRole("button", { name: "关闭 Agent 筛选" }));
  expect(document.activeElement).toBe(trigger);
  openAgents();
  fireEvent.pointerDown(document.body);
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
});

it("uses a rolling 24-hour activity window, includes its boundary and orders time zones correctly", () => {
  setup();
  expect(listTitles()[0]).toBe("daily-new");
  const recent = screen.getByRole("button", { name: recentLabel });
  fireEvent.click(recent);
  expect(recent.getAttribute("aria-pressed")).toBe("true");
  expect(listTitles()).toEqual(["daily-new", "a-new", "b-edge"]);
  act(() => vi.advanceTimersByTime(30_000));
  expect(listTitles()).toEqual(["daily-new", "a-new"]);
  fireEvent.click(recent);
  expect(listTitles()).toHaveLength(5);
});

it("combines project scope, agent, recency and search without changing the selected conversation", () => {
  const { select } = setup();
  fireEvent.change(screen.getByLabelText("对话范围"), {
    target: { value: "A" },
  });
  const filter = openAgents();
  expect(within(filter).getAllByRole("checkbox")).toHaveLength(1);
  fireEvent.click(
    within(filter).getByRole("checkbox", { name: "Codex Project A" }),
  );
  fireEvent.click(screen.getByRole("button", { name: recentLabel }));
  fireEvent.change(screen.getByLabelText("搜索对话"), {
    target: { value: "edge" },
  });
  expect(listTitles()).toEqual([]);
  expect(screen.getByText("没有符合条件的对话")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("搜索对话"), {
    target: { value: "new" },
  });
  expect(listTitles()).toEqual(["a-new"]);
  expect(select).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("对话范围"), {
    target: { value: "daily" },
  });
  expect(listTitles()).toEqual(["daily-new"]);
});

it("groups by distinct agent IDs and preserves recency order within and between groups", () => {
  setup();
  const group = screen.getByRole("button", { name: "按 Agent 分组" });
  fireEvent.click(group);
  expect(group.getAttribute("aria-pressed")).toBe("true");
  const groups = screen.getAllByRole("group", { name: /^Codex ·/ });
  expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual([
    "Codex · 日常对话",
    "Codex · Project A",
    "Codex · Project B",
  ]);
  expect(
    within(groups[0]).getAllByRole("button", { name: /^daily-/ }),
  ).toHaveLength(2);
  expect(listTitles()).toEqual([
    "daily-new",
    "daily-old",
    "a-new",
    "a-edge-old",
    "b-edge",
  ]);
  fireEvent.click(group);
  expect(screen.queryByRole("group", { name: /^Codex ·/ })).toBeNull();
  expect(listTitles()).toEqual([
    "daily-new",
    "a-new",
    "b-edge",
    "a-edge-old",
    "daily-old",
  ]);
});

it("reveals a conversation restored through history when filters would hide it", () => {
  const { props, rerender } = setup();
  fireEvent.click(
    within(openAgents()).getByRole("checkbox", { name: "Codex Project A" }),
  );
  fireEvent.click(screen.getByRole("button", { name: recentLabel }));
  fireEvent.change(screen.getByLabelText("搜索对话"), {
    target: { value: "new" },
  });
  rerender(<Conversations {...props} sessionID="daily-old" />);
  expect(
    screen
      .getByRole("button", { name: recentLabel })
      .getAttribute("aria-pressed"),
  ).toBe("false");
  expect(listTitles()).toContain("daily-old");
});

it("clears a deleted agent's filter instead of leaving an empty stale list", () => {
  const { props, rerender } = setup();
  fireEvent.click(
    within(openAgents()).getByRole("checkbox", { name: "Codex Project A" }),
  );
  rerender(
    <Conversations
      {...props}
      state={{
        ...props.state,
        agents: props.state.agents.filter((a) => a.id !== "a"),
        sessions: props.state.sessions.filter((s) => s.agent_id !== "a"),
      }}
    />,
  );
  expect(listTitles()).toEqual(["daily-new", "b-edge", "daily-old"]);
});
