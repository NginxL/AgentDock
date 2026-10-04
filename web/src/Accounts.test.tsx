import { useState } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Accounts from "./views/Accounts";
import Workspace from "./views/Workspace";
import AccountSelection, {
  deviceAccount,
  SessionAccountControls,
} from "./AccountSelection";
import AccountAttempts from "./AccountAttempts";
import { accountError, resetCountdown } from "./accountDisplay";
import type {
  Account,
  AccountSettings,
  Agent,
  DockState,
  Mutate,
  Session,
} from "./types";

const t = (zh: string) => zh;
const account: Account = {
  id: "personal",
  label: "Personal",
  provider: "codex",
  environment_id: "local",
  status: "ready",
  priority: 0,
  generation: 1,
};
const remote: Account = {
  ...account,
  id: "remote",
  label: "Remote",
  environment_id: "devbox",
};
const claude: Account = {
  ...account,
  id: "claude",
  label: "Work",
  provider: "claude",
};
const state: DockState = {
  projects: [],
  agents: [],
  sessions: [],
  messages: [],
  runs: [],
  memories: [],
  proposals: [],
  events: [],
  quotas: [],
  approvals: [],
  subscriptions: [],
  runtime: { enabled: true, version: "0.3.0" },
  accounts: [account, remote, claude],
  environments: [
    { id: "devbox", name: "Devbox", kind: "ssh", status: "connected" },
  ],
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
function setup(extra: Partial<DockState> = {}) {
  const mutate = vi.fn<Mutate>(async (_path, _data, success) => {
    success?.({});
    return true;
  });
  const changed = vi.fn();
  render(
    <Accounts
      state={{ ...state, ...extra }}
      token="test"
      busy={false}
      mutate={mutate}
      onChanged={changed}
      t={t}
    />,
  );
  return { mutate, changed };
}
it("creates a subscription bound to the user's selected device and supports closing the form twice", async () => {
  const { mutate } = setup();
  const add = screen.getByRole("button", { name: "添加账号" });
  fireEvent.click(add);
  fireEvent.click(add);
  expect(screen.queryByLabelText("账号名称")).toBeNull();
  fireEvent.click(add);
  fireEvent.change(screen.getByLabelText("账号名称"), {
    target: { value: " Dev work " },
  });
  const form = screen.getByLabelText("账号名称").closest("form")!;
  fireEvent.change(within(form).getByLabelText("服务"), {
    target: { value: "claude" },
  });
  fireEvent.change(within(form).getByLabelText("设备"), {
    target: { value: "devbox" },
  });
  fireEvent.click(within(form).getByRole("button", { name: "添加" }));
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith("/api/accounts", {
      label: "Dev work",
      provider: "claude",
      environment_id: "devbox",
      priority: 0,
    }),
  );
});
it("filters removed accounts and device/provider independently", () => {
  setup({
    accounts: [
      ...state.accounts!,
      { ...account, id: "removed", label: "Old", status: "removed" },
    ],
  });
  expect(screen.queryByRole("heading", { name: "Old" })).toBeNull();
  fireEvent.change(screen.getByLabelText("设备"), {
    target: { value: "devbox" },
  });
  expect(screen.queryByRole("heading", { name: "Personal" })).toBeNull();
  expect(screen.getByRole("heading", { name: "Remote" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("服务"), {
    target: { value: "claude" },
  });
  expect(screen.getByText("暂无订阅账号")).toBeTruthy();
});
it("starts native device login, shows the code, and cancels without altering another account", async () => {
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({
      status: "waiting",
      url: "https://auth.example.test/device",
      device_code: "ABCD-1234",
    }),
  }));
  vi.stubGlobal("fetch", fetch);
  const { mutate } = setup({ accounts: [remote] });
  expect(screen.queryByRole("button", { name: "重新登录" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "设备码登录" }));
  await waitFor(() => expect(screen.getByText("ABCD-1234")).toBeTruthy());
  expect(mutate).toHaveBeenCalledWith("/api/accounts/remote/login", {
    method: "device",
  });
  expect(
    screen.getByRole("link", { name: /打开登录页面/ }).getAttribute("href"),
  ).toBe("https://auth.example.test/device");
  fireEvent.click(screen.getByRole("button", { name: "取消登录" }));
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith(
      "/api/accounts/remote/cancel",
      {},
      expect.any(Function),
    ),
  );
});
it("never renders an unsafe login URL, and can submit an explicit Claude callback code", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ status: "waiting", url: "javascript:alert(1)" }),
    })),
  );
  const { mutate } = setup({ accounts: [claude] });
  fireEvent.click(screen.getByRole("button", { name: "重新登录" }));
  const input = await screen.findByLabelText("授权码（仅登录页面提供时填写）");
  expect(screen.queryByRole("link", { name: /打开登录页面/ })).toBeNull();
  fireEvent.change(input, { target: { value: "code-from-browser" } });
  fireEvent.click(screen.getByRole("button", { name: "提交验证码" }));
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith("/api/accounts/claude/input", {
      code: "code-from-browser",
    }),
  );
});
it("edits, disables and explicitly deletes an account while preserving a missing quota as unknown", async () => {
  const { mutate } = setup({
    accounts: [
      {
        ...account,
        quota: {
          windows: [{ label: "Weekly", remaining_percent: null }],
          status: "unknown",
          source: "cli",
        },
      },
    ],
  });
  expect(screen.getByText("未知")).toBeTruthy();
  expect(screen.getByRole("button", { name: "删除账号" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "设置" }));
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "Personal 2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith("/api/accounts/personal", {
      label: "Personal 2",
      priority: 0,
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "设置" }));
  fireEvent.click(screen.getByRole("button", { name: "停用账号" }));
  expect(mutate).toHaveBeenCalledWith("/api/accounts/personal", {
    enabled: false,
  });
  fireEvent.click(screen.getByRole("button", { name: "设置" }));
  expect(screen.queryByLabelText("名称")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "删除账号" }));
  fireEvent.click(screen.getByRole("button", { name: "删除账号" }));
  expect(screen.queryByRole("button", { name: "确认删除账号" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "删除账号" }));
  fireEvent.click(screen.getByRole("button", { name: "关闭删除确认" }));
  expect(screen.queryByRole("button", { name: "确认删除账号" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "删除账号" }));
  expect(mutate).not.toHaveBeenCalledWith("/api/accounts/personal/delete", {});
  fireEvent.click(screen.getByRole("button", { name: "确认删除账号" }));
  expect(mutate).toHaveBeenCalledWith("/api/accounts/personal/delete", {});
});
it("only offers accounts for the exact service and device and submits an explicit failover pool", () => {
  let latest: AccountSettings = {};
  function Harness() {
    const [value, setValue] = useState<AccountSettings>(deviceAccount);
    return (
      <AccountSelection
        accounts={state.accounts!}
        provider="codex"
        environment="local"
        value={value}
        onChange={(next) => {
          latest = next;
          setValue(next);
        }}
        t={t}
      />
    );
  }
  render(<Harness />);
  expect(screen.queryByRole("option", { name: /Remote|Work/ })).toBeNull();
  fireEvent.change(screen.getByLabelText("账号使用方式"), {
    target: { value: "failover" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: /Personal/ }));
  expect(latest).toEqual({
    account_id: null,
    account_policy: "failover",
    account_ids: ["personal"],
  });
});
it("changes only the current session and keeps a removed account explicit instead of falling back", async () => {
  const agent: Agent = {
    id: "agent",
    name: "Codex",
    provider: "codex",
    role: "",
    project_id: null,
  };
  const session: Session = {
    id: "session",
    agent_id: "agent",
    title: "One",
    project_id: null,
    status: "idle",
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
    account_id: "deleted",
  };
  const mutate = vi.fn<Mutate>(async () => true);
  render(
    <SessionAccountControls
      accounts={[account]}
      agent={agent}
      session={session}
      busy={false}
      demo={false}
      mutate={mutate}
      t={t}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /账号不可用/ }));
  expect((screen.getByLabelText("订阅账号") as HTMLSelectElement).value).toBe(
    "deleted",
  );
  fireEvent.change(screen.getByLabelText("订阅账号"), {
    target: { value: "personal" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存账号设置" }));
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith("/api/sessions/session/account", {
      account_id: "personal",
      account_policy: "manual",
      account_ids: [],
    }),
  );
});
it("opens account settings outside the clipped conversation, traps focus, and restores the trigger", () => {
  const agent: Agent = {
    id: "agent",
    name: "Codex",
    provider: "codex",
    role: "",
    project_id: null,
  };
  const session: Session = {
    id: "session",
    agent_id: agent.id,
    title: "One",
    project_id: null,
    status: "idle",
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
    account_id: null,
  };
  const mutate = vi.fn<Mutate>(async () => true);
  const { container } = render(
    <div style={{ height: 200, overflow: "hidden" }}>
      <SessionAccountControls
        accounts={[account]}
        agent={agent}
        session={session}
        busy={false}
        demo={false}
        mutate={mutate}
        t={t}
      />
    </div>,
  );
  const trigger = screen.getByRole("button", { name: "沿用设备登录" });
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "会话账号" });
  expect(container.contains(dialog)).toBe(false);
  expect(document.activeElement).toBe(dialog);
  const save = screen.getByRole("button", { name: "保存账号设置" });
  save.focus();
  fireEvent.keyDown(save, { key: "Tab" });
  expect(document.activeElement).toBe(
    screen.getByRole("button", { name: "关闭账号设置" }),
  );
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(mutate).not.toHaveBeenCalled();
});
it("shows account switch and wait events without printing raw payloads", () => {
  render(
    <AccountAttempts
      accounts={[account]}
      attempts={[]}
      events={[
        {
          id: "switch",
          seq: 1,
          session_id: "s",
          project_id: null,
          kind: "account_switched",
          payload: { to_account_id: "personal", secret: "must-not-render" },
          created_at: "2026-01-01",
        },
        {
          id: "wait",
          seq: 2,
          session_id: "s",
          project_id: null,
          kind: "account_waiting",
          payload: { account_id: "personal" },
          created_at: "2026-01-01",
        },
      ]}
      t={t}
    />,
  );
  expect(screen.getByText("已切换账号")).toBeTruthy();
  expect(screen.getByRole("status").textContent).toContain("等待");
  expect(screen.queryByText("must-not-render")).toBeNull();
});

