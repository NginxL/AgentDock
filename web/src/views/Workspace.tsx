import SessionListItem from "../SessionListItem";
import { followSession } from "../sessionEvents";
import { useEffect, useRef, useState } from "react";
import TaskTimeline from "../TaskTimeline";
import InferenceControls from "../InferenceControls";
import AccountSelection, {
  accountSettings,
  deviceAccount,
  supportsAccounts,
  SessionAccountControls,
} from "../AccountSelection";
import AgentDeletion from "../AgentDeletion";
import ProviderIcon from "../ProviderIcon";
import ProviderSelect from "../ProviderSelect";
import ProjectAgentForm from "../ProjectAgentForm";
import { useProviderAvailability } from "../providerAvailability";
import WorkspaceDirectory from "../WorkspaceDirectory";
import { useModelCatalog } from "../modelCatalog";
import AgentConnection, {
  NEW_SSH_CONNECTION,
  type SSHConnectionDraft,
} from "../AgentConnection";
import { TPS, agentTPS, type Metrics } from "../metrics";
import { listOf, remainingPercent, request } from "../api";
import type {
  Agent,
  AccountSettings,
  AgentEvent,
  Approval,
  DockState,
  Language,
  Mutate,
  PermissionMode,
  Project,
  Provider,
  Session,
  Translate,
} from "../types";
import {
  ApprovalCard,
  DateText,
  Empty,
  Icon,
  Stat,
  isArchived,
  statusLabel,
} from "../ui";

