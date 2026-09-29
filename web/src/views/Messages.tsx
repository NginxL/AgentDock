import { providerNames } from "../ProviderIcon";
import { useEffect, useRef, useState } from "react";
import type { Agent, DockState, Language, Mutate, Translate } from "../types";
import { DateText, Empty, Icon, PageTitle, statusLabel } from "../ui";

export default function Messages({
  t,
  lang,
  state,
  projectID,
  agents,
  busy,
  mutate,
}: {
  t: Translate;
  lang: Language;
  state: DockState;
  projectID: string;
  agents: Agent[];
  busy: boolean;
  mutate: Mutate;
}) {
  const [recipient, setRecipient] = useState(agents[0]?.id ?? "");
  const [targetSession, setTargetSession] = useState("");
  const [filter, setFilter] = useState("all");
  const [body, setBody] = useState("");
  const [reference, setReference] = useState("");
  const requestKey = useRef<string | null>(null);
  const sessions = state.sessions.filter(
    (s) => s.project_id === projectID && s.agent_id === recipient,
  );
  useEffect(() => {
    if (!agents.some((a) => a.id === recipient))
      setRecipient(agents[0]?.id ?? "");
  }, [agents, recipient]);
  useEffect(() => {
    if (targetSession && !sessions.some((s) => s.id === targetSession))
      setTargetSession("");
  }, [sessions, targetSession]);
  const messages = state.messages
    .filter(
      (m) =>
        m.project_id === projectID &&
        (filter === "all" || m.recipient_id === filter),
    )
    .slice()
    .reverse();
  const name = (id: string) =>
    id === "human"
      ? t("你", "You")
      : (agents.find((a) => a.id === id)?.name ??
        t("已移除的 Agent", "Removed agent"));
  const enabled = state.runtime.enabled;
  return (
    <>
      <PageTitle
        headingLevel={2}
        eyebrow=""
        title={t("任务派工", "Dispatch")}
        description={t(
          "将任务提交给目标 Agent 的原生会话，跟踪执行与结果回传。忙碌的会话会按顺序处理后续任务。",
          "Submit work to an agent’s native session and follow execution and returned results. Busy sessions process subsequent tasks in order.",
        )}
      />
      <div className="two-column">
        <section className="panel">
          <div className="panel-heading">
            <h2>
              {t("派工记录", "Dispatch activity")}{" "}
              <span className="count-badge">{messages.length}</span>
            </h2>
            <label className="compact-select">
              <span className="sr-only">
                {t("按目标 Agent 筛选", "Filter by target agent")}
              </span>
              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                <option value="all">{t("所有 Agent", "All agents")}</option>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {messages.length ? (
            <div className="message-list">
              {messages.map((message) => {
                const session = state.sessions.find(
                  (s) => s.id === message.recipient_session_id,
                );
                const run = (state.runs ?? []).find(
                  (r) => r.id === message.run_id,
                );
                const replyRun = (state.runs ?? []).find(
                  (r) => r.id === message.reply_run_id,
                );
                const status = message.status ?? run?.status ?? "pending";
                const cancellationRunID =
                  replyRun && ["queued", "running"].includes(replyRun.status)
                    ? replyRun.id
                    : message.run_id &&
                        (["queued", "running", "waiting"].includes(status) ||
                          (run && ["queued", "running"].includes(run.status)))
                      ? message.run_id
                      : undefined;
                return (
                  <article className="message-card" key={message.id}>
                    <header>
                      <strong>
                        <span className={`state-indicator ${status}`} />
                        {name(message.sender_id)}
                        <Icon name="arrow" size={14} />
                        {name(message.recipient_id)}
                      </strong>
                      <span
                        className={`pill ${status === "completed" ? "good" : ""}`}
                      >
                        {statusLabel(status, t)}
                      </span>
                    </header>
                    <p>{message.body}</p>
                    <div className="delivery-target">
                      <Icon name="work" size={14} />
                      <span>
                        {t("目标会话", "Target session")}:{" "}
                        {session?.title ?? t("尚未分配", "Not assigned yet")}
                      </span>
                    </div>
                    {session?.native_session_id && (
                      <code className="delivery-native">
                        {session.native_session_id}
                      </code>
                    )}
                    {message.result && (
                      <div className="delivery-result">
                        <strong>
                          {status === "waiting"
                            ? t("当前进展", "Progress so far")
                            : t("执行结果", "Result")}
                        </strong>
                        <pre>{message.result}</pre>
                      </div>
                    )}
                    {(message.error || run?.error) && (
                      <p className="inline-error">
                        {message.error || run?.error}
                      </p>
                    )}
                    {replyRun && (
                      <p className="form-hint">
                        {t("回传任务", "Return task")}:{" "}
                        {statusLabel(replyRun.status, t)}
                        {replyRun.error && ` · ${replyRun.error}`}
                      </p>
                    )}
                    <footer>
                      <DateText date={message.created_at} lang={lang} />
                      {message.correlation_id && (
                        <span>
                          {t("关联", "Reference")}: {message.correlation_id}
                        </span>
                      )}
                      {cancellationRunID && (
                        <button
                          className="text-button"
                          disabled={busy}
                          onClick={() =>
                            void mutate(
                              `/api/runs/${encodeURIComponent(cancellationRunID)}/cancel`,
                              {},
                            )
                          }
                        >
                          {t("取消任务", "Cancel task")}
                        </button>
                      )}
                    </footer>
                  </article>
                );
              })}
            </div>
          ) : (
            <Empty
              icon="message"
              title={t("尚无派工记录", "No dispatched tasks")}
            >
              {t(
                "选择 Agent 和目标会话，说明目标与完成标准。发送后由服务派发执行，结果保留在这里。",
                "Choose an agent and session, then describe the goal and completion criteria. Sending dispatches the work; results appear here.",
              )}
            </Empty>
          )}
        </section>
        <section className="panel inset-form sticky-panel">
          <span className="eyebrow">{t("新建派工", "NEW DISPATCH")}</span>
          <h2>{t("交给 Agent 处理", "Delegate a task")}</h2>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (!enabled || busy) return;
              requestKey.current ??= crypto.randomUUID();
              await mutate(
                "/api/messages",
                {
                  project_id: projectID,
                  recipient_id: recipient,
                  body: body.trim(),
                  ...(targetSession
                    ? { recipient_session_id: targetSession }
                    : {}),
                  ...(reference.trim()
                    ? { correlation_id: reference.trim() }
                    : {}),
                  idempotency_key: requestKey.current,
                },
                () => {
                  setBody("");
                  setReference("");
                  requestKey.current = null;
                },
              );
            }}
          >
            <label>
              {t("目标 Agent", "Target agent")}
              <select
                value={recipient}
                onChange={(e) => {
                  setRecipient(e.target.value);
                  setTargetSession("");
                  requestKey.current = null;
                }}
                required
              >
                {!agents.length && (
                  <option value="">
                    {t("先添加 Agent", "Add an agent first")}
                  </option>
                )}
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} · {providerNames[a.provider]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("目标会话", "Target session")}
              <select
                value={targetSession}
                onChange={(e) => {
                  setTargetSession(e.target.value);
                  requestKey.current = null;
                }}
              >
                <option value="">
                  {t("由服务选择会话", "Let the service select a session")}
                </option>
                {sessions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("任务说明", "Task description")}
              <textarea
                value={body}
                onChange={(e) => {
                  setBody(e.target.value);
                  requestKey.current = null;
                }}
                rows={5}
                maxLength={12000}
                required
                placeholder={t(
                  "描述任务、必要上下文和完成标准…",
                  "Describe the task, relevant context and completion criteria…",
                )}
              />
            </label>
            <label>
              {t("关联标识（可选）", "Reference (optional)")}
              <input
                value={reference}
                onChange={(e) => {
                  setReference(e.target.value);
                  requestKey.current = null;
                }}
                maxLength={160}
                placeholder={t("例如：SEARCH-24", "For example: SEARCH-24")}
              />
            </label>
            <p className="form-hint">
              {enabled
                ? t(
                    "发送即派发执行，可能修改项目文件。私有会话历史不会完整复制给其他 Agent。",
                    "Sending dispatches execution and may change project files. Private session history is not copied wholesale to other agents.",
                  )
                : t(
                    "执行已关闭，当前不能派发任务。",
                    "Execution is disabled. Tasks cannot be dispatched.",
                  )}
            </p>
            <button
              className="primary full"
              disabled={busy || !enabled || !recipient || !body.trim()}
            >
              {t("派发任务", "Dispatch task")}
              <Icon name="arrow" size={17} />
            </button>
          </form>
        </section>
      </div>
    </>
  );
}
