import { useEffect, useRef, useState } from "react";
import { listOf, remainingPercent, request } from "../api";
import type {
  Agent,
  AgentEvent,
  Approval,
  DockState,
  Language,
  Mutate,
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
  conversationEvents,
  eventDescription,
  eventLabel,
  isArchived,
  statusLabel,
} from "../ui";

export default function Workspace({
  t,
  lang,
  project,
  agents,
  sessions,
  approvals,
  state,
  token,
  demo = false,
  runtimeEnabled,
  busy,
  mutate,
}: {
  t: Translate;
  lang: Language;
  project: Project;
  agents: Agent[];
  sessions: Session[];
  approvals: Approval[];
  state: DockState;
  token: string;
  demo?: boolean;
  runtimeEnabled: boolean;
  busy: boolean;
  mutate: Mutate;
}) {
  const [agentForm, setAgentForm] = useState(false);
  const [agentName, setAgentName] = useState("");
  const [provider, setProvider] = useState<Provider>("codex");
  const [role, setRole] = useState("");
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
  const running = selectedSession?.status === "running";
  const sessionRuns = (state.runs ?? []).filter(
    (run) => run.session_id === sessionID,
  );
  const queued = sessionRuns.filter((run) => run.status === "queued");
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
        const result = await request<{ events: AgentEvent[] }>(
          token,
          `/api/sessions/${encodeURIComponent(sessionID)}/events?after=${lastSeq.current}`,
          undefined,
          controller.signal,
        );
        if (controller.signal.aborted) return;
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
            ].slice(-500);
          });
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
    }, 2000);
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
          <p className="path-line" title={project.path}>
            {project.path}
          </p>
        </div>
        <button className="primary" onClick={() => setAgentForm(!agentForm)}>
          <Icon name="plus" size={18} />
          {t("添加 Agent", "Add agent")}
        </button>
      </div>
      <div className="stat-grid">
        <Stat
          value={agents.length}
          label={t("项目 Agent", "Project agents")}
          icon="dock"
        />
        <Stat
          value={sessions.filter((s) => s.status === "running").length}
          label={t("运行中", "Running")}
          icon="bolt"
        />
        <Stat
          value={
            state.memories.filter(
              (m) => m.project_id === project.id && !isArchived(m),
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
        <section className="panel inset-form">
          <div className="panel-heading">
            <h2>{t("添加项目 Agent", "Add a project agent")}</h2>
            <button
              className="icon-button"
              onClick={() => setAgentForm(false)}
              aria-label={t("取消添加 Agent", "Cancel adding agent")}
            >
              <Icon name="close" />
            </button>
          </div>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              await mutate(
                "/api/agents",
                {
                  project_id: project.id,
                  name: agentName.trim(),
                  provider,
                  role: role.trim(),
                },
                (result) => {
                  setAgentID(result.id);
                  setAgentName("");
                  setRole("");
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
                    "例如：代码审阅员",
                    "For example: Code reviewer",
                  )}
                />
              </label>
              <label>
                {t("服务", "Provider")}
                <select
                  value={provider}
                  onChange={(e) => setProvider(e.target.value as Provider)}
                >
                  <option value="codex">Codex</option>
                  <option value="claude">Claude</option>
                </select>
              </label>
            </div>
            <label>
              {t("角色说明", "Role")}
              <textarea
                value={role}
                onChange={(e) => setRole(e.target.value)}
                rows={2}
                maxLength={4000}
                placeholder={t(
                  "说明此 Agent 的职责和边界",
                  "Describe this agent’s responsibilities and boundaries",
                )}
              />
            </label>
            <p className="form-hint">
              {t(
                "使用服务端配置的本机 Codex / Claude CLI 与其登录凭据。各 Agent 的原生会话独立保留上下文。",
                "Uses server-configured local Codex / Claude CLIs and their credentials. Each agent’s native sessions retain their own context.",
              )}
            </p>
            <button className="primary" disabled={busy || !agentName.trim()}>
              {t("创建 Agent", "Create agent")}
            </button>
          </form>
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
                  {t("原生会话", "Native session")}
                </span>
                <p>
                  {agent.role || t("未设置角色说明", "No role description")}
                </p>
                {(() => {
                  const quota = listOf(state.quotas).find(
                    (q) => q.provider === agent.provider,
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
            </button>
          ))}
        </div>
      ) : (
        <section className="panel">
          <Empty
            icon="dock"
            title={t("为项目分配第一位 Agent", "Add your first agent")}
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
                <p>{selectedAgent?.name}</p>
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
                <p>
                  {t(
                    "原生上下文独立保留 · 项目记忆按审阅结果共享",
                    "Private native context · Reviewed project memory is shared",
                  )}
                </p>
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
                <div className="session-context">
                  <Icon name="shield" size={14} />
                  <span>{t("原生会话", "Native session")}</span>
                  <code title={selectedSession.native_session_id ?? ""}>
                    {selectedSession.native_session_id
                      ? selectedSession.native_session_id
                      : t("首次执行后建立", "Created on first run")}
                  </code>
                  <span className="private-label">
                    {t("私有上下文", "Private context")}
                  </span>
                </div>
                {!!sessionRuns.length && (
                  <details className="run-history">
                    <summary>
                      {t("执行记录", "Run history")}{" "}
                      <span className="count-badge">{sessionRuns.length}</span>
                      <span className="muted">
                        {queued.length
                          ? t(
                              `${queued.length} 项排队中`,
                              `${queued.length} queued`,
                            )
                          : t("查看任务与派工状态", "Task and dispatch status")}
                      </span>
                    </summary>
                    <div className="run-list">
                      {sessionRuns
                        .slice()
                        .reverse()
                        .map((run) => (
                          <article className="run-row" key={run.id}>
                            <span className={`state-indicator ${run.status}`} />
                            <div>
                              <strong>{run.prompt}</strong>
                              <small>
                                {run.origin === "delegate"
                                  ? t("Agent 派工", "Agent delegation")
                                  : run.origin === "reply"
                                    ? t("协作结果回传", "Collaboration result")
                                    : t("你发起的任务", "Your task")}{" "}
                                · <DateText date={run.created_at} lang={lang} />
                              </small>
                              {run.error && (
                                <p className="inline-error">{run.error}</p>
                              )}
                            </div>
                            <span className="pill">
                              {statusLabel(run.status, t)}
                            </span>
                            {["queued", "running"].includes(run.status) && (
                              <button
                                type="button"
                                className="text-button"
                                disabled={busy}
                                onClick={() =>
                                  void mutate(
                                    `/api/runs/${encodeURIComponent(run.id)}/cancel`,
                                    {},
                                  )
                                }
                              >
                                {t("取消", "Cancel")}
                              </button>
                            )}
                          </article>
                        ))}
                    </div>
                  </details>
                )}
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
                  ) : !events.length ? (
                    <Empty
                      icon="message"
                      title={t(
                        "这个会话还没有记录",
                        "This session has no events yet",
                      )}
                    >
                      {t(
                        "输入任务并点击运行。后续任务会延续此原生会话，已审阅的项目记忆作为共享上下文。",
                        "Enter a task and click Run. Follow-up tasks continue this native session with reviewed project memory as shared context.",
                      )}
                    </Empty>
                  ) : (
                    conversationEvents(events).map((event) => (
                      <article
                        key={event.id}
                        className={`event ${event.kind.includes("error") ? "event-error" : ""}`}
                      >
                        <div className="event-meta">
                          <span title={event.kind}>
                            {eventLabel(event.kind, t)}
                          </span>
                          <DateText date={event.created_at} lang={lang} />
                        </div>
                        <pre>{eventDescription(event, t)}</pre>
                      </article>
                    ))
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
