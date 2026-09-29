import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { StrictMode } from "react";
import App from "./App";
import type { DockState, Environment } from "./types";

const state: DockState = {
  environments: [
    { id: "local", name: "This Mac", kind: "local", status: "connected" },
    {
      id: "remote",
      name: "Devbox",
      kind: "ssh",
      ssh_host: "fixture-host",
      status: "connected",
    },
  ],
  projects: [{ id: "p", name: "Example project", path: "/example" }],
  agents: [
    {
      id: "a",
      name: "Local helper",
      project_id: "p",
      provider: "codex",
      role: "",
    },
    {
      id: "b",
      name: "Remote helper",
      project_id: null,
      provider: "codex",
      role: "",
      environment_id: "remote",
    },
  ],
  memories: [
    {
      id: "m1",
      project_id: "p",
      key: "stack",
      content: "TypeScript",
      version: 1,
      updated_at: "",
    },
    {
      id: "m2",
      project_id: "p",
      key: "tests",
      content: "Vitest",
      version: 1,
      updated_at: "",
    },
  ],
  subscriptions: [
    {
      provider: "codex",
      plan: "Local plan",
      currency: "USD",
      renewal_date: "",
      monthly_cost: null,
    },
    {
      provider: "codex",
      environment_id: "remote",
      plan: "Remote plan",
      currency: "USD",
      renewal_date: "",
      monthly_cost: null,
    },
  ],
  sessions: [],
  messages: [],
  proposals: [],
  events: [],
  quotas: [],
  approvals: [],
  runtime: { enabled: false, version: "0.3.0" },
};

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
  delete window.__AGENTDOCK_DESKTOP_TOKEN__;
  vi.unstubAllGlobals();
});

async function setup(extra: Partial<DockState> = {}) {
  let current = { ...state, ...extra };
  const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    let data: unknown = current;
    if (path === "/api/agents" && init?.method === "POST") {
      const agent = { ...JSON.parse(init.body as string), id: "created" };
      current = { ...current, agents: [...current.agents, agent] };
      data = agent;
    }
    if (path === "/api/environments" && init?.method === "POST") {
      const connection: Environment = {
        ...JSON.parse(init.body as string),
        id: "new-host",
        kind: "ssh",
        status: "disconnected",
      };
      current = {
        ...current,
        environments: [...(current.environments ?? []), connection],
      };
      data = connection;
    }
    if (path === "/api/environments/new-host/connect") {
      current = {
        ...current,
        environments: current.environments?.map((e) =>
          e.id === "new-host"
            ? { ...e, status: "connected", updated_at: "connected-now" }
            : e,
        ),
      };
      data = current.environments?.find((e) => e.id === "new-host");
    }
    if (path.startsWith("/api/models/")) data = { models: [] };
    return { ok: true, json: async () => data };
  });
  vi.stubGlobal("fetch", fetchMock);
  window.__AGENTDOCK_DESKTOP_TOKEN__ = "navigation-fixture";
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  await screen.findByRole("heading", { name: "协作工作台" });
  return fetchMock;
}

it.each(["local", "remote"])(
  "creates an independent agent on %s entirely within Add agent",
  async (id) => {
    const fetchMock = await setup();
    expect(screen.queryByRole("button", { name: "设备与连接" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "添加 Agent" }));
    fireEvent.change(screen.getByLabelText("设备"), {
      target: { value: id },
    });
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "My helper" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建 Agent" }));
    await waitFor(() => expect(screen.queryByLabelText("设备")).toBeNull());
    const writes = fetchMock.mock.calls.filter(
      ([, init]) => init?.method === "POST",
    );
    expect(writes).toHaveLength(1);
    expect(writes[0][0]).toBe("/api/agents");
    expect(JSON.parse(writes[0][1]!.body as string)).toMatchObject({
      name: "My helper",
      provider: "codex",
      environment_id: id,
      project_id: null,
      permission_mode: "ask",
    });
  },
);

