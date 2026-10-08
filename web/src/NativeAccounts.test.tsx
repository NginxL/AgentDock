import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import NativeAccounts from "./NativeAccounts";
import { quotaWindow } from "./accountDisplay";
import type { Account } from "./types";

const t = (zh: string) => zh;
const account: Account = {
  id: "one",
  label: "Personal",
  provider: "claude",
  environment_id: "local",
  status: "ready",
};
const status = {
  available: true,
  recovery_needed: false,
  clients: [
    { id: "claude_code", saved: true, identity: { email: "one@example.test" } },
    { id: "claude_desktop", saved: false },
  ],
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function setup() {
  const fetch = vi.fn(
    async (_url: string, _init: RequestInit) =>
      ({ ok: true, json: async () => status }) as Response,
  );
  vi.stubGlobal("fetch", fetch);
  const close = vi.fn();
  render(
    <NativeAccounts account={account} token="admin" close={close} t={t} />,
  );
  return { fetch, close };
}
it("opening only reads metadata; Claude CLI and desktop have distinct saved logins", async () => {
  const { fetch, close } = setup();
  await screen.findByText("Claude Code CLI");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][1].method).toBe("GET");
  const switches = screen.getAllByRole("button", { name: "切换到此账号" });
  expect((switches[0] as HTMLButtonElement).disabled).toBe(false);
  expect((switches[1] as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "关闭本机账号面板" }));
  expect(close).toHaveBeenCalledOnce();
});
it("switches only after explicit click and sends a client identifier, never credentials", async () => {
  const { fetch } = setup();
  await screen.findByText("Claude Code CLI");
  fireEvent.click(screen.getAllByRole("button", { name: "切换到此账号" })[0]);
  await screen.findByText(/已恢复保存的登录/);
  expect(fetch.mock.calls[1][1].method).toBe("POST");
  expect(JSON.parse(fetch.mock.calls[1][1].body as string)).toEqual({
    client: "claude_code",
    operation: "switch",
  });
});
it("shows recovery after a failed operation and blocks another switch", async () => {
  const { fetch } = setup();
  await screen.findByText("Claude Code CLI");
  fetch.mockImplementationOnce(
    async () =>
      ({
        ok: false,
        status: 400,
        json: async () => ({ error: "Recover previous login" }),
      }) as never,
  );
  fetch.mockImplementationOnce(
    async () =>
      ({
        ok: true,
        json: async () => ({
          ...status,
          recovery_needed: true,
          recovery_client: "claude_code",
        }),
      }) as never,
  );
  fireEvent.click(screen.getAllByRole("button", { name: "切换到此账号" })[0]);
  await screen.findByRole("button", { name: "恢复切换前登录" });
  expect(screen.getByRole("alert").textContent).toBe("Recover previous login");
  expect(
    (
      screen.getAllByRole("button", {
        name: "切换到此账号",
      })[0] as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});
it("labels actual quota durations without guessing primary and secondary windows", () => {
  expect(quotaWindow({ name: "primary", duration_minutes: 10080 }, t)).toBe(
    "7 天额度",
  );
  expect(quotaWindow({ name: "secondary", duration_minutes: 300 }, t)).toBe(
    "5 小时额度",
  );
  expect(quotaWindow({ name: "primary" }, t)).toBe("周期额度");
});
