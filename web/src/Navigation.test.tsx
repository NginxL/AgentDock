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
import type { DockState } from "./types";

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

it.each([
  ["本机", "local"],
  ["Devbox", "remote"],
])(
  "creates an independent agent on %s from its device card without connecting or executing",
  async (name, id) => {
    const fetchMock = await setup();
    fireEvent.change(screen.getByLabelText("当前项目"), {
      target: { value: "p" },
    });
    fireEvent.click(screen.getByRole("button", { name: "设备与连接" }));
    const card = screen.getByRole("heading", { name }).closest("section")!;
    fireEvent.click(
      within(card).getByRole("button", { name: "在此设备添加 Agent" }),
    );
    expect((screen.getByLabelText("运行位置") as HTMLSelectElement).value).toBe(
      id,
    );
    expect(
      (screen.getByLabelText("关联项目（可选）") as HTMLSelectElement).value,
    ).toBe("");
    expect((screen.getByLabelText("当前项目") as HTMLSelectElement).value).toBe(
      "",
    );
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "New helper" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建 Agent" }));
    await waitFor(() => expect(screen.queryByLabelText("运行位置")).toBeNull());
    const writes = fetchMock.mock.calls.filter(
      ([, init]) => init?.method === "POST",
    );
    expect(writes).toHaveLength(1);
    expect(writes[0][0]).toBe("/api/agents");
    expect(JSON.parse(writes[0][1]!.body as string)).toMatchObject({
      environment_id: id,
      project_id: null,
      permission_mode: "ask",
      name: "New helper",
    });
    fireEvent.click(screen.getByRole("button", { name: "设备与连接" }));
    fireEvent.click(screen.getByRole("button", { name: "协作工作台" }));
    expect(screen.queryByLabelText("运行位置")).toBeNull();
  },
);

it("opens the actual agent form from the empty billing page and translates device labels", async () => {
  await setup({ agents: [] });
  fireEvent.click(screen.getByRole("button", { name: "额度与订阅" }));
  fireEvent.click(screen.getByRole("button", { name: "添加 Agent" }));
  expect((screen.getByLabelText("运行位置") as HTMLSelectElement).value).toBe(
    "local",
  );
  fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
  expect(screen.getByLabelText("Run on")).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Devices & connections" }),
  ).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Devices & connections" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Add SSH device" }));
  expect(screen.getByLabelText("Device name")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Add SSH device" }));
  expect(screen.queryByLabelText("Device name")).toBeNull();
});

it("toggles device setup, preserves its draft, and keeps the close button", async () => {
  const fetchMock = await setup();
  fireEvent.click(screen.getByRole("button", { name: "设备与连接" }));
  const button = screen.getByRole("button", { name: "添加 SSH 设备" });
  fireEvent.click(button);
  fireEvent.change(screen.getByLabelText("设备名称"), {
    target: { value: "Draft device" },
  });
  expect(button.getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(button);
  expect(screen.queryByLabelText("设备名称")).toBeNull();
  expect(button.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(button);
  expect((screen.getByLabelText("设备名称") as HTMLInputElement).value).toBe(
    "Draft device",
  );
  fireEvent.click(screen.getByRole("button", { name: "关闭设备表单" }));
  expect(screen.queryByLabelText("设备名称")).toBeNull();
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false,
  );
});

it("toggles agent forms without losing a collapsed draft, and switches targets instead of closing the wrong form", async () => {
  await setup();
  const add = screen.getByRole("button", { name: "添加 Agent" });
  const settings = screen.getByRole("button", { name: "设置 Local helper" });
  fireEvent.click(add);
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "My draft" },
  });
  fireEvent.click(add);
  expect(screen.queryByLabelText("名称")).toBeNull();
  expect(add.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(add);
  expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe(
    "My draft",
  );
  fireEvent.click(settings);
  expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe(
    "Local helper",
  );
  expect(settings.getAttribute("aria-expanded")).toBe("true");
  expect(add.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(settings);
  expect(screen.queryByLabelText("名称")).toBeNull();
  fireEvent.click(settings);
  fireEvent.click(screen.getByRole("button", { name: "取消编辑 Agent" }));
  expect(screen.queryByLabelText("名称")).toBeNull();
  fireEvent.click(add);
  fireEvent.click(screen.getByRole("button", { name: "取消添加 Agent" }));
  expect(screen.queryByLabelText("名称")).toBeNull();
});

it("toggles both project creation entry points and keeps the close button", async () => {
  await setup();
  fireEvent.click(screen.getByRole("button", { name: "共享记忆" }));
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
  fireEvent.change(screen.getByLabelText("当前项目"), {
    target: { value: "p" },
  });
  fireEvent.click(screen.getByRole("button", { name: "共享记忆" }));
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