it("hides legacy device-login attempts while retaining removed managed account history", () => {
  const attempt = {
    id: "attempt",
    run_id: "run",
    account_id: null,
    status: "completed",
    created_at: "2026-01-01",
  };
  const event = {
    id: "event",
    seq: 1,
    session_id: "s",
    project_id: null,
    kind: "account_attempt",
    payload: { account_id: null },
    created_at: "2026-01-01",
  };
  const { container, rerender } = render(
    <AccountAttempts attempts={[attempt]} events={[event]} t={t} />,
  );
  expect(container.textContent).toBe("");
  rerender(
    <AccountAttempts
      attempts={[{ ...attempt, account_id: "removed" }]}
      events={[]}
      accounts={[{ ...account, id: "removed", status: "removed" }]}
      t={t}
    />,
  );
  expect(screen.getByText("账号使用记录")).toBeTruthy();
  expect(screen.getByText("Personal")).toBeTruthy();
});

it("opens manual account selection after a failed run with preserved progress", () => {
  const configure = vi.fn();
  render(
    <AccountAttempts
      accounts={[account]}
      active={false}
      events={[
        {
          id: "required",
          seq: 1,
          session_id: "s",
          project_id: null,
          kind: "account_action_required",
          payload: {
            account_id: "personal",
            reason: "progress_recorded",
            error_code: "quota_exhausted",
          },
          created_at: "2026-01-01",
        },
      ]}
      t={t}
      onConfigureAccount={configure}
    />,
  );
  expect(screen.getByRole("status").textContent).toContain("已保留执行现场");
  fireEvent.click(screen.getByRole("button", { name: "选择账号后继续" }));
  expect(configure).toHaveBeenCalledOnce();
  expect(screen.queryByText("progress_recorded")).toBeNull();
});

