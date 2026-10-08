import * as uiMessages from "../messages";
import ProjectAgentForm from "../ProjectAgentForm";
import { TPS, agentTPS } from "../metrics";
import { ApprovalCard, Empty, Stat, isArchived } from "../ui";
import AgentGrid from "./AgentGrid";
import AgentSettingsForm from "./AgentSettingsForm";
import ConversationPanel from "./ConversationPanel";
import SessionPanel from "./SessionPanel";
import { useWorkspaceController } from "./WorkspaceController";
import WorkspaceHeading from "./WorkspaceHeading";

export default function Workspace(
  props: Parameters<typeof useWorkspaceController>[0],
) {
  const view = useWorkspaceController(props);
  const {
    t,
    lang,
    project,
    metrics,
    metricsFailed,
    agents,
    sessions,
    approvals,
    state,
    token,
    demo,
    runtimeEnabled,
    busy,
    mutate,
    agentPageID,
    onNavigateAgent,
    initialEnvironment,
    onInitialEnvironmentUsed,
    onConfigureAgent,
    conversationOnly,
    sessionPageID,
    agentForm,
    setAgentForm,
    projectAgentForm,
    setProjectAgentForm,
    draftTarget,
    editingAgentID,
    setEditingAgentID,
    agentName,
    setAgentName,
    provider,
    setProvider,
    environment,
    setEnvironment,
    connectionDraft,
    setConnectionDraft,
    selectedConnection,
    connectionReady,
    connectionVersion,
    role,
    setRole,
    workspace,
    setWorkspace,
    agentProject,
    setAgentProject,
    model,
    setModel,
    effort,
    setEffort,
    runTimeout,
    setRunTimeout,
    accountDraft,
    setAccountDraft,
    permissionMode,
    setPermissionMode,
    discovery,
    selectedAvailable,
    catalog,
    models,
    catalogError,
    catalogLoading,
    internalAgentID,
    setInternalAgentID,
    agentID,
    setAgentID,
    sessionSelections,
    setSessionSelections,
    relevantSessions,
    sessionID,
    setSessionID,
    sessionTitle,
    setSessionTitle,
    accountSelectionRequest,
    setAccountSelectionRequest,
    prompts,
    setPrompts,
    prompt,
    setPrompt,
    pageTitle,
    previousAgent,
    submittingPrompt,
    composingPrompt,
    events,
    setEvents,
    eventError,
    setEventError,
    eventLoading,
    setEventLoading,
    selectedSession,
    selectedAgent,
    editingAgent,
    selectedProject,
    projectDirectory,
    changingEnvironment,
    running,
    sessionRuns,
    activeRuns,
    pendingDeliveries,
    hasSessionTasks,
    Heading,
  } = view;
  return (
    <section
      className={
        conversationOnly
          ? "conversation-view"
          : selectedAgent
            ? "agent-page"
            : "workspace-overview"
      }
    >
      {!conversationOnly && <WorkspaceHeading view={view} />}
      {!selectedAgent && (
        <div className={`stat-grid ${project ? "" : "workspace-stats"}`}>
          <Stat
            value={agents.length}
            label={t(...uiMessages.workspace_agents_bd5413)}
            icon="dock"
          />
          <Stat
            value={sessions.filter((s) => s.status === "running").length}
            label={t(...uiMessages.workspace_running_79c71e)}
            icon="bolt"
          />
          {project && (
            <Stat
              value={
                state.memories.filter(
                  (m) =>
                    !!project && m.project_id === project.id && !isArchived(m),
                ).length
              }
              label={t(...uiMessages.workspace_reviewed_memories_9a610b)}
              icon="memory"
            />
          )}
          <Stat
            value={approvals.length}
            label={t(...uiMessages.workspace_awaiting_approval_caad1d)}
            icon="shield"
          />
        </div>
      )}
      {agentForm && <AgentSettingsForm view={view} />}
      {project && projectAgentForm && !selectedAgent && (
        <ProjectAgentForm
          project={project}
          state={state}
          busy={busy && !demo}
          token={token}
          demo={demo}
          mutate={mutate}
          t={t}
          onClose={() => setProjectAgentForm(false)}
          onConfigure={onConfigureAgent}
          onAdded={(agent) => {
            setProjectAgentForm(false);
            setAgentID(agent.id);
          }}
        />
      )}
      {!selectedAgent && (
        <>
          {!!agents.length && (
            <section className="panel workspace-tps">
              <TPS
                meter={
                  project
                    ? agentTPS(
                        metrics,
                        agents.map((a) => a.id),
                      )
                    : metrics?.total
                }
                t={t}
                stale={metricsFailed}
              />
            </section>
          )}
          {agents.length ? (
            <AgentGrid view={view} />
          ) : (
            <section className="panel">
              <Empty
                icon="dock"
                title={t(...uiMessages.workspace_add_your_first_agent_992569)}
              >
                {t(
                  ...uiMessages.workspace_create_an_agent_open_a_session_and_explicitly_d3a818,
                )}
              </Empty>
            </section>
          )}
        </>
      )}
      {selectedAgent && !agentForm && (
        <div className="workspace-grid">
          {!conversationOnly && <SessionPanel view={view} />}
          <ConversationPanel view={view} />
        </div>
      )}
      {approvals.some(
        (a) =>
          a.session_id !== sessionID &&
          (!selectedAgent ||
            relevantSessions.some((s) => s.id === a.session_id)),
      ) && (
        <section className="panel inset-form">
          <h2>
            {t(...uiMessages.workspace_approvals_in_other_sessions_9c3f78)}
          </h2>
          {approvals
            .filter(
              (a) =>
                a.session_id !== sessionID &&
                (!selectedAgent ||
                  relevantSessions.some((s) => s.id === a.session_id)),
            )
            .map((approval) => (
              <ApprovalCard
                key={approval.id}
                approval={approval}
                busy={busy}
                mutate={mutate}
                t={t}
              />
            ))}
        </section>
      )}
    </section>
  );
}
