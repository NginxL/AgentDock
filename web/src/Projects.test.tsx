import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import App from "./App";
import type { DockState } from "./types";

const state: DockState = {
  runtime: { enabled: false, version: "0.3.0" },
  projects: ["Alpha", "Beta"].map((name) => ({
    id: name.toLowerCase(),
    name,
    path: `/private/${name}`,
  })),
  agents: ["Alpha", "Beta", "Independent"].map((name) => ({
    id: name,
    name: `${name} agent`,
    project_id: name === "Independent" ? null : name.toLowerCase(),
    provider: "codex",
    role: "",
  })),
  sessions: [
    {
      id: "s",
      title: "Alpha conversation",
      agent_id: "Alpha",
      project_id: "alpha",
      status: "idle",
      created_at: "",
      updated_at: "",
    },
  ],
  memories: ["alpha", "beta"].map((id) => ({
    id,
    project_id: id,
    key: `${id}.rules`,
    content: `${id} conventions`,
    version: 1,
  })),
  proposals: [
    {
      id: "p",
      project_id: "beta",
      agent_id: "Beta",
      key: "extra",
      content: "Proposed beta rule",
      expected_version: 0,
      status: "pending",
      created_at: "",
    },
  ],
  messages: [],
  events: [],
  approvals: [],
  quotas: [],
  subscriptions: [],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  delete window.__AGENTDOCK_DESKTOP_TOKEN__;
  window.history.replaceState(null, "", "/");
});
async function setup(hash = "") {
  window.history.replaceState(null, "", "/" + hash);
  const fetchMock = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path === "/api/state"
        ? state
        : path.includes("/events?")
          ? { events: [] }
          : { models: [] },
  }));
  vi.stubGlobal("fetch", fetchMock);
  window.__AGENTDOCK_DESKTOP_TOKEN__ = "projects-fixture";
  render(<App />);
  await screen.findByRole("navigation", { name: "主导航" });
  return fetchMock;
}
const mainNav = () =>
  within(screen.getByRole("navigation", { name: "主导航" }));
const projectNav = () =>
  within(screen.getByRole("navigation", { name: "项目导航" }));
const openAlpha = () => {
  fireEvent.click(mainNav().getByRole("button", { name: "项目" }));
  fireEvent.click(screen.getByRole("button", { name: "打开项目 Alpha" }));
};

it("groups projects in one entry and keeps independent agents on the workspace", async () => {
  const fetchMock = await setup();
  expect(mainNav().queryByRole("button", { name: "任务派工" })).toBeNull();
  expect(mainNav().queryByRole("button", { name: "共享记忆" })).toBeNull();
  expect(screen.queryByLabelText("当前项目")).toBeNull();
  expect(
    screen.getByRole("button", { name: /^Independent agent/ }),
  ).toBeTruthy();
  fireEvent.click(mainNav().getByRole("button", { name: "项目" }));
  expect(screen.getAllByRole("button", { name: /^打开项目 / })).toHaveLength(2);
  expect(screen.queryByText("/private/Alpha")).toBeNull();
  expect(screen.queryByRole("navigation", { name: "项目导航" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "打开项目 Alpha" }));
  expect(screen.getByRole("heading", { level: 1, name: "Alpha" })).toBeTruthy();
  expect(projectNav().getAllByRole("button")).toHaveLength(3);
  expect(screen.queryByRole("button", { name: /^Beta agent/ })).toBeNull();
  expect(
    screen.queryByRole("button", { name: /^Independent agent/ }),
  ).toBeNull();
  expect(fetchMock.mock.calls.some(([path]) => path.includes("/events?"))).toBe(
    false,
  );
  fireEvent.click(mainNav().getByRole("button", { name: "协作工作台" }));
  expect(window.location.hash).toBe("#/workspace");
  expect(
    screen.getByRole("button", { name: /^Independent agent/ }),
  ).toBeTruthy();
});