it("opens the requested account panel and retains the explicit account if saving fails", async () => {
  const agent: Agent = {
    id: "agent",
    name: "Codex",
    provider: "codex",
    role: "",
    project_id: null,
  };
  const session: Session = {
    id: "session",
    agent_id: "agent",
    title: "One",
    project_id: null,
    status: "failed",
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
    account_id: "removed",
  };
  const mutate = vi.fn<Mutate>(async () => false);
  const props = {
    accounts: [account],
    agent,
    session,
    busy: false,
    demo: false,
    mutate,
    t,
  };
  const { rerender } = render(
    <SessionAccountControls {...props} openRequest={0} />,
  );
  expect(screen.queryByLabelText("订阅账号")).toBeNull();
  rerender(<SessionAccountControls {...props} openRequest={1} />);
  const selector = screen.getByLabelText("订阅账号") as HTMLSelectElement;
  expect(selector.value).toBe("removed");
  fireEvent.click(screen.getByRole("button", { name: "保存账号设置" }));
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith("/api/sessions/session/account", {
      account_id: "removed",
      account_policy: "manual",
      account_ids: [],
    }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "保存账号设置" })).toBeTruthy(),
  );
  expect(selector.value).toBe("removed");
  fireEvent.change(selector, { target: { value: "personal" } });
  fireEvent.click(screen.getByRole("button", { name: "保存账号设置" }));
  await waitFor(() =>
    expect(mutate).toHaveBeenLastCalledWith("/api/sessions/session/account", {
      account_id: "personal",
      account_policy: "manual",
      account_ids: [],
    }),
  );
  expect(selector.value).toBe("personal");
  expect(
    mutate.mock.calls.every(
      ([, data]) => (data as AccountSettings).account_id !== null,
    ),
  ).toBe(true);
});