export default function Workspace({
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
  demo = false,
  runtimeEnabled,
  busy,
  mutate,
  agentPageID,
  onNavigateAgent,
  initialEnvironment,
  onInitialEnvironmentUsed,
  onConfigureAgent,
  conversationOnly = false,
  sessionPageID,
}: {
  t: Translate;
  lang: Language;
  project?: Project;
  metrics?: Metrics | null;
  metricsFailed?: boolean;
  agents: Agent[];
  sessions: Session[];
  approvals: Approval[];
  state: DockState;
  token: string;
  demo?: boolean;
  runtimeEnabled: boolean;
  busy: boolean;
  mutate: Mutate;
  agentPageID?: string;
  onNavigateAgent?: (id: string, replace?: boolean) => void;
  initialEnvironment?: string;
  onInitialEnvironmentUsed?: () => void;
  onConfigureAgent?: () => void;
  conversationOnly?: boolean;
  sessionPageID?: string;
}) {
  const [agentForm, setAgentForm] = useState(initialEnvironment !== undefined);
  const [projectAgentForm, setProjectAgentForm] = useState(false);
  const draftTarget = useRef<string | null>(
    initialEnvironment !== undefined ? "new" : null,
  );
  const [editingAgentID, setEditingAgentID] = useState<string | null>(null);
  const [agentName, setAgentName] = useState("");
  const [provider, setProvider] = useState<Provider>("codex");
  const [environment, setEnvironment] = useState(
    initialEnvironment ?? project?.environment_id ?? "local",
  );
  const [connectionDraft, setConnectionDraft] = useState<SSHConnectionDraft>({
    host: "",
    python: "python3",
    previous: environment,
  });
  useEffect(() => {
    if (initialEnvironment !== undefined) onInitialEnvironmentUsed?.();
  }, [initialEnvironment, onInitialEnvironmentUsed]);
  const selectedConnection = state.environments?.find(
    (e) => e.id === environment,
  );
  const connectionReady =
    environment === "local" || selectedConnection?.status === "connected";
  const connectionVersion = selectedConnection?.updated_at;
  const [role, setRole] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [agentProject, setAgentProject] = useState(project?.id ?? "");
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [runTimeout, setRunTimeout] = useState("");
  const [accountDraft, setAccountDraft] =
    useState<AccountSettings>(deviceAccount);
  const [permissionMode, setPermissionMode] = useState<PermissionMode>("ask");
  const discovery = useProviderAvailability(
    token,
    environment,
    agentForm && environment !== NEW_SSH_CONNECTION,
    demo,
    connectionVersion,
  );
  const selectedAvailable = discovery.providers?.[provider]?.available === true;
  const catalog = useModelCatalog(
    token,
    provider,
    environment,
    agentForm &&
      !demo &&
      (accountDraft.account_policy === "manual" || !!accountDraft.account_id) &&
      runtimeEnabled &&
      selectedAvailable &&
      connectionReady &&
      environment !== NEW_SSH_CONNECTION,
    connectionVersion,
    accountDraft.account_id,
    state.accounts?.find((account) => account.id === accountDraft.account_id)
      ?.generation,
  );
  const models = demo
    ? [
        {
          id: "demo-model",
          name: "Demo model",
          efforts: ["low", "medium", "high"],
        },
      ]
    : catalog.models;
  const catalogError = catalog.failed;
  const catalogLoading = catalog.loading;
  const [internalAgentID, setInternalAgentID] = useState("");
  const agentID = agentPageID ?? internalAgentID;
  function setAgentID(id: string, replace = false) {
    if (onNavigateAgent) onNavigateAgent(id, replace);
    else setInternalAgentID(id);
  }
  const [sessionSelections, setSessionSelections] = useState<
    Record<string, string>
  >({});
  const relevantSessions = sessions.filter((s) => s.agent_id === agentID);
  const sessionID =
    sessionPageID !== undefined
      ? relevantSessions.some((s) => s.id === sessionPageID)
        ? sessionPageID
        : ""
      : relevantSessions.some((s) => s.id === sessionSelections[agentID])
        ? sessionSelections[agentID]
        : (relevantSessions[0]?.id ?? "");
  function setSessionID(id: string) {
    setSessionSelections((current) => ({ ...current, [agentID]: id }));
  }
  const [sessionTitle, setSessionTitle] = useState("");
  const [accountSelectionRequest, setAccountSelectionRequest] = useState(0);
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const prompt = prompts[sessionID] ?? "";
  function setPrompt(value: string) {
    setPrompts((current) => ({ ...current, [sessionID]: value }));
  }
  const pageTitle = useRef<HTMLHeadingElement>(null);
  const previousAgent = useRef(agentID);
  const submittingPrompt = useRef(false);
  const composingPrompt = useRef(false);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [eventError, setEventError] = useState("");
  const [eventLoading, setEventLoading] = useState(false);
  const selectedSession = relevantSessions.find((s) => s.id === sessionID);
  const selectedAgent = agents.find((a) => a.id === agentID);
  const editingAgent = agents.find((a) => a.id === editingAgentID);
  const selectedProject = state.projects.find((p) => p.id === agentProject);
  const projectDirectory =
    selectedProject &&
    !workspace &&
    (selectedProject.environment_id ?? "local") === environment
      ? selectedProject.path
      : undefined;
  const changingEnvironment =
    !!editingAgent && environment !== (editingAgent.environment_id ?? "local");
  const running = selectedSession?.status === "running";
  const sessionRuns = (state.runs ?? []).filter(
    (run) => run.session_id === sessionID,
  );
  const activeRuns = sessionRuns.filter((run) =>
    ["queued", "running"].includes(run.status),
  );
  const pendingDeliveries = state.messages.filter((message) => {
    if (!sessionID) return false;
    const reply = (state.runs ?? []).find(
      (run) => run.id === message.reply_run_id,
    );
    return (
      (message.recipient_session_id === sessionID &&
        message.status === "waiting") ||
      (message.sender_session_id === sessionID &&
        (["queued", "running", "waiting"].includes(message.status ?? "") ||
          (reply && ["queued", "running"].includes(reply.status))))
    );
  });
  const hasSessionTasks =
    running ||
    selectedSession?.status === "waiting" ||
    activeRuns.length > 0 ||
    pendingDeliveries.length > 0;
  useEffect(() => {
    if (agentID && !agents.some((a) => a.id === agentID)) setAgentID("", true);
  }, [agents, agentID]);
  useEffect(() => {
    if (previousAgent.current === agentID) return;
    previousAgent.current = agentID;
    setAgentForm(false);
    setProjectAgentForm(false);
    setEditingAgentID(null);
    draftTarget.current = null;
    setSessionTitle("");
    composingPrompt.current = false;
    pageTitle.current?.focus({ preventScroll: true });
  }, [agentID]);
  useEffect(() => {
    setEvents([]);
    setEventError("");
    if (demo) {
      setEvents(state.events.filter((event) => event.session_id === sessionID));
      setEventLoading(false);
      return;
    }
    if (!sessionID) {
      setEventLoading(false);
      return;
    }
    const controller = new AbortController();
    setEventLoading(true);
    void followSession(
      token,
      sessionID,
      controller.signal,
      (incoming) => {
        setEvents((previous) => {
          const seen = new Set(previous.map((event) => event.id));
          return [
            ...previous,
            ...incoming.filter((event) => !seen.has(event.id)),
          ];
        });
      },
      (failed) => {
        if (controller.signal.aborted) return;
        setEventLoading(false);
        setEventError(
          failed
            ? lang === "zh"
              ? "事件连接中断，正在重连。"
              : "Event connection interrupted. Reconnecting."
            : "",
        );
      },
    );
    return () => controller.abort();
  }, [sessionID, token, lang, demo, demo ? state.events : null]);

  const Heading = project && !selectedAgent ? "h2" : "h1";
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
      {!conversationOnly && (
        <div className="page-heading">
          <div className="agent-page-title">
            {selectedAgent && (
              <button
                className="icon-button back-to-agents"
                onClick={() => setAgentID("")}
                aria-label={t("返回 Agent 列表", "Back to agents")}
                title={t("返回 Agent 列表", "Back to agents")}
              >
                <span aria-hidden="true">←</span>
              </button>
            )}
            <Heading ref={pageTitle} tabIndex={-1}>
              {selectedAgent?.name ??
                (project ? t("Agent", "Agents") : t("协作工作台", "Workspace"))}
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
                    setRunTimeout(selectedAgent.run_timeout ? String(selectedAgent.run_timeout / 60) : "");
                    setPermissionMode(selectedAgent.permission_mode ?? "ask");
                    setAccountDraft(accountSettings(selectedAgent));
                    draftTarget.current = selectedAgent.id;
                  }
                  setAgentForm(true);
                }}
              >
                {t("Agent 设置", "Agent settings")}
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
                  project
                    ? projectAgentForm
                    : agentForm && editingAgentID === null
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
                {t("添加 Agent", "Add agent")}
              </button>
            )}
          </div>
        </div>
      )}
      {!selectedAgent && (
        <div className={`stat-grid ${project ? "" : "workspace-stats"}`}>
          <Stat
            value={agents.length}
            label={t("Agent", "Agents")}
            icon="dock"
          />
          <Stat
            value={sessions.filter((s) => s.status === "running").length}
            label={t("运行中", "Running")}
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
              label={t("已审阅记忆", "Reviewed memories")}
              icon="memory"
            />
          )}
          <Stat
            value={approvals.length}
            label={t("等待授权", "Awaiting approval")}
            icon="shield"
          />
        </div>
      )}
      {agentForm && (
        <section className="panel inset-form" id="agent-form">
          <div className="panel-heading">
            <h2>
              {editingAgent
                ? t(
                    `编辑 Agent · ${editingAgent.name}`,
                    `Edit agent · ${editingAgent.name}`,
                  )
                : t("添加 Agent", "Add an agent")}
            </h2>
            <button
              className="icon-button"
              onClick={() => setAgentForm(false)}
              aria-label={
                editingAgent
                  ? t("取消编辑 Agent", "Cancel editing agent")
                  : t("取消添加 Agent", "Cancel adding agent")
              }
              disabled={busy && !demo}
            >
              <Icon name="close" />
            </button>
          </div>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (environment === NEW_SSH_CONNECTION) return;
              await mutate(
                editingAgentID
                  ? `/api/agents/${encodeURIComponent(editingAgentID)}`
                  : "/api/agents",
                editingAgentID
                  ? {
                      name: agentName.trim(),
                      role: role.trim(),
                      model: model || null,
                      effort: effort || null,
                      run_timeout: runTimeout ? Number(runTimeout) * 60 : null,
                      permission_mode: permissionMode,
                      ...(supportsAccounts(provider) &&
                      (state.accounts?.length ||
                        editingAgent?.account_policy ||
                        accountDraft.account_id ||
                        accountDraft.account_policy !== "manual")
                        ? accountSettings(accountDraft)
                        : {}),
                      environment_id: environment,
                      ...(!sessions.some(
                        (s) => s.agent_id === editingAgentID,
                      ) || changingEnvironment
                        ? {
                            project_id: agentProject || null,
                            workspace: workspace || null,
                          }
                        : {}),
                    }
                  : {
                      project_id: agentProject || null,
                      workspace: workspace || null,
                      model: model || null,
                      effort: effort || null,
                      run_timeout: runTimeout ? Number(runTimeout) * 60 : null,
                      permission_mode: permissionMode,
                      ...(supportsAccounts(provider) &&
                      (state.accounts?.length ||
                        editingAgent?.account_policy ||
                        accountDraft.account_id ||
                        accountDraft.account_policy !== "manual")
                        ? accountSettings(accountDraft)
                        : {}),
                      name: agentName.trim(),
                      provider,
                      environment_id: environment,
                      role: role.trim(),
                    },
                (result) => {
                  draftTarget.current = null;
                  setAgentID(result.id);
                  setAgentName("");
                  setRole("");
                  setEditingAgentID(null);
                  setAgentForm(false);
                },
              );
            }}
          >
            <label>
              {t("名称", "Name")}
              <input
                value={agentName}
                onChange={(e) => setAgentName(e.target.value)}
                required
                maxLength={100}
                placeholder={t(
                  "为这位 Agent 命名",
                  "Choose a name for this agent",
                )}
              />
            </label>
            <AgentConnection
              value={environment}
              draft={connectionDraft}
              onDraftChange={setConnectionDraft}
              locked={false}
              environments={state.environments ?? []}
              t={t}
              busy={busy && !demo}
              runtimeEnabled={runtimeEnabled && !demo}
              mutate={mutate}
              onChange={(id) => {
                setEnvironment(id);
                setAccountDraft(deviceAccount);
                const original =
                  editingAgent &&
                  id === (editingAgent.environment_id ?? "local")
                    ? editingAgent
                    : undefined;
                setWorkspace(
                  original?.workspace_is_default
                    ? ""
                    : (original?.workspace ?? ""),
                );
                setModel(original?.model ?? "");
                setEffort(original?.effort ?? "");
                setRunTimeout(original?.run_timeout ? String(original.run_timeout / 60) : "");
              }}
            >
              <WorkspaceDirectory
                key={environment}
                value={projectDirectory ?? workspace}
                onChange={setWorkspace}
                environment={environment}
                token={token}
                t={t}
                disabled={
                  !!projectDirectory ||
                  (!!editingAgentID &&
                    !changingEnvironment &&
                    sessions.some((s) => s.agent_id === editingAgentID)) ||
                  busy ||
                  demo
                }
                browseEnabled={
                  environment !== NEW_SSH_CONNECTION &&
                  (environment === "local" ||
                    (connectionReady && runtimeEnabled))
                }
              />
            </AgentConnection>
            <div className="form-grid">
              <ProviderSelect
                value={provider}
                onChange={(value) => {
                  setProvider(value);
                  setAccountDraft(deviceAccount);
                  setModel("");
                  setEffort("");
                }}
                disabled={!!editingAgentID}
                availability={discovery.providers}
                loading={discovery.loading}
                failed={discovery.failed}
                onRefresh={discovery.refresh}
                t={t}
              />
              <label>
                {t("模型", "Model")}
                <select
                  value={model}
                  onChange={(e) => {
                    setModel(e.target.value);
                    setEffort("");
                  }}
                >
                  <option value="">{t("CLI 默认", "CLI default")}</option>
                  {model && !models.some((m) => m.id === model) && (
                    <option value={model}>{model}</option>
                  )}
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name || m.id}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("思考强度", "Reasoning effort")}
                <select
                  value={effort}
                  disabled={!model}
                  onChange={(e) => setEffort(e.target.value)}
                >
                  <option value="">{t("自动", "Auto")}</option>
                  {effort &&
                    !models
                      .find((m) => m.id === model)
                      ?.efforts.includes(effort) && (
                      <option value={effort}>{effort}</option>
                    )}
                  {(models.find((m) => m.id === model)?.efforts ?? []).map(
                    (e) => (
                      <option key={e} value={e}>
                        {e}
                      </option>
                    ),
                  )}
                </select>
              </label>
              {editingAgent?.project_id && (
                <label>
                  {t("所属项目", "Project")}
                  <input readOnly value={selectedProject?.name ?? ""} />
                </label>
              )}
              <label>
                {t("最长执行时间（分钟）", "Execution time limit (minutes)")}
                <input type="number" min="1" max="1440" step="1"
                  placeholder={t("默认 15 分钟", "Default: 15 minutes")}
                  value={runTimeout} onChange={(event) => setRunTimeout(event.target.value)} />
              </label>
            </div>
            <p className="settings-note">
              {catalogLoading
                ? t(
                    "正在读取所选环境的模型…",
                    "Reading models from the selected environment…",
                  )
                : catalogError
                  ? t(
                      "模型列表暂不可用；可以保留客户端设置，稍后重新打开此面板。",
                      "Model list unavailable. Keep client settings and reopen this panel to retry.",
                    )
                  : t(
                      "模型与思考强度作为 Agent 默认设置，会话可单独覆盖。",
                      "Model and effort set agent defaults; conversations can override them.",
                    )}
            </p>
            <AccountSelection
              accounts={state.accounts ?? []}
              provider={provider}
              environment={environment}
              value={accountDraft}
              onChange={(value) => {
                setAccountDraft(value);
                setModel("");
                setEffort("");
              }}
              disabled={busy && !demo}
              t={t}
            />
            <label>
              {t("访问权限", "Access permissions")}
              <select
                value={permissionMode}
                aria-describedby="agent-permission-description"
                disabled={
                  !!editingAgentID &&
                  !changingEnvironment &&
                  state.runs?.some(
                    (run) =>
                      run.agent_id === editingAgentID &&
                      ["queued", "running"].includes(run.status),
                  )
                }
                onChange={(e) =>
                  setPermissionMode(e.target.value as PermissionMode)
                }
              >
                <option value="ask">
                  {t("需要确认（默认）", "Ask for approval (default)")}
                </option>
                <option value="full_access">
                  {t("完全访问", "Full access")}
                </option>
              </select>
            </label>
            {provider === "pi" && (
              <p className="settings-note">
                {t(
                  "Pi 的工具执行需要完全访问权限，请自行选择。",
                  "Pi tool execution requires full access. Select it explicitly to continue.",
                )}
              </p>
            )}
            <p className="form-hint" id="agent-permission-description">
              {permissionMode === "full_access"
                ? t(
                    "Agent 可在所选环境中读写文件、执行命令和联网，无需常规权限确认。系统账户和组织策略仍然有效。",
                    "The agent can read and write files, run commands and access the network in the selected environment without routine permission prompts. System account and organization policies still apply.",
                  )
                : t(
                    "需要授权的操作会在此等待你确认。",
                    "Operations that need approval wait for your confirmation here.",
                  )}
            </p>
            <label>
              {t("角色说明（可选）", "Role (optional)")}
              <textarea
                value={role}
                onChange={(e) => setRole(e.target.value)}
                rows={2}
                maxLength={4000}
                placeholder={t(
                  "填写职责、工作方式和边界；留空则按每次任务要求执行。",
                  "Describe responsibilities, working style and boundaries. Leave blank to follow each task.",
                )}
              />
            </label>
            <p className="form-hint">
              {t(
                "名称和角色由你定义。角色在后续执行时生效，不会清除已有会话历史。",
                "You define the name and role. Changes apply to future turns and do not clear existing conversation history.",
              )}
            </p>
            {editingAgentID && (
              <p className="form-hint">
                {t(
                  "更改运行位置后，新会话使用新位置；已有会话保留原位置、目录和设置，正在执行的任务不受影响。",
                  "Changing the runtime location applies to new conversations. Existing conversations keep their original location, directory and settings; active tasks continue unchanged.",
                )}
              </p>
            )}
            <button
              className="primary"
              disabled={
                busy ||
                !agentName.trim() ||
                environment === NEW_SSH_CONNECTION ||
                (!editingAgentID && !selectedAvailable) ||
                (provider === "pi" && permissionMode !== "full_access")
              }
            >
              {editingAgentID
                ? t("保存设置", "Save settings")
                : t("创建 Agent", "Create agent")}
            </button>
          </form>
        </section>
      )}
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
                        {
                          state.projects.find((p) => p.id === agent.project_id)
                            ?.name
                        }
                      </span>
                    )}
                    <p>
                      {agent.role ||
                        t(
                          "未设置角色 · 按任务要求执行",
                          "No role set · Follows each task",
                        )}
                    </p>
                    <span className="model-summary">
                      {agent.model ||
                        t("客户端默认模型", "Client default model")}
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
                        [
                          "ok",
                          "ready",
                          "available",
                          "success",
                          "exhausted",
                        ].includes(quota.status ?? "")
                          ? remainingPercent(
                              quota.windows?.[0]?.remaining_percent,
                            )
                          : null;
                      return (
                        <span className="agent-quota">
                          {t("当前额度", "Current usage")}:{" "}
                          {value === null
                            ? t("未知", "Unknown")
                            : `${value}% ${t("剩余", "left")}`}
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
                      ? t("运行中", "Running")
                      : t("待命", "Idle")}
                  </span>
                  <TPS
                    meter={metrics?.agents[agent.id]}
                    t={t}
                    compact
                    stale={metricsFailed}
                  />
                  <span className="agent-card-link">
                    {t("进入会话", "Open conversations")}{" "}
                    <span aria-hidden="true">→</span>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <section className="panel">
              <Empty
                icon="dock"
                title={t("添加第一位 Agent", "Add your first agent")}
              >
                {t(
                  "先创建 Agent，再建立会话并明确发起任务。",
                  "Create an agent, open a session, and explicitly start a task.",
                )}
              </Empty>
            </section>
          )}
        </>
      )}
      {selectedAgent && !agentForm && (
        <div className="workspace-grid">
          {!conversationOnly && (
            <section className="panel session-panel">
              <div className="panel-heading">
                <div>
                  <h2>{t("会话", "Sessions")}</h2>
                  <p>{selectedAgent?.name}</p>
                </div>
                <span className="count-badge">{relevantSessions.length}</span>
              </div>
              <div className="session-list">
                {relevantSessions.map((session) => (
                  <SessionListItem
                    key={session.id}
                    session={session}
                    state={state}
                    selected={session.id === sessionID}
                    className="session-item"
                    busy={busy}
                    mutate={mutate}
                    t={t}
                    onSelect={() => setSessionID(session.id)}
                    onDeleted={() => {
                      setPrompts((current) => {
                        const next = { ...current };
                        delete next[session.id];
                        return next;
                      });
                      setSessionSelections((current) =>
                        current[agentID] === session.id
                          ? { ...current, [agentID]: "" }
                          : current,
                      );
                    }}
                  >
                    <strong>{session.title}</strong>
                    <span>
                      {statusLabel(session.status, t)}
                      <span>·</span>
                      <DateText date={session.updated_at} lang={lang} />
                    </span>
                  </SessionListItem>
                ))}
                {!relevantSessions.length && (
                  <p className="muted small-text">
                    {t(
                      "尚无会话。为这位 Agent 创建一个任务。",
                      "No sessions yet. Create a task for this agent.",
                    )}
                  </p>
                )}
              </div>
              <form
                className="session-create"
                onSubmit={async (e) => {
                  e.preventDefault();
                  await mutate(
                    "/api/sessions",
                    { agent_id: agentID, title: sessionTitle.trim() },
                    (result) => {
                      setSessionID(result.id);
                      setSessionTitle("");
                    },
                  );
                }}
              >
                <label htmlFor="session-title">
                  {t("新会话标题", "New session title")}
                </label>
                <input
                  id="session-title"
                  value={sessionTitle}
                  onChange={(e) => setSessionTitle(e.target.value)}
                  required
                  maxLength={160}
                  placeholder={t(
                    "例如：审阅登录流程",
                    "For example: Review sign-in",
                  )}
                />
                <button
                  className="secondary full"
                  disabled={busy || !sessionTitle.trim()}
                >
                  <Icon name="plus" size={16} />
                  {t("创建会话", "Create session")}
                </button>
              </form>
            </section>
          )}
          <section className="panel conversation-panel">
            <div className="panel-heading">
              <div>
                <h2>
                  {selectedSession?.title ||
                    t("选择一个会话", "Select a session")}
                </h2>
              </div>
              {selectedSession && (
                <span className={`pill ${running ? "live" : ""}`}>
                  <span className={`status-dot ${running ? "" : "idle"}`} />
                  {statusLabel(selectedSession.status, t)}
                </span>
              )}
            </div>
            {selectedSession ? (
              <>
                <div
                  className="event-feed"
                  aria-label={t("会话事件", "Session events")}
                  aria-busy={eventLoading}
                >
                  {eventError && (
                    <p className="inline-error" role="status">
                      {eventError}
                    </p>
                  )}
                  {eventLoading && !events.length ? (
                    <p className="muted">
                      {t("正在读取事件…", "Loading events…")}
                    </p>
                  ) : !events.length && !sessionRuns.length ? (
                    <Empty
                      icon="message"
                      title={t(
                        "这个会话还没有记录",
                        "This session has no events yet",
                      )}
                    >
                      {t(
                        "发送第一条消息，开始对话。",
                        "Send your first message to start a conversation.",
                      )}
                    </Empty>
                  ) : (
                    <TaskTimeline
                      runs={sessionRuns}
                      events={events}
                      agentName={selectedAgent?.name ?? "Agent"}
                      accounts={state.accounts}
                      accountAttempts={state.account_attempts}
                      onConfigureAccount={() =>
                        setAccountSelectionRequest((value) => value + 1)
                      }
                      t={t}
                      lang={lang}
                      busy={busy}
                      mutate={mutate}
                    />
                  )}
                </div>
                {approvals
                  .filter((a) => a.session_id === sessionID)
                  .map((approval) => (
                    <ApprovalCard
                      key={approval.id}
                      approval={approval}
                      busy={busy}
                      mutate={mutate}
                      t={t}
                    />
                  ))}
                <form
                  className="prompt-form"
                  onSubmit={async (e) => {
                    e.preventDefault();
                    if (
                      submittingPrompt.current ||
                      busy ||
                      !runtimeEnabled ||
                      demo ||
                      !prompt.trim()
                    )
                      return;
                    submittingPrompt.current = true;
                    try {
                      await mutate(
                        `/api/sessions/${encodeURIComponent(sessionID)}/run`,
                        { prompt: prompt.trim() },
                        () => setPrompt(""),
                      );
                    } finally {
                      submittingPrompt.current = false;
                    }
                  }}
                >
                  <label htmlFor="run-prompt">
                    {t("给 Agent 的任务", "Task for this agent")}
                  </label>
                  <textarea
                    id="run-prompt"
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    onCompositionStart={() => {
                      composingPrompt.current = true;
                    }}
                    onCompositionEnd={() => {
                      composingPrompt.current = false;
                    }}
                    onKeyDown={(e) => {
                      if (
                        e.key !== "Enter" ||
                        e.shiftKey ||
                        e.altKey ||
                        e.ctrlKey ||
                        e.metaKey ||
                        composingPrompt.current ||
                        e.nativeEvent.isComposing ||
                        e.nativeEvent.keyCode === 229
                      )
                        return;
                      e.preventDefault();
                      if (
                        !e.repeat &&
                        !busy &&
                        runtimeEnabled &&
                        !demo &&
                        prompt.trim() &&
                        !submittingPrompt.current
                      )
                        e.currentTarget.form?.requestSubmit();
                    }}
                    rows={3}
                    required
                    maxLength={24000}
                    disabled={busy}
                    placeholder={t(
                      "描述目标、约束和你希望得到的结果…",
                      "Describe the goal, constraints and expected outcome…",
                    )}
                  />
                  {selectedAgent && selectedSession && (
                    <SessionAccountControls
                      key={`account-${sessionID}`}
                      openRequest={accountSelectionRequest}
                      accounts={state.accounts ?? []}
                      agent={selectedAgent}
                      session={selectedSession}
                      busy={busy || hasSessionTasks}
                      demo={demo}
                      mutate={mutate}
                      t={t}
                    />
                  )}
                  <div className="prompt-footer">
                    {selectedAgent && selectedSession && (
                      <InferenceControls
                        key={sessionID}
                        agent={selectedAgent}
                        session={selectedSession}
                        token={token}
                        accountGeneration={
                          state.accounts?.find(
                            (account) =>
                              account.id === selectedSession.account_id,
                          )?.generation
                        }
                        busy={busy}
                        runtimeEnabled={runtimeEnabled}
                        demo={demo}
                        mutate={mutate}
                        t={t}
                      />
                    )}
                    <div className="button-row">
                      {hasSessionTasks && (
                        <button
                          className="secondary"
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            void mutate(
                              `/api/sessions/${encodeURIComponent(sessionID)}/cancel`,
                              {},
                            )
                          }
                        >
                          {t("取消会话任务", "Cancel session tasks")}
                        </button>
                      )}
                      <button
                        className="primary"
                        disabled={busy || !runtimeEnabled || !prompt.trim()}
                        title={t(
                          "Enter 发送，Shift + Enter 换行",
                          "Enter to send, Shift + Enter for a new line",
                        )}
                        aria-keyshortcuts="Enter"
                      >
                        <Icon name="arrow" size={17} />
                        {running
                          ? t("加入队列", "Queue task")
                          : t("运行任务", "Run task")}
                      </button>
                    </div>
                  </div>
                </form>
              </>
            ) : (
              <Empty
                icon="work"
                title={t("创建会话后开始协作", "Create a session to begin")}
              >
                {t(
                  "会话保留执行事件。创建会话本身不会启动 Agent。",
                  "Sessions preserve execution events. Creating one does not start an agent.",
                )}
              </Empty>
            )}
          </section>
        </div>
      )}
      {approvals.some(
        (a) =>
          a.session_id !== sessionID &&
          (!selectedAgent ||
            relevantSessions.some((s) => s.id === a.session_id)),
      ) && (
        <section className="panel inset-form">
          <h2>{t("其他会话等待授权", "Approvals in other sessions")}</h2>
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