it("switches project memories, proposals and task recipients without crossing scopes", async () => {
  await setup();
  openAlpha();
  fireEvent.click(projectNav().getByRole("button", { name: "记忆" }));
  expect(screen.getByText("alpha conventions")).toBeTruthy();
  expect(screen.queryByText("beta conventions")).toBeNull();
  expect(screen.queryByText("Proposed beta rule")).toBeNull();
  fireEvent.change(screen.getByLabelText("切换项目"), {
    target: { value: "beta" },
  });
  expect(window.location.hash).toBe("#/projects?project=beta&view=memory");
  expect(screen.getByText("beta conventions")).toBeTruthy();
  expect(screen.getByText("Proposed beta rule")).toBeTruthy();
  expect(screen.queryByText("alpha conventions")).toBeNull();
  fireEvent.click(projectNav().getByRole("button", { name: "任务" }));
  fireEvent.click(screen.getByRole("button", { name: "新建任务" }));
  expect(screen.getByRole("option", { name: "Beta agent" })).toBeTruthy();
  expect(screen.queryByRole("option", { name: "Alpha agent" })).toBeNull();
  fireEvent.change(screen.getByLabelText("切换项目"), {
    target: { value: "alpha" },
  });
  fireEvent.click(screen.getByRole("button", { name: "新建任务" }));
  expect(screen.getByRole("option", { name: "Alpha agent" })).toBeTruthy();
  expect(screen.queryByRole("option", { name: "Beta agent" })).toBeNull();
});

it("returns from an agent to its project and restores project tabs through browser history", async () => {
  await setup();
  openAlpha();
  fireEvent.click(projectNav().getByRole("button", { name: "Agent" }));
  fireEvent.click(
    screen.getByRole("button", { name: /^Alpha agent.*进入会话/ }),
  );
  expect(window.location.hash).toBe("#/agents/Alpha?project=alpha");
  fireEvent.change(screen.getByLabelText("给 Agent 的任务"), {
    target: { value: "Project draft" },
  });
  fireEvent.click(screen.getByRole("button", { name: "返回 Agent 列表" }));
  expect(window.location.hash).toBe("#/projects?project=alpha&view=agents");
  fireEvent.click(
    screen.getByRole("button", { name: /^Alpha agent.*进入会话/ }),
  );
  expect(
    (screen.getByLabelText("给 Agent 的任务") as HTMLTextAreaElement).value,
  ).toBe("Project draft");
  fireEvent.click(screen.getByRole("button", { name: "返回 Agent 列表" }));
  fireEvent.click(projectNav().getByRole("button", { name: "任务" }));
  fireEvent.click(projectNav().getByRole("button", { name: "记忆" }));
  act(() => window.history.back());
  await screen.findByRole("heading", { name: "任务" });
  act(() => window.history.forward());
  await screen.findByRole("heading", { name: "项目记忆" });
  expect(screen.getByText("alpha conventions")).toBeTruthy();
});

it.each([
  ["#/projects?project=alpha&view=tasks", "任务"],
  ["#/projects?project=alpha&view=memory", "项目记忆"],
  ["#/messages?project=alpha", "任务"],
  ["#/memory?project=alpha", "项目记忆"],
  ["#/workspace?project=alpha", "Agent"],
  ["#/agents/Alpha?project=alpha", "Alpha agent"],
])("restores current and legacy project links: %s", async (hash, heading) => {
  await setup(hash);
  expect(screen.getByRole("heading", { name: heading })).toBeTruthy();
  expect(
    mainNav()
      .getByRole("button", { name: "项目" })
      .getAttribute("aria-current"),
  ).toBe("page");
});

it("returns a removed project to the list and translates project navigation", async () => {
  await setup("#/projects?project=removed&view=memory");
  await screen.findByRole("button", { name: "打开项目 Alpha" });
  expect(screen.queryByRole("heading", { name: "项目记忆" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
  expect(screen.getByRole("heading", { name: "Projects" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Open project Alpha" }));
  fireEvent.click(screen.getByRole("button", { name: "Memory" }));
  expect(screen.getByRole("heading", { name: "Project memory" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Back to projects" }));
  expect(screen.getByRole("heading", { name: "Projects" })).toBeTruthy();
});