it("shows exact app usage, quota reset countdowns and safe account errors", () => {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-01-01T00:00:00Z"));
  setup({
    accounts: [
      {
        ...account,
        status: "cooldown",
        error: "quota_exhausted",
        usage: { input_tokens: 1200, output_tokens: 0, total_tokens: 1200 },
        quota: {
          status: "ready",
          fetched_at: "2026-01-01T00:00:00Z",
          windows: [
            {
              name: "weekly",
              remaining_percent: 0,
              reset_at: "2026-01-01T01:30:00Z",
            },
          ],
        },
      },
    ],
  });
  const usage = screen.getByLabelText("AgentDock 用量");
  expect(within(usage).getAllByText("1,200")).toHaveLength(2);
  expect(within(usage).getByText("0")).toBeTruthy();
  expect(screen.getByText("0% 剩余")).toBeTruthy();
  expect(screen.getByText("1 小时 30 分钟后恢复")).toBeTruthy();
  expect(
    screen.getByText("当前额度已用完，请等待恢复或选择其他账号。"),
  ).toBeTruthy();
  expect(screen.queryByText(/上次数据/)).toBeNull();
  expect(screen.queryByText("quota_exhausted")).toBeNull();
});

it("keeps unknown usage distinct from zero and empty quota distinct from exhausted", () => {
  setup({
    accounts: [
      {
        ...account,
        usage: { input_tokens: null, output_tokens: 0, total_tokens: null },
        quota: { status: "unknown", windows: [] },
      },
    ],
  });
  expect(
    within(screen.getByLabelText("AgentDock 用量")).getAllByText("—"),
  ).toHaveLength(2);
  expect(screen.getByText("额度暂未读取")).toBeTruthy();
  expect(screen.queryByRole("meter")).toBeNull();
});

