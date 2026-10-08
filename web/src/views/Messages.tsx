import * as uiMessages from "../messages";
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
      ? t(...uiMessages.messages_you_d1c11b)
      : (agents.find((a) => a.id === id)?.name ??
        t(...uiMessages.messages_removed_agent_22e81a));
  const enabled = state.runtime.enabled;
  return (
    <>
      <PageTitle
        headingLevel={2}
        eyebrow=""
        title={t(...uiMessages.messages_dispatch_07f639)}
        description={t(
          ...uiMessages.messages_submit_work_to_an_agent_s_native_session_and_b644f9,
        )}
      />
      <div className="two-column">
        <section className="panel">
          <div className="panel-heading">
            <h2>
              {t(...uiMessages.messages_dispatch_activity_b03885)}{" "}
              <span className="count-badge">{messages.length}</span>
            </h2>
            <label className="compact-select">
              <span className="sr-only">
                {t(...uiMessages.messages_filter_by_target_agent_2ca43c)}
              </span>
              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                <option value="all">
                  {t(...uiMessages.messages_all_agents_bcb360)}
                </option>
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
                        {t(...uiMessages.messages_target_session_9cf187)}:{" "}
                        {session?.title ??
                          t(...uiMessages.messages_not_assigned_yet_8e05c3)}
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
                            ? t(...uiMessages.messages_progress_so_far_f605bc)
                            : t(...uiMessages.messages_result_860e32)}
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
                        {t(...uiMessages.messages_return_task_a8ebd1)}:{" "}
                        {statusLabel(replyRun.status, t)}
                        {replyRun.error && ` · ${replyRun.error}`}
                      </p>
                    )}
                    <footer>
                      <DateText date={message.created_at} lang={lang} />
                      {message.correlation_id && (
                        <span>
                          {t(...uiMessages.messages_reference_173f93)}:{" "}
                          {message.correlation_id}
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
                          {t(...uiMessages.messages_cancel_task_5b5e51)}
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
              title={t(...uiMessages.messages_no_dispatched_tasks_902119)}
            >
              {t(
                ...uiMessages.messages_choose_an_agent_and_session_then_describe_the_728e88,
              )}
            </Empty>
          )}
        </section>
        <section className="panel inset-form sticky-panel">
          <span className="eyebrow">
            {t(...uiMessages.messages_new_dispatch_fd708e)}
          </span>
          <h2>{t(...uiMessages.messages_delegate_a_task_1b4790)}</h2>
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
              {t(...uiMessages.messages_target_agent_aaf306)}
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
                    {t(...uiMessages.messages_add_an_agent_first_826af7)}
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
              {t(...uiMessages.messages_target_session_9cf187)}
              <select
                value={targetSession}
                onChange={(e) => {
                  setTargetSession(e.target.value);
                  requestKey.current = null;
                }}
              >
                <option value="">
                  {t(
                    ...uiMessages.messages_let_the_service_select_a_session_f84266,
                  )}
                </option>
                {sessions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t(...uiMessages.messages_task_description_fb693f)}
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
                  ...uiMessages.messages_describe_the_task_relevant_context_and_comple_56372d,
                )}
              />
            </label>
            <label>
              {t(...uiMessages.messages_reference_optional_6e8d6c)}
              <input
                value={reference}
                onChange={(e) => {
                  setReference(e.target.value);
                  requestKey.current = null;
                }}
                maxLength={160}
                placeholder={t(
                  ...uiMessages.messages_for_example_search_24_9ac3f9,
                )}
              />
            </label>
            <p className="form-hint">
              {enabled
                ? t(
                    ...uiMessages.messages_sending_dispatches_execution_and_may_change_p_0dac4a,
                  )
                : t(
                    ...uiMessages.messages_execution_is_disabled_tasks_cannot_be_dispatc_2c364a,
                  )}
            </p>
            <button
              className="primary full"
              disabled={busy || !enabled || !recipient || !body.trim()}
            >
              {t(...uiMessages.messages_dispatch_task_00a9c3)}
              <Icon name="arrow" size={17} />
            </button>
          </form>
        </section>
      </div>
    </>
  );
}
