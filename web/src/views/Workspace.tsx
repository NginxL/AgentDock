import { useEffect, useRef, useState } from "react";
import TaskTimeline from "../TaskTimeline";
import { TPS, type Metrics } from "../metrics";
import { listOf, remainingPercent, request } from "../api";
import type {
  Agent,
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
  initialEnvironment,
  onInitialEnvironmentUsed,
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
  initialEnvironment?: string;
  onInitialEnvironmentUsed?: () => void;
}) {
  const [agentForm, setAgentForm] = useState(initialEnvironment !== undefined);
  const draftTarget = useRef<string | null>(
    initialEnvironment !== undefined ? "new" : null,
  );
  const [editingAgentID, setEditingAgentID] = useState<string | null>(null);
  const [agentName, setAgentName] = useState("");
  const [provider, setProvider] = useState<Provider>("codex");
  const [environment, setEnvironment] = useState(
    initialEnvironment ?? project?.environment_id ?? "local",
  );
  useEffect(() => {
    if (initialEnvironment !== undefined) onInitialEnvironmentUsed?.();
  }, [initialEnvironment, onInitialEnvironmentUsed]);
  const environmentName = (id?: string) =>
    !id || id === "local"
      ? t("本机", "This Mac")
      : (state.environments?.find((e) => e.id === id)?.name ?? id);
  const [role, setRole] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [agentProject, setAgentProject] = useState(project?.id ?? "");
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [permissionMode, setPermissionMode] = useState<PermissionMode>("ask");
  const [models, setModels] = useState<
    { id: string; name: string; efforts: string[] }[]
  >([]);
  const [catalogError, setCatalogError] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(false);
  useEffect(() => {
    if (!agentForm) return;
    setModels([]);
    setCatalogError(false);
    if (demo) {
      setModels([
        {
          id: "demo-model",
          name: "Demo model",
          efforts: ["low", "medium", "high"],
        },
      ]);
      return;
    }
    if (!runtimeEnabled) return;
    const abort = new AbortController();
    setCatalogLoading(true);
    void request<{ models: { id: string; name: string; efforts: string[] }[] }>(
      token,
      `/api/models/${provider}?environment_id=${encodeURIComponent(environment)}`,
      undefined,
      abort.signal,
    )
      .then((r) => {
        if (!abort.signal.aborted)
          setModels(Array.isArray(r.models) ? r.models : []);
      })
      .catch(() => {
        if (!abort.signal.aborted) setCatalogError(true);
      })
      .finally(() => {
        if (!abort.signal.aborted) setCatalogLoading(false);
      });
    return () => abort.abort();
  }, [agentForm, provider, environment, token, demo, runtimeEnabled]);
  const [agentID, setAgentID] = useState(agents[0]?.id ?? "");
  const [sessionID, setSessionID] = useState("");
  const [sessionTitle, setSessionTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [eventError, setEventError] = useState("");
  const [eventLoading, setEventLoading] = useState(false);
  const lastSeq = useRef(0);
  const relevantSessions = sessions.filter((s) => s.agent_id === agentID);
  const selectedSession = relevantSessions.find((s) => s.id === sessionID);
  const selectedAgent = agents.find((a) => a.id === agentID);
  const editingAgent = agents.find((a) => a.id === editingAgentID);
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
    if (!agents.some((a) => a.id === agentID)) setAgentID(agents[0]?.id ?? "");
  }, [agents, agentID]);
  useEffect(() => {
    if (!relevantSessions.some((s) => s.id === sessionID))
      setSessionID(relevantSessions[0]?.id ?? "");
  }, [relevantSessions, sessionID]);
  useEffect(() => {
    setEvents([]);
    setEventError("");
    lastSeq.current = 0;
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
    let pending = false;
    setEventLoading(true);
    async function poll() {
      if (pending) return;
      pending = true;
      try {
        for (let page = 0; page < 10; page++) {
          const result = await request<{ events: AgentEvent[] }>(
            token,
            `/api/sessions/${encodeURIComponent(sessionID)}/events?after=${lastSeq.current}`,
            undefined,
            controller.signal,
          );
          if (controller.signal.aborted) return;
          if (!Array.isArray(result.events))
            throw new Error("Invalid event list");
          if (result.events.length) {
            lastSeq.current = Math.max(
              lastSeq.current,
              ...result.events.map((event) => event.seq),
            );
            setEvents((previous) => {
              const seen = new Set(previous.map((event) => event.id));
              return [
                ...previous,
                ...result.events.filter((event) => !seen.has(event.id)),
              ];
            });
          }
          if (result.events.length < 500) break;
        }
        setEventError("");
      } catch {
        if (!controller.signal.aborted)
          setEventError(
            lang === "zh"
              ? "事件读取失败，正在重试。"
              : "Could not load events. Retrying.",
          );
      } finally {
        pending = false;
        if (!controller.signal.aborted) setEventLoading(false);
      }
    }
    void poll();
    const interval = window.setInterval(() => {
      if (document.visibilityState !== "hidden") void poll();
    }, 1000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [sessionID, token, lang, demo, demo ? state.events : null]);

  return (
    <>
      <div className="page-heading">
        <div>
          <h1>{t("协作工作台", "Workspace")}</h1>
          <p
            className="path-line"
            title={project?.path ?? selectedAgent?.workspace}
          >
            {project?.path ??
              selectedAgent?.workspace ??
              t(
                "无需项目，连接本机或 SSH Agent 开始对话",
                "Chat with a local or SSH agent — no project required",
              )}
          </p>
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
                  setWorkspace(selectedAgent.workspace ?? "");
                  setAgentProject(selectedAgent.project_id ?? "");
                  setModel(selectedAgent.model ?? "");
                  setEffort(selectedAgent.effort ?? "");
                  setPermissionMode(selectedAgent.permission_mode ?? "ask");
                  draftTarget.current = selectedAgent.id;
                }
                setAgentForm(true);
              }}
            >
              {t("Agent 设置", "Agent settings")}
            </button>
          )}
          <button
            className="primary"
            disabled={busy && !demo}
            aria-expanded={agentForm && editingAgentID === null}
            aria-controls="agent-form"
            onClick={() => {
              if (agentForm && editingAgentID === null) {
                setAgentForm(false);
                return;
              }
              if (draftTarget.current !== "new") {
                setEditingAgentID(null);
                setAgentName("");
                setProvider("codex");
                setEnvironment(project?.environment_id ?? "local");
                setRole("");
                setWorkspace("");
                setAgentProject(project?.id ?? "");
                setModel("");
                setEffort("");
                setPermissionMode("ask");
                draftTarget.current = "new";
              }
              setAgentForm(true);
            }}
          >
            <Icon name="plus" size={18} />
            {t("添加 Agent", "Add agent")}
          </button>
        </div>
      </div>
      <div className="stat-grid">
        <Stat value={agents.length} label={t("Agent", "Agents")} icon="dock" />
        <Stat
          value={sessions.filter((s) => s.status === "running").length}
          label={t("运行中", "Running")}
          icon="bolt"
        />
        <Stat
          value={
            state.memories.filter(
              (m) => !!project && m.project_id === project.id && !isArchived(m),
            ).length
          }
          label={t("已审阅记忆", "Reviewed memories")}
          icon="memory"
        />
        <Stat
          value={approvals.length}
          label={t("等待授权", "Awaiting approval")}
          icon="shield"
        />
      </div>
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
                      permission_mode: permissionMode,
                      ...(!sessions.some((s) => s.agent_id === editingAgentID)
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
                      permission_mode: permissionMode,
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
            <div className="form-grid">
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
              <label>
                {t("服务", "Provider")}
                <select
                  value={provider}
                  onChange={(e) => {
                    setProvider(e.target.value as Provider);
                    setModel("");
                    setEffort("");
                  }}
                  disabled={!!editingAgentID}
                >
                  <option value="codex">Codex</option>
                  <option value="claude">Claude</option>
                </select>
              </label>
            </div>
            <label>
              {t("运行位置", "Run on")}
              <select
                value={environment}
                disabled={!!editingAgentID}
                onChange={(e) => {
                  setEnvironment(e.target.value);
                  setWorkspace("");
                  setModel("");
                  setEffort("");
                }}
              >
                <option value="local">{t("本机", "This Mac")}</option>
                {(state.environments ?? [])
                  .filter((e) => e.kind === "ssh")
                  .map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name} · SSH
                    </option>
                  ))}
              </select>
            </label>
            {!editingAgentID && (
              <p className="form-hint">
                {t(
                  "使用所选设备上的 CLI 与登录状态。新设备可在「设备与连接」中添加，同一设备可运行多个 Agent。",
                  "Uses the CLI and login on this device. Add devices in Devices & connections; each device can run multiple agents.",
                )}
              </p>
            )}
            <div className="form-grid">
              <label>
                {t("关联项目（可选）", "Project (optional)")}
                <select
                  value={agentProject}
                  disabled={
                    !!editingAgentID &&
                    sessions.some((s) => s.agent_id === editingAgentID)
                  }
                  onChange={(e) => setAgentProject(e.target.value)}
                >
                  <option value="">
                    {t("独立 Agent", "Independent agent")}
                  </option>
                  {state.projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              {(!agentProject ||
                (state.projects.find((p) => p.id === agentProject)
                  ?.environment_id ?? "local") !== environment) && (
                <label>
                  {t("工作目录（可留空）", "Working directory (optional)")}
                  <input
                    value={workspace}
                    disabled={
                      !!editingAgentID &&
                      sessions.some((s) => s.agent_id === editingAgentID)
                    }
                    onChange={(e) => setWorkspace(e.target.value)}
                    placeholder={t(
                      "留空自动创建独立目录",
                      "Leave blank for a private directory",
                    )}
                  />
                </label>
              )}
              <label>
                {t("模型", "Model")}
                <select
                  value={model}
                  onChange={(e) => {
                    setModel(e.target.value);
                    setEffort("");
                  }}
                >
                  <option value="">
                    {t(
                      "沿用客户端 / 会话设置",
                      "Use client / session settings",
                    )}
                  </option>
                  {model && !models.some((m) => m.id === model) && (
                    <option value={model}>{model}</option>
                  )}
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.id}
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
                  <option value="">
                    {t(
                      "沿用客户端 / 会话设置",
                      "Use client / session settings",
                    )}
                  </option>
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
                      "模型、思考强度与访问权限对后续消息生效。已有会话保持上下文；建立会话后，工作目录及项目固定。",
                      "Model, effort and permissions apply to future messages. Conversations keep their context; workspace and project stay fixed once a conversation exists.",
                    )}
            </p>
            <label>
              {t("访问权限", "Access permissions")}
              <select
                value={permissionMode}
                aria-describedby="agent-permission-description"
                disabled={
                  !!editingAgentID &&
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
                "名称和角色由你定义，与 Codex / Claude 服务无关。角色在后续执行时生效，不会清除已有原生会话历史。",
                "You define the name and role independently of Codex / Claude. Changes apply to future turns and do not clear existing native conversation history.",
              )}
            </p>
            {editingAgentID && (
              <p className="form-hint">
                {t(
                  "运行位置与服务保持不变，以保留已有会话绑定。需要更换时，请添加新的 Agent。",
                  "The device and provider stay unchanged to preserve session bindings. Add a new agent to use another device or provider.",
                )}
              </p>
            )}
            <button className="primary" disabled={busy || !agentName.trim()}>
              {editingAgentID
                ? t("保存设置", "Save settings")
                : t("创建 Agent", "Create agent")}
            </button>
          </form>
        </section>
      )}
      {!!agents.length && (
        <section className="panel workspace-tps">
          <TPS meter={metrics?.total} t={t} stale={metricsFailed} />
        </section>
      )}
      {agents.length ? (
        <div className="agent-grid">
          {agents.map((agent) => (
            <button
              className={`agent-card ${agentID === agent.id ? "active" : ""}`}
              key={agent.id}
              onClick={() => {
                setAgentID(agent.id);
                setPrompt("");
              }}
              aria-pressed={agentID === agent.id}
            >
              <div className={`provider-symbol ${agent.provider}`}>
                {agent.provider === "codex" ? "C" : "✳"}
              </div>
              <div className="agent-info">
                <strong>{agent.name}</strong>
                <span>
                  {agent.provider === "codex" ? "Codex" : "Claude"} ·{" "}
                  {environmentName(agent.environment_id)}
                </span>
                <p>
                  {agent.role ||
                    t(
                      "未设置角色 · 按任务要求执行",
                      "No role set · Follows each task",
                    )}
                </p>
                <span className="model-summary">
                  {agent.model || t("客户端默认模型", "Client default model")}
                  {agent.effort ? ` · ${agent.effort}` : ""}
                </span>
                {(() => {
                  const quota = listOf(state.quotas).find(
                    (q) =>
                      q.provider === agent.provider &&
                      (q.environment_id ?? "local") ===
                        (agent.environment_id ?? "local"),
                  );
                  const value =
                    quota &&
                    ["ok", "available", "success"].includes(quota.status)
                      ? remainingPercent(quota.windows[0]?.remaining_percent)
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
      {!!agents.length && (
        <div className="workspace-grid">
          <section className="panel session-panel">
            <div className="panel-heading">
              <div>
                <h2>{t("会话", "Sessions")}</h2>
                <p>
                  {selectedAgent?.name} ·{" "}
                  {environmentName(selectedAgent?.environment_id)}
                </p>
              </div>
              <span className="count-badge">{relevantSessions.length}</span>
            </div>
            <div className="session-list">
              {relevantSessions.map((session) => (
                <button
                  key={session.id}
                  className={`session-item ${session.id === sessionID ? "active" : ""}`}
                  onClick={() => {
                    setSessionID(session.id);
                    setPrompt("");
                  }}
                >
                  <strong>{session.title}</strong>
                  <span>
                    {statusLabel(session.status, t)}
                    <span>·</span>
                    <DateText date={session.updated_at} lang={lang} />
                  </span>
                </button>
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
                    await mutate(
                      `/api/sessions/${encodeURIComponent(sessionID)}/run`,
                      { prompt: prompt.trim() },
                      () => setPrompt(""),
                    );
                  }}
                >
                  <label htmlFor="run-prompt">
                    {t("给 Agent 的任务", "Task for this agent")}
                  </label>
                  <textarea
                    id="run-prompt"
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    rows={3}
                    required
                    maxLength={24000}
                    disabled={busy}
                    placeholder={t(
                      "描述目标、约束和你希望得到的结果…",
                      "Describe the goal, constraints and expected outcome…",
                    )}
                  />
                  <div className="prompt-footer">
                    <span>
                      {runtimeEnabled
                        ? t(
                            "执行可能修改所选工作目录中的文件。",
                            "Execution may change files in this workspace.",
                          )
                        : t(
                            "服务尚未启用执行。",
                            "Execution is disabled on the service.",
                          )}
                    </span>
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
      {approvals.some((a) => a.session_id !== sessionID) && (
        <section className="panel inset-form">
          <h2>{t("其他会话等待授权", "Approvals in other sessions")}</h2>
          {approvals
            .filter((a) => a.session_id !== sessionID)
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
    </>
  );
}