it("explains native login failure without rendering a raw backend error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        status: "failed",
        error_code: "login_timeout",
        error: "secret-error-output",
      }),
    })),
  );
  setup({ accounts: [account] });
  fireEvent.click(screen.getByRole("button", { name: "重新登录" }));
  expect(
    await screen.findByText("登录等待已超时，请重新发起登录。"),
  ).toBeTruthy();
  expect(screen.queryByText("secret-error-output")).toBeNull();
});

it("handles passed or invalid quota reset times without inventing availability", () => {
  const now = Date.parse("2026-01-01T00:00:00Z");
  expect(resetCountdown("invalid", now, t)).toBe("恢复时间未知");
  expect(resetCountdown("2026-01-01T00:00:00Z", now, t)).toBe(
    "已到恢复时间，可刷新确认",
  );
  expect(resetCountdown("2026-01-02T01:00:00Z", now, t)).toBe(
    "1 天 1 小时后恢复",
  );
  expect(accountError("unexpected-secret-value", t)).toBe(
    "账号操作暂未成功，请检查设备连接和登录状态后重试。",
  );
});

it("uses managed account quotas on Agent cards and never falls back to device quota", () => {
  const base: Agent = {
    id: "fixed",
    name: "Fixed helper",
    provider: "codex",
    project_id: null,
    role: "",
    account_id: "personal",
    account_policy: "manual",
  };
  const agents: Agent[] = [
    base,
    { ...base, id: "zero", name: "Exhausted helper", account_id: "exhausted" },
    { ...base, id: "removed", name: "Removed helper", account_id: "removed" },
    {
      ...base,
      id: "remote",
      name: "Wrong device helper",
      account_id: "remote",
    },
    {
      ...base,
      id: "auto",
      name: "Automatic helper",
      account_id: null,
      account_policy: "auto",
    },
    { ...base, id: "legacy", name: "Legacy helper", account_id: null },
  ];
  render(
    <Workspace
      t={t}
      lang="zh"
      state={{
        ...state,
        agents,
        accounts: [
          {
            ...account,
            quota: { status: "ready", windows: [{ remaining_percent: 27 }] },
          },
          {
            ...account,
            id: "exhausted",
            status: "cooldown",
            quota: { status: "exhausted", windows: [{ remaining_percent: 0 }] },
          },
          {
            ...account,
            id: "removed",
            status: "removed",
            quota: { status: "ready", windows: [{ remaining_percent: 32 }] },
          },
          {
            ...remote,
            quota: { status: "ready", windows: [{ remaining_percent: 44 }] },
          },
        ],
        quotas: [
          {
            provider: "codex",
            status: "ok",
            source: "device",
            windows: [{ label: "Device", remaining_percent: 89 }],
          },
        ],
      }}
      agents={agents}
      sessions={[]}
      approvals={[]}
      token="test"
      demo
      runtimeEnabled
      busy={false}
      mutate={async () => true}
    />,
  );
  expect(
    within(screen.getByRole("button", { name: /^Fixed helper/ })).getByText(
      "当前额度: 27% 剩余",
    ),
  ).toBeTruthy();
  expect(
    within(screen.getByRole("button", { name: /^Exhausted helper/ })).getByText(
      "当前额度: 0% 剩余",
    ),
  ).toBeTruthy();
  for (const name of [
    "Removed helper",
    "Wrong device helper",
    "Automatic helper",
  ]) {
    expect(
      within(
        screen.getByRole("button", { name: new RegExp(`^${name}`) }),
      ).getByText("当前额度: 未知"),
    ).toBeTruthy();
  }
  expect(
    within(screen.getByRole("button", { name: /^Legacy helper/ })).getByText(
      "当前额度: 89% 剩余",
    ),
  ).toBeTruthy();
});