it("opens agent creation from the empty billing page and keeps connection setup inside it in both languages", async () => {
  await setup({ agents: [] });
  fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
  fireEvent.click(screen.getByRole("button", { name: "添加 Agent" }));
  fireEvent.change(screen.getByLabelText("设备"), {
    target: { value: "new-ssh-connection" },
  });
  expect(screen.getByLabelText("SSH 地址或 Host 别名")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
  expect(
    screen.queryByRole("button", { name: "Devices & connections" }),
  ).toBeNull();
  expect(screen.getByLabelText("Device")).toBeTruthy();
  expect(screen.getByLabelText("SSH destination or Host alias")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Close SSH setup" }));
  expect((screen.getByLabelText("Device") as HTMLSelectElement).value).toBe(
    "local",
  );
  expect(screen.queryByLabelText("SSH destination or Host alias")).toBeNull();
});

it("connects a new host inside the agent form, preserves the agent draft, and discovers remote models only after connection", async () => {
  const fetchMock = await setup({
    runtime: { enabled: true, version: "0.3.0" },
  });
  fireEvent.click(screen.getByRole("button", { name: "添加 Agent" }));
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "My assistant" },
  });
  fireEvent.change(screen.getByLabelText("设备"), {
    target: { value: "new-ssh-connection" },
  });
  expect(
    (screen.getByRole("button", { name: "创建 Agent" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(
    fetchMock.mock.calls.some(([path]) =>
      path.includes("environment_id=new-ssh"),
    ),
  ).toBe(false);
  fireEvent.change(screen.getByLabelText("SSH 地址或 Host 别名"), {
    target: { value: "builder@devbox" },
  });
  fireEvent.click(screen.getByRole("button", { name: "连接并使用" }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(
        ([path]) => path === "/api/models/codex?environment_id=new-host",
      ),
    ).toBe(true),
  );
  expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe(
    "My assistant",
  );
  expect((screen.getByLabelText("设备") as HTMLSelectElement).value).toBe(
    "new-host",
  );
  fireEvent.click(screen.getByRole("button", { name: "创建 Agent" }));
  await waitFor(() => expect(screen.queryByLabelText("设备")).toBeNull());
  const writes = fetchMock.mock.calls.filter(
    ([, init]) => init?.method === "POST",
  );
  expect(writes.map(([path]) => path)).toEqual([
    "/api/environments",
    "/api/environments/new-host/connect",
    "/api/agents",
  ]);
  expect(JSON.parse(writes[2][1]!.body as string)).toMatchObject({
    name: "My assistant",
    environment_id: "new-host",
    provider: "codex",
  });
});

it("shows user names without provider or device suffixes and selects equal names by ID", async () => {
  await setup({ agents: state.agents.map((a) => ({ ...a, name: "Helper" })) });
  const cards = screen.getAllByRole("button", { name: /Helper.*待命/ });
  expect(cards).toHaveLength(2);
  for (const card of cards) {
    expect(within(card).queryByText("Codex")).toBeNull();
    expect(within(card).queryByText("Devbox")).toBeNull();
    expect(within(card).queryByText("本机")).toBeNull();
  }
  fireEvent.click(cards[1]);
  expect(window.location.hash).toBe("#/agents/b");
  expect(
    screen.getByRole("heading", { name: "Helper", level: 1 }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "设置 Helper" }));
  expect((screen.getByLabelText("设备") as HTMLSelectElement).value).toBe(
    "remote",
  );
  fireEvent.click(screen.getByRole("button", { name: "取消编辑 Agent" }));
  fireEvent.click(screen.getByRole("button", { name: "返回 Agent 列表" }));
  fireEvent.click(screen.getAllByRole("button", { name: /Helper.*待命/ })[0]);
  fireEvent.click(screen.getByRole("button", { name: "设置 Helper" }));
  expect((screen.getByLabelText("设备") as HTMLSelectElement).value).toBe(
    "local",
  );
});

it("toggles agent forms without losing a collapsed draft, and switches targets instead of closing the wrong form", async () => {
  await setup();
  const add = screen.getByRole("button", { name: "添加 Agent" });
  fireEvent.click(add);
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "My draft" },
  });
  fireEvent.change(screen.getByLabelText("设备"), {
    target: { value: "remote" },
  });
  fireEvent.change(screen.getByLabelText("设备"), {
    target: { value: "new-ssh-connection" },
  });
  fireEvent.change(screen.getByLabelText("SSH 地址或 Host 别名"), {
    target: { value: "builder@new-host" },
  });
  fireEvent.change(screen.getByLabelText("远端 Python"), {
    target: { value: "/usr/bin/python3" },
  });
  fireEvent.click(add);
  expect(screen.queryByLabelText("名称")).toBeNull();
  expect(add.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(add);
  expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe(
    "My draft",
  );
  expect(
    (screen.getByLabelText("SSH 地址或 Host 别名") as HTMLInputElement).value,
  ).toBe("builder@new-host");
  expect((screen.getByLabelText("远端 Python") as HTMLInputElement).value).toBe(
    "/usr/bin/python3",
  );
  fireEvent.click(screen.getByRole("button", { name: "关闭 SSH 连接配置" }));
  expect((screen.getByLabelText("设备") as HTMLSelectElement).value).toBe(
    "remote",
  );
  fireEvent.click(add);
  fireEvent.click(screen.getByRole("button", { name: /^Local helper/ }));
  const settings = screen.getByRole("button", { name: "设置 Local helper" });
  fireEvent.click(settings);
  expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe(
    "Local helper",
  );
  expect(settings.getAttribute("aria-expanded")).toBe("true");
  expect(screen.queryByRole("button", { name: "添加 Agent" })).toBeNull();
  fireEvent.click(settings);
  expect(screen.queryByLabelText("名称")).toBeNull();
  fireEvent.click(settings);
  fireEvent.click(screen.getByRole("button", { name: "取消编辑 Agent" }));
  expect(screen.queryByLabelText("名称")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "返回 Agent 列表" }));
  fireEvent.click(screen.getByRole("button", { name: "添加 Agent" }));
  fireEvent.click(screen.getByRole("button", { name: "取消添加 Agent" }));
  expect(screen.queryByLabelText("名称")).toBeNull();
});

