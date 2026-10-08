import * as uiMessages from "../messages";
import { accountSettings, deviceAccount } from "../AccountSelection";
import AgentDeletion from "../AgentDeletion";
import { Icon } from "../ui";
import type { WorkspaceView } from "./WorkspaceController";
export default function WorkspaceHeading({
  view,
}: {
  view: Pick<
    WorkspaceView,
    | "selectedAgent"
    | "setAgentID"
    | "t"
    | "Heading"
    | "pageTitle"
    | "project"
    | "busy"
    | "demo"
    | "agentForm"
    | "editingAgentID"
    | "setAgentForm"
    | "draftTarget"
    | "setEditingAgentID"
    | "setAgentName"
    | "setProvider"
    | "provider"
    | "setEnvironment"
    | "setRole"
    | "role"
    | "setWorkspace"
    | "workspace"
    | "setAgentProject"
    | "setModel"
    | "model"
    | "setEffort"
    | "effort"
    | "setRunTimeout"
    | "setPermissionMode"
    | "setAccountDraft"
    | "sessions"
    | "state"
    | "mutate"
    | "agentID"
    | "setSessionID"
    | "setEvents"
    | "setPrompt"
    | "projectAgentForm"
    | "setProjectAgentForm"
    | "setConnectionDraft"
  >;
}) {
  const {
    selectedAgent,
    setAgentID,
    t,
    Heading,
    pageTitle,
    project,
    busy,
    demo,
    agentForm,
    editingAgentID,
    setAgentForm,
    draftTarget,
    setEditingAgentID,
    setAgentName,
    setProvider,
    provider,
    setEnvironment,
    setRole,
    role,
    setWorkspace,
    workspace,
    setAgentProject,
    setModel,
    model,
    setEffort,
    effort,
    setRunTimeout,
    setPermissionMode,
    setAccountDraft,
    sessions,
    state,
    mutate,
    agentID,
    setSessionID,
    setEvents,
    setPrompt,
    projectAgentForm,
    setProjectAgentForm,
    setConnectionDraft,
  } = view;
  return (
    <div className="page-heading">
      <div className="agent-page-title">
        {selectedAgent && (
          <button
            className="icon-button back-to-agents"
            onClick={() => setAgentID("")}
            aria-label={t(...uiMessages.workspaceheading_back_to_agents_0374a5)}
            title={t(...uiMessages.workspaceheading_back_to_agents_0374a5)}
          >
            <span aria-hidden="true">←</span>
          </button>
        )}
        <Heading ref={pageTitle} tabIndex={-1}>
          {selectedAgent?.name ??
            (project
              ? t(...uiMessages.workspaceheading_agents_bd5413)
              : t(...uiMessages.workspaceheading_workspace_e6f3d2))}
        </Heading>
      </div>
      <div className="button-row">
        {selectedAgent && (
          <button
            className="secondary"
            disabled={busy && !demo}
            aria-expanded={agentForm && editingAgentID === selectedAgent.id}
            aria-controls="agent-form"
            aria-label={t(
              `设置 ${selectedAgent.name}`,
              `Configure ${selectedAgent.name}`,
            )}
            onClick={() => {
              if (agentForm && editingAgentID === selectedAgent.id) {
                setAgentForm(false);
                return;
              }
              if (draftTarget.current !== selectedAgent.id) {
                setEditingAgentID(selectedAgent.id);
                setAgentName(selectedAgent.name);
                setProvider(selectedAgent.provider);
                setEnvironment(selectedAgent.environment_id ?? "local");
                setRole(selectedAgent.role);
                setWorkspace(
                  selectedAgent.workspace_is_default
                    ? ""
                    : (selectedAgent.workspace ?? ""),
                );
                setAgentProject(selectedAgent.project_id ?? "");
                setModel(selectedAgent.model ?? "");
                setEffort(selectedAgent.effort ?? "");
                setRunTimeout(
                  selectedAgent.run_timeout
                    ? String(selectedAgent.run_timeout / 60)
                    : "",
                );
                setPermissionMode(selectedAgent.permission_mode ?? "ask");
                setAccountDraft(accountSettings(selectedAgent));
                draftTarget.current = selectedAgent.id;
              }
              setAgentForm(true);
            }}
          >
            {t(...uiMessages.workspaceheading_agent_settings_207090)}
          </button>
        )}
        {selectedAgent && (
          <AgentDeletion
            key={selectedAgent.id}
            agent={selectedAgent}
            sessionCount={
              sessions.filter((s) => s.agent_id === selectedAgent.id).length
            }
            active={
              (state.runs ?? []).some(
                (r) =>
                  r.agent_id === selectedAgent.id &&
                  ["queued", "running"].includes(r.status),
              ) ||
              sessions.some(
                (s) =>
                  s.agent_id === selectedAgent.id &&
                  ["queued", "running", "waiting"].includes(s.status),
              ) ||
              state.messages.some(
                (m) =>
                  (m.sender_id === selectedAgent.id ||
                    m.recipient_id === selectedAgent.id) &&
                  ["queued", "running", "waiting"].includes(m.status ?? ""),
              )
            }
            busy={busy}
            mutate={mutate}
            t={t}
            onDeleted={() => {
              if (editingAgentID === selectedAgent.id) {
                setAgentForm(false);
                setEditingAgentID(null);
                draftTarget.current = null;
              }
              if (agentID === selectedAgent.id) {
                setAgentID("");
                setSessionID("");
                setEvents([]);
                setPrompt("");
              }
            }}
          />
        )}
        {!selectedAgent && (
          <button
            className="primary"
            disabled={busy && !demo}
            aria-expanded={
              project ? projectAgentForm : agentForm && editingAgentID === null
            }
            aria-controls={project ? "project-agent-form" : "agent-form"}
            onClick={() => {
              if (project) {
                setProjectAgentForm(!projectAgentForm);
                return;
              }
              if (agentForm && editingAgentID === null) {
                setAgentForm(false);
                return;
              }
              if (draftTarget.current !== "new") {
                setEditingAgentID(null);
                setAgentName("");
                setProvider("codex");
                setEnvironment("local");
                setConnectionDraft({
                  host: "",
                  python: "python3",
                  previous: "local",
                });
                setRole("");
                setWorkspace("");
                setAgentProject("");
                setModel("");
                setEffort("");
                setPermissionMode("ask");
                setRunTimeout("");
                setAccountDraft(deviceAccount);
                draftTarget.current = "new";
              }
              setAgentForm(true);
            }}
          >
            <Icon name="plus" size={18} />
            {t(...uiMessages.workspaceheading_add_agent_3bb60f)}
          </button>
        )}
      </div>
    </div>
  );
}
