import type { Account, AccountSettings, Agent, Session } from "./types";

export type UsageTarget = {
  key: string;
  provider: Agent["provider"];
  environment: string;
  managed: boolean;
  accountID?: string;
  account?: Account;
  agentNames: string[];
  sessionNames: string[];
};

/** Device login and each managed identity own separate quota snapshots. */
export function usageTargets(
  agents: Agent[],
  sessions: Session[],
  accounts: Account[],
): UsageTarget[] {
  const targets = new Map<string, UsageTarget>();
  function add(
    agent: Agent,
    settings: AccountSettings,
    environment: string,
    session?: Session,
  ) {
    const managed =
      !!settings.account_id ||
      (settings.account_policy ?? "manual") !== "manual";
    const matching = accounts.filter(
      (a) => a.provider === agent.provider && a.environment_id === environment,
    );
    const candidates = settings.account_id
      ? [settings.account_id]
      : managed
        ? matching
            .filter(
              (a) =>
                a.status !== "removed" &&
                (!settings.account_ids?.length ||
                  settings.account_ids.includes(a.id)),
            )
            .map((a) => a.id)
        : [];
    for (const accountID of candidates.length ? candidates : [undefined]) {
      const key = JSON.stringify([
        environment,
        agent.provider,
        managed ? (accountID ?? "automatic") : null,
      ]);
      let target = targets.get(key);
      if (!target) {
        target = {
          key,
          provider: agent.provider,
          environment,
          managed,
          accountID,
          account: matching.find((a) => a.id === accountID),
          agentNames: [],
          sessionNames: [],
        };
        targets.set(key, target);
      }
      if (!target.agentNames.includes(agent.name))
        target.agentNames.push(agent.name);
      if (session && !target.sessionNames.includes(session.title))
        target.sessionNames.push(session.title);
    }
  }
  for (const agent of agents)
    add(agent, agent, agent.environment_id ?? "local");
  for (const session of sessions) {
    const agent = agents.find((a) => a.id === session.agent_id);
    if (!agent) continue;
    // Older API fixtures omitted account fields. Explicit null means device login,
    // even when the agent now defaults to a different managed account.
    const settings =
      "account_id" in session || "account_policy" in session ? session : agent;
    add(
      agent,
      settings,
      session.environment_id ?? agent.environment_id ?? "local",
      session,
    );
  }
  return [...targets.values()];
}

export function quotaRefreshTargets(targets: UsageTarget[]) {
  return targets
    .filter(
      (target) =>
        !target.managed ||
        (target.account &&
          target.account.enabled !== false &&
          ["ready", "cooldown"].includes(target.account.status)),
    )
    .map(({ key, provider, environment, accountID, account }) => ({
      key,
      provider,
      environment,
      accountID,
      generation: account?.generation,
    }));
}
