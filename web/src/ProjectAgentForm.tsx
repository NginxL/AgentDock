import { useState } from "react";
import type { Agent, DockState, Mutate, Project, Translate } from "./types";
import { Icon } from "./ui";
import ProviderIcon from "./ProviderIcon";
import WorkspaceDirectory from "./WorkspaceDirectory";

export default function ProjectAgentForm({
  project,
  state,
  busy,
  token,
  demo,
  mutate,
  onAdded,
  onClose,
  onConfigure,
  t,
}: {
  project: Project;
  state: DockState;
  busy: boolean;
  token: string;
  demo: boolean;
  mutate: Mutate;
  onAdded: (agent: Agent) => void;
  onClose: () => void;
  onConfigure?: () => void;
  t: Translate;
}) {
  // Existing project-bound agents can also be reused after upgrading.
  const sources = state.agents.filter((agent) => !agent.source_agent_id);
  const [sourceID, setSourceID] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [workspace, setWorkspace] = useState("");
  const source = sources.find((agent) => agent.id === sourceID);
  const environment = source?.environment_id ?? "local";
  const needsDirectory =
    !!source && environment !== (project.environment_id ?? "local");
  return (
    <section className="panel inset-form" id="project-agent-form">
      <div className="panel-heading">
        <h2>{t("添加 Agent 到项目", "Add agent to project")}</h2>
        <button
          className="icon-button"
          aria-label={t("取消添加 Agent", "Cancel adding agent")}
          onClick={onClose}
          disabled={busy}
        >
          <Icon name="close" />
        </button>
      </div>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (!source || (needsDirectory && !workspace.trim())) return;
          await mutate(
            `/api/projects/${encodeURIComponent(project.id)}/agents`,
            {
              source_agent_id: source.id,
              name: name.trim(),
              role: role.trim(),
              ...(needsDirectory ? { workspace: workspace.trim() } : {}),
            },
            onAdded,
          );
        }}
      >
        <label>
          {t("使用 Agent", "Use agent")}
          <select
            required
            value={sourceID}
            onChange={(event) => {
              const selected = sources.find(
                (agent) => agent.id === event.target.value,
              );
              setSourceID(event.target.value);
              setName(selected?.name ?? "");
              setRole(selected?.role ?? "");
              setWorkspace("");
            }}
          >
            <option value="">
              {t("选择已配置的 Agent", "Choose a configured agent")}
            </option>
            {sources.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
                {agent.project_id
                  ? ` · ${state.projects.find((p) => p.id === agent.project_id)?.name ?? ""}`
                  : ""}
              </option>
            ))}
          </select>
        </label>
        {source && (
          <div className="project-agent-source">
            <ProviderIcon provider={source.provider} />
            {source.name}
          </div>
        )}
        <label>
          {t("项目内名称", "Name in this project")}
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            maxLength={100}
            placeholder={t("例如 cr、coding", "For example, cr or coding")}
          />
        </label>
        <label>
          {t("项目职责（可选）", "Project role (optional)")}
          <textarea
            value={role}
            onChange={(event) => setRole(event.target.value)}
            maxLength={4000}
            rows={3}
            placeholder={t(
              "例如：审阅代码，检查风险与测试覆盖",
              "For example: review code, risks and test coverage",
            )}
          />
        </label>
        {needsDirectory && (
          <WorkspaceDirectory
            required
            value={workspace}
            onChange={setWorkspace}
            environment={environment}
            token={token}
            t={t}
            disabled={busy}
            browseEnabled={
              !demo &&
              state.runtime.enabled &&
              (environment === "local" ||
                state.environments?.some(
                  (e) => e.id === environment && e.status === "connected",
                ) === true)
            }
          />
        )}
        <div className="button-row project-agent-actions">
          {onConfigure && (
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={onConfigure}
            >
              {t("配置新 Agent", "Configure a new agent")}
            </button>
          )}
          <button
            className="primary"
            type="submit"
            disabled={
              busy ||
              demo ||
              !source ||
              !name.trim() ||
              (needsDirectory && !workspace.trim())
            }
          >
            {t("添加到项目", "Add to project")}
          </button>
        </div>
      </form>
    </section>
  );
}