it("toggles both project creation entry points and keeps the close button", async () => {
  await setup({ projects: [] });
  fireEvent.click(screen.getByRole("button", { name: "项目" }));
  const sidebar = screen.getByRole("button", { name: "新建项目" });
  const empty = screen.getByRole("button", { name: "创建第一个项目" });
  fireEvent.click(empty);
  expect(sidebar.getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(empty);
  expect(screen.queryByLabelText("项目名称")).toBeNull();
  fireEvent.click(sidebar);
  fireEvent.click(sidebar);
  expect(screen.queryByLabelText("项目名称")).toBeNull();
  fireEvent.click(sidebar);
  expect(screen.getByLabelText("项目所在设备")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "取消新建项目" }));
  expect(screen.queryByLabelText("项目名称")).toBeNull();
});

it("toggles memory creation and editing while keeping record selection separate", async () => {
  await setup();
  fireEvent.click(screen.getByRole("button", { name: "项目" }));
  fireEvent.click(
    screen.getByRole("button", { name: "打开项目 Example project" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "记忆" }));
  const add = screen.getByRole("button", { name: "新增记忆" });
  fireEvent.click(add);
  fireEvent.click(add);
  expect(screen.queryByRole("heading", { name: "新增已审阅记忆" })).toBeNull();
  const edit = screen.getAllByRole("button", { name: "编辑" });
  fireEvent.click(edit[0]);
  fireEvent.click(edit[0]);
  expect(screen.queryByRole("heading", { name: "编辑记忆" })).toBeNull();
  fireEvent.click(edit[0]);
  fireEvent.click(edit[1]);
  expect(edit[0].getAttribute("aria-expanded")).toBe("false");
  expect(edit[1].getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByDisplayValue("Vitest")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "关闭记忆编辑器" }));
  expect(screen.queryByRole("heading", { name: "编辑记忆" })).toBeNull();
});

it("toggles billing editing by provider AND device, retaining the close button", async () => {
  await setup();
  fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
  const edits = screen.getAllByRole("button", { name: "编辑" });
  fireEvent.click(edits[0]);
  expect(screen.getByDisplayValue("Local plan")).toBeTruthy();
  fireEvent.click(edits[0]);
  expect(screen.queryByLabelText("订阅方案")).toBeNull();
  fireEvent.click(edits[0]);
  fireEvent.click(edits[1]);
  expect(screen.getByDisplayValue("Remote plan")).toBeTruthy();
  expect(edits[0].getAttribute("aria-expanded")).toBe("false");
  expect(edits[1].getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "关闭订阅编辑器" }));
  expect(screen.queryByLabelText("订阅方案")).toBeNull();
});
