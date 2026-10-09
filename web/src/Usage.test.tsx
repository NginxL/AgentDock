import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import Usage from "./views/Usage";
import { usageTargets, quotaRefreshTargets } from "./usageTargets";
import type { Account, Agent, Session } from "./types";

afterEach(cleanup);
const agent: Agent = {
  id: "agent",
  name: "Coding",
  provider: "codex",
  project_id: null,
  role: "",
  environment_id: "local",
  account_id: "personal",
};
const personal: Account = {
  id: "personal",
  label: "Personal",
  provider: "codex",
  environment_id: "local",
  status: "ready",
  identity: { plan: "Personal plan" },
  quota: { status: "ok", windows: [{ name: "weekly", remaining_percent: 12 }] },
};
const work: Account = {
  ...personal,
  id: "work",
  label: "Work",
  identity: { plan: "Work plan" },
  quota: { status: "ok", windows: [{ name: "weekly", remaining_percent: 34 }] },
};
const session: Session = {
  id: "one",
  agent_id: agent.id,
  title: "Use work account",
  project_id: null,
  status: "idle",
  created_at: "2026-10-01",
  updated_at: "2026-10-01",
  environment_id: "local",
  account_id: "work",
  account_policy: "manual",
};
function setup(agents: Agent[], sessions: Session[], accounts: Account[]) {
  return render(
    <Usage
      agents={agents}
      sessions={sessions}
      accounts={accounts}
      quotas={[
        {
          provider: "codex",
          source: "cli",
          status: "ok",
          plan: "Device plan",
          windows: [{ label: "Weekly", remaining_percent: 99 }],
        },
      ]}
      subscriptions={[]}
      onAddAgent={vi.fn()}
      refreshing={false}
      refreshFailed={false}
      busy={false}
      mutate={vi.fn()}
      lang="en"
      t={(_, en) => en}
    />,
  );
}

it("separates managed identities and explicit device-login conversations on the same agent", () => {
  const sessions = [
    session,
    {
      ...session,
      id: "device",
      title: "Device conversation",
      account_id: null,
    },
  ];
  setup([agent], sessions, [personal, work]);
  const card = (name: string) =>
    within(screen.getByRole("heading", { name }).closest("section")!);
  expect(card("Personal").getByText("Personal plan")).toBeTruthy();
  expect(
    card("Personal").getByRole("progressbar").getAttribute("aria-valuenow"),
  ).toBe("12");
  expect(
    card("Work").getByText("Conversations: Use work account"),
  ).toBeTruthy();
  expect(
    card("Work").getByRole("progressbar").getAttribute("aria-valuenow"),
  ).toBe("34");
  expect(
    card("Coding").getByText("Codex · This Mac · Device login"),
  ).toBeTruthy();
  expect(
    card("Coding").getByRole("progressbar").getAttribute("aria-valuenow"),
  ).toBe("99");
  expect(card("Personal").queryByText("Manual billing record")).toBeNull();
  expect(card("Coding").getByText("Manual billing record")).toBeTruthy();
});

it("keeps automatic pools and unavailable managed identities away from device quotas", () => {
  setup(
    [
      {
        ...agent,
        account_id: null,
        account_policy: "auto",
        account_ids: ["work"],
      },
      { ...agent, id: "missing", name: "Removed login", account_id: "removed" },
    ],
    [],
    [personal, work],
  );
  expect(screen.getByRole("heading", { name: "Work" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Personal" })).toBeNull();
  expect(
    screen.getByRole("heading", { name: "Account unavailable" }),
  ).toBeTruthy();
  expect(screen.queryByText("Device plan")).toBeNull();
  expect(screen.getAllByRole("progressbar")).toHaveLength(1);
});

it.each(["ready", "removed"] as const)(
  "renders a %s account with cleared quota metadata without using device limits",
  (status) => {
    setup([agent], [], [{ ...personal, status, quota: {} }]);
    expect(screen.getByRole("heading", { name: "Personal" })).toBeTruthy();
    expect(screen.getByText("No available quota data")).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByText("Device plan")).toBeNull();
  },
);

it("refreshes each actual identity once and retains a moved conversation's device", () => {
  const remote = { ...work, id: "remote", environment_id: "devbox" };
  const targets = usageTargets(
    [agent],
    [
      session,
      { ...session, id: "other", account_id: "work" },
      {
        ...session,
        id: "remote",
        account_id: "remote",
        environment_id: "devbox",
      },
      { ...session, id: "device", account_id: null, environment_id: "devbox" },
    ],
    [personal, work, remote],
  );
  expect(
    quotaRefreshTargets(targets).map(({ accountID, environment }) => [
      accountID ?? null,
      environment,
    ]),
  ).toEqual([
    ["personal", "local"],
    ["work", "local"],
    ["remote", "devbox"],
    [null, "devbox"],
  ]);
  expect(
    quotaRefreshTargets(
      usageTargets(
        [{ ...agent, account_id: null, account_policy: "auto" }],
        [],
        [{ ...personal, status: "disabled" }],
      ),
    ),
  ).toEqual([]);
});

it.each(["cli_event", "legacy_snapshot"])(
  "shows Claude observation source %s and sample time",
  (source) => {
    setup(
      [{ ...agent, provider: "claude" }],
      [],
      [
        {
          ...personal,
          provider: "claude",
          quota: {
            source,
            status: "ok",
            fetched_at: "2026-10-09T08:00:00Z",
            windows: [{ name: "session", remaining_percent: 15 }],
          },
        },
      ],
    );
    expect(
      screen.getByText(
        source === "cli_event"
          ? /Source: last run/
          : /Source: pre-upgrade record/,
      ),
    ).toBeTruthy();
    expect(screen.getByText(/15%/)).toBeTruthy();
  },
);
