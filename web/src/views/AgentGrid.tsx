import * as uiMessages from "../messages";
import ProviderIcon from "../ProviderIcon";
import { listOf, remainingPercent } from "../api";
import { TPS } from "../metrics";
import type { WorkspaceView } from "./WorkspaceController";
export default function AgentGrid({
  view,
}: {
  view: Pick<
    WorkspaceView,
    | "agents"
    | "setAgentID"
    | "provider"
    | "project"
    | "state"
    | "role"
    | "t"
    | "model"
    | "effort"
    | "sessions"
    | "metrics"
    | "metricsFailed"
  >;
}) {
  const {
    agents,
    setAgentID,
    provider,
    project,
    state,
    role,
    t,
    model,
    effort,
    sessions,
    metrics,
    metricsFailed,
  } = view;
  return (
    <div className="agent-grid">
      {agents.map((agent) => (
        <button
          className="agent-card"
          key={agent.id}
          onClick={() => setAgentID(agent.id)}
        >
          <div className="provider-symbol" aria-hidden="true">
            <ProviderIcon provider={agent.provider} />
          </div>
          <div className="agent-info">
            <strong>{agent.name}</strong>
            {!project && agent.project_id && (
              <span className="agent-project-name">
                {state.projects.find((p) => p.id === agent.project_id)?.name}
              </span>
            )}
            <p>
              {agent.role ||
                t(...uiMessages.agentgrid_no_role_set_follows_each_task_5eca02)}
            </p>
            <span className="model-summary">
              {agent.model ||
                t(...uiMessages.agentgrid_client_default_model_162745)}
              {agent.effort ? ` · ${agent.effort}` : ""}
            </span>
            {(() => {
              const managed = state.accounts?.find(
                (account) =>
                  account.id === agent.account_id &&
                  account.provider === agent.provider &&
                  account.environment_id ===
                    (agent.environment_id ?? "local") &&
                  account.status !== "removed",
              );
              const usesManagedAccount =
                !!agent.account_id ||
                (agent.account_policy ?? "manual") !== "manual";
              const quota = usesManagedAccount
                ? managed?.quota
                : listOf(state.quotas).find(
                    (q) =>
                      q.provider === agent.provider &&
                      (q.environment_id ?? "local") ===
                        (agent.environment_id ?? "local"),
                  );
              const value =
                quota &&
                ["ok", "ready", "available", "success", "exhausted"].includes(
                  quota.status ?? "",
                )
                  ? remainingPercent(quota.windows?.[0]?.remaining_percent)
                  : null;
              return (
                <span className="agent-quota">
                  {t(...uiMessages.agentgrid_current_usage_11e0a7)}:{" "}
                  {value === null
                    ? t(...uiMessages.agentgrid_unknown_6c2018)
                    : `${value}% ${t(...uiMessages.agentgrid_left_bbc2b1)}`}
                </span>
              );
            })()}
          </div>

          <span
            className={`small-status ${sessions.some((s) => s.agent_id === agent.id && s.status === "running") ? "live" : ""}`}
          >
            {sessions.some(
              (s) => s.agent_id === agent.id && s.status === "running",
            )
              ? t(...uiMessages.agentgrid_running_79c71e)
              : t(...uiMessages.agentgrid_idle_1f7cc9)}
          </span>
          <TPS
            meter={metrics?.agents[agent.id]}
            t={t}
            compact
            stale={metricsFailed}
          />
          <span className="agent-card-link">
            {t(...uiMessages.agentgrid_open_conversations_4c2828)}{" "}
            <span aria-hidden="true">→</span>
          </span>
        </button>
      ))}
    </div>
  );
}
