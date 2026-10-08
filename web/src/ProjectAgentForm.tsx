import * as uiMessages from "./messages";
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
        <h2>{t(...uiMessages.projectagentform_add_agent_to_project_34fdb2)}</h2>
        <button
          className="icon-button"
          aria-label={t(
            ...uiMessages.projectagentform_cancel_adding_agent_fe4fef,
          )}
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
          {t(...uiMessages.projectagentform_use_agent_cec758)}
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
              {t(
                ...uiMessages.projectagentform_choose_a_configured_agent_0b6742,
              )}
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
          {t(...uiMessages.projectagentform_name_in_this_project_1b1ec4)}
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            maxLength={100}
            placeholder={t(
              ...uiMessages.projectagentform_for_example_cr_or_coding_62d484,
            )}
          />
        </label>
        <label>
          {t(...uiMessages.projectagentform_project_role_optional_c8d252)}
          <textarea
            value={role}
            onChange={(event) => setRole(event.target.value)}
            maxLength={4000}
            rows={3}
            placeholder={t(
              ...uiMessages.projectagentform_for_example_review_code_risks_and_test_covera_5b7264,
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
              {t(...uiMessages.projectagentform_configure_a_new_agent_3143bc)}
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
            {t(...uiMessages.projectagentform_add_to_project_f76bee)}
          </button>
        </div>
      </form>
    </section>
  );
}
