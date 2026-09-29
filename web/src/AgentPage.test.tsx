import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  act,
} from "@testing-library/react";
import App from "./App";
import type { DockState } from "./types";
import { clearModelCatalog } from "./modelCatalog";

const state: DockState = {
  runtime: { enabled: true, version: "0.3.0" },
  projects: [],
  agents: ["Alpha", "Beta"].map((name, i) => ({
    id: `a${i}`,
    name,
    provider: "codex",
    project_id: null,
    role: "",
  })),
  sessions: [
    { id: "s0", agent_id: "a0", title: "First conversation" },
    { id: "s1", agent_id: "a0", title: "Second conversation" },
    { id: "s2", agent_id: "a1", title: "Beta conversation" },
  ].map((s) => ({
    ...s,
    project_id: null,
    status: "idle",
    created_at: "",
    updated_at: "",
  })),
  runs: [],
  messages: [],
  events: [],
  proposals: [],
  approvals: [],
  memories: [],
  quotas: [],
  subscriptions: [],
};
afterEach(() => {
  cleanup();
  clearModelCatalog();
  vi.unstubAllGlobals();
  delete window.__AGENTDOCK_DESKTOP_TOKEN__;
  window.history.replaceState(null, "", "/");
});
async function setup(hash = "") {
  window.history.replaceState(null, "", "/" + hash);
  const fetchMock = vi.fn(async (path: string, _init?: RequestInit) => ({
    ok: true,
    json: async () =>
      path === "/api/state"
        ? state
        : path.includes("/events?")
          ? { events: [] }
          : { models: [] },
  }));
  vi.stubGlobal("fetch", fetchMock);
  window.__AGENTDOCK_DESKTOP_TOKEN__ = "page-fixture";
  render(<App />);
  await screen.findByRole("button", { name: "协作工作台" });
  await waitFor(() => expect(screen.queryByText("连接本地工作台")).toBeNull());
  return fetchMock;
}
const open = (name: string) =>
  fireEvent.click(
    screen.getByRole("button", { name: new RegExp(`^${name}.*进入会话`) }),
  );
const back = () =>
  fireEvent.click(screen.getByRole("button", { name: "返回 Agent 列表" }));
const draft = () =>
  screen.getByLabelText("给 Agent 的任务") as HTMLTextAreaElement;

it("opens a dedicated page with only that agent's conversations, then returns to overview", async () => {
  const fetchMock = await setup();
  expect(screen.queryByRole("heading", { name: "会话" })).toBeNull();
  expect(fetchMock.mock.calls.some(([path]) => path.includes("/events?"))).toBe(
    false,
  );
  open("Alpha");
  expect(window.location.hash).toBe("#/agents/a0");
  expect(screen.getByRole("heading", { name: "Alpha", level: 1 })).toBeTruthy();
  expect(
    screen.getByRole("heading", { name: "First conversation" }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: /^Beta/ })).toBeNull();
  expect(screen.queryByRole("button", { name: "添加 Agent" })).toBeNull();
  expect(screen.queryByText("TPS")).toBeNull();
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([path]) => path === "/api/sessions/s0/events?after=0",
      ),
    ).toBe(true),
  );
  back();
  expect(window.location.hash).toBe("#/workspace");
  expect(screen.queryByLabelText("给 Agent 的任务")).toBeNull();
  expect(screen.getByRole("heading", { name: "协作工作台" })).toBeTruthy();
  expect(
    fetchMock.mock.calls.every(
      ([, init]) => (init as RequestInit | undefined)?.method !== "POST",
    ),
  ).toBe(true);
});

it("remembers each agent's selected conversation and keeps drafts separate across pages", async () => {
  await setup();
  open("Alpha");
  fireEvent.change(draft(), { target: { value: "first draft" } });
  fireEvent.click(screen.getByRole("button", { name: /^Second conversation/ }));
  expect(draft().value).toBe("");
  fireEvent.change(draft(), { target: { value: "second draft" } });
  back();
  open("Beta");
  expect(draft().value).toBe("");
  fireEvent.change(draft(), { target: { value: "beta draft" } });
  back();
  open("Alpha");
  expect(
    screen.getByRole("heading", { name: "Second conversation" }),
  ).toBeTruthy();
  expect(draft().value).toBe("second draft");
  fireEvent.click(screen.getByRole("button", { name: /^First conversation/ }));
  expect(draft().value).toBe("first draft");
  back();
  open("Beta");
  expect(draft().value).toBe("beta draft");
});

it("supports browser back and forward without losing the in-memory draft", async () => {
  await setup();
  open("Alpha");
  fireEvent.change(draft(), { target: { value: "keep on back" } });
  act(() => window.history.back());
  await screen.findByRole("heading", { name: "协作工作台" });
  act(() => window.history.forward());
  await screen.findByRole("heading", { name: "Alpha", level: 1 });
  expect(draft().value).toBe("keep on back");
});

it("restores a linked agent page and returns an unavailable ID to the list", async () => {
  await setup("#/agents/a1");
  expect(screen.getByRole("heading", { name: "Beta", level: 1 })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "返回工作台" }));
  expect(screen.getByRole("heading", { name: "协作工作台" })).toBeTruthy();
  act(() => {
    window.history.pushState(null, "", "#/agents/deleted-agent");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await waitFor(() => expect(window.location.hash).toBe("#/workspace"));
  expect(screen.queryByLabelText("给 Agent 的任务")).toBeNull();
});
