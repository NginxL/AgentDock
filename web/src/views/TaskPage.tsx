import * as uiMessages from "../messages";
import { useEffect, useRef, useState } from "react";
import { SessionAccountControls } from "../AccountSelection";
import { request } from "../api";
import InferenceControls from "../InferenceControls";
import { followSession } from "../sessionEvents";
import TaskTimeline from "../TaskTimeline";
import type {
  AgentEvent,
  Language,
  Mutate,
  ProjectTask,
  TaskDetail,
  TaskIntent,
} from "../types";
import { ApprovalCard, DateText, Icon } from "../ui";
import Question from "./Question";
import TaskSettings from "./TaskSettings";
import { taskLabel, type Common } from "./taskShared";
export default function TaskPage({
  task,
  state,
  t,
  busy,
  mutate,
  token,
  demo,
  lang,
  back,
}: Common & {
  task: ProjectTask;
  token: string;
  demo: boolean;
  lang: Language;
  back: () => void;
}) {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const [body, setBody] = useState("");
  const [intent, setIntent] = useState<TaskIntent>(
    task.intent === "record" ? "develop" : task.intent,
  );
  const [action, setAction] = useState("queue");
  const [owner, setOwner] = useState(task.owner_id);
  const [watch, setWatch] = useState(task.status === "active");
  const [editing, setEditing] = useState(false);
  const [sessionID, setSessionID] = useState("");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const composing = useRef(false),
    submitting = useRef(false);
  const pendingRequest = useRef<{
    body: string;
    intent: string;
    action: string;
    id: string;
  } | null>(null);
  const recoveryRequest = useRef<{
    owner: string;
    intent: string;
    id: string;
  } | null>(null);
  const refresh = () => setVersion((v) => v + 1);
  const change: Mutate = async (path, data, done) => {
    const ok = await mutate(path, data, done);
    if (ok) refresh();
    return ok;
  };
  useEffect(() => {
    const controller = new AbortController();
    if (demo) {
      setDetail({
        ...task,
        inputs: [],
        questions: [],
        deliveries: [],
        sessions: [],
        runs: [],
        journal: [],
        workspaces: [],
      });
      return;
    }
    void request<TaskDetail>(
      token,
      `/api/tasks/${task.id}`,
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) {
          setDetail(value);
          setError("");
        }
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError(
            t(...uiMessages.taskpage_could_not_load_this_task_retry_f52dd3),
          );
      });
    return () => controller.abort();
  }, [
    task.id,
    task.updated_at,
    task.status,
    state.runs,
    version,
    token,
    demo,
    t,
  ]);
  const current = detail ?? task;
  useEffect(() => {
    setWatch(current.status === "active");
  }, [current.status]);
  const sessions = detail?.sessions ?? [];
  const selected =
    sessions.find((s) => s.id === sessionID) ??
    sessions.find((s) => s.id === current.session_id) ??
    sessions.at(-1);
  useEffect(() => {
    setEvents([]);
    if (!watch || !selected || demo) return;
    const controller = new AbortController();
    void followSession(
      token,
      selected.id,
      controller.signal,
      (incoming) =>
        setEvents((old) => {
          const ids = new Set(old.map((e) => e.id));
          return [...old, ...incoming.filter((e) => !ids.has(e.id))];
        }),
      () => {},
    );
    return () => controller.abort();
  }, [selected?.id, token, demo, watch]);
  const live = (detail?.runs ?? []).some((r) =>
    ["queued", "running"].includes(r.status),
  );
  const closed = ["completed", "cancelled", "archived"].includes(
    current.status,
  );
  const stopped = ["interrupted", "paused"].includes(current.status);
  const delivery = detail?.deliveries.find((d) => d.id === current.delivery_id);
  const lastReply = detail?.runs
    .filter(
      (r) => r.task_role === "owner" && r.status === "completed" && r.result,
    )
    .at(-1);
  const steeringUnavailable = action === "steer" && !detail?.can_steer_run_id;
  const agents = state.agents.filter(
    (a) =>
      a.project_id === task.project_id &&
      (a.environment_id ?? "local") ===
        (state.projects.find((p) => p.id === task.project_id)?.environment_id ??
          "local"),
  );
  const ownerAgent = agents.find((a) => a.id === current.owner_id);
  const ownerSession = sessions.find((s) => s.id === current.session_id);
  return (
    <div className="project-task-page">
      <header className="task-page-header">
        <button
          className="icon-button"
          onClick={back}
          aria-label={t(...uiMessages.taskpage_back_to_tasks_d3db24)}
        >
          <Icon name="back" />
        </button>
        <h2>{current.title}</h2>
        <span className="pill">{taskLabel(current.status, t)}</span>
      </header>
      {error && (
        <div role="alert" className="alert">
          {error}
          <button onClick={refresh}>
            {t(...uiMessages.taskpage_retry_19a00f)}
          </button>
        </div>
      )}
      <section className="panel task-brief">
        <p className="task-prose">{current.goal}</p>
        <details>
          <summary>
            {t(
              ...uiMessages.taskpage_acceptance_criteria_and_task_settings_c8924f,
            )}
          </summary>
          <ul>
            {current.criteria.split("\n").map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <p>
            {t(...uiMessages.taskpage_acceptance_d68747)}：
            {current.acceptance_policy === "owner"
              ? t(...uiMessages.taskpage_owner_verifies_every_criterion_61b7a4)
              : t(...uiMessages.taskpage_human_confirmation_19648f)}
          </p>
          <p>
            {current.review_required
              ? t(...uiMessages.taskpage_independent_review_required_aa67bb)
              : t(
                  ...uiMessages.taskpage_owner_arranges_review_as_needed_1c75ff,
                )}
          </p>
          <p>
            {current.workspace_mode === "shared"
              ? t(...uiMessages.taskpage_shared_project_directory_d3451f)
              : t(...uiMessages.taskpage_isolated_git_worktrees_68ea12)}
          </p>
        </details>
        {!closed && (
          <button
            className="text-button"
            disabled={live}
            aria-expanded={editing}
            onClick={() => setEditing(!editing)}
          >
            {t(...uiMessages.taskpage_edit_requirements_63057f)}{" "}
            <Icon name={editing ? "close" : "edit"} />
          </button>
        )}
        <div className="task-controls">
          <label>
            {t(...uiMessages.taskpage_task_owner_4079a1)}
            <select
              value={owner}
              disabled={live || closed}
              onChange={(e) => setOwner(e.target.value)}
            >
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          {!closed && !live && (
            <button
              className="secondary"
              disabled={busy || !state.runtime.enabled}
              onClick={() => {
                const mode = intent === "record" ? "develop" : intent;
                const previous = recoveryRequest.current;
                const id =
                  previous?.owner === owner && previous?.intent === mode
                    ? previous.id
                    : crypto.randomUUID();
                recoveryRequest.current = { owner, intent: mode, id };
                void change(
                  `/api/tasks/${task.id}/resume`,
                  { owner_id: owner, intent: mode, request_id: id },
                  () => {
                    recoveryRequest.current = null;
                  },
                );
              }}
            >
              {owner !== current.owner_id
                ? t(...uiMessages.taskpage_reassign_and_continue_afecf3)
                : t(...uiMessages.taskpage_continue_task_12b5c4)}
            </button>
          )}
          {!closed && current.status !== "paused" && (
            <button
              className="secondary"
              disabled={busy || !state.runtime.enabled}
              onClick={() => void change(`/api/tasks/${task.id}/pause`, {})}
            >
              {t(...uiMessages.taskpage_pause_task_e9ed8d)}
            </button>
          )}
          {!closed && (
            <button
              className="text-button danger"
              disabled={busy || !state.runtime.enabled}
              onClick={() => void change(`/api/tasks/${task.id}/cancel`, {})}
            >
              {t(...uiMessages.taskpage_cancel_task_5b5e51)}
            </button>
          )}
          {["completed", "cancelled"].includes(current.status) && (
            <>
              <button
                className="secondary"
                disabled={busy}
                onClick={() => void change(`/api/tasks/${task.id}/reopen`, {})}
              >
                {t(...uiMessages.taskpage_reopen_bc0937)}
              </button>
              <button
                className="text-button"
                disabled={busy}
                onClick={() => void change(`/api/tasks/${task.id}/archive`, {})}
              >
                {t(...uiMessages.taskpage_archive_990782)}
              </button>
            </>
          )}
        </div>
      </section>
      {editing && (
        <TaskSettings
          key={current.revision}
          task={current}
          t={t}
          busy={busy || live}
          mutate={change}
          close={() => setEditing(false)}
        />
      )}
      {detail?.questions
        .filter((q) => q.status === "open")
        .map((q) => (
          <section className="panel task-inbox" key={q.id}>
            <h3>{t(...uiMessages.taskpage_needs_your_input_3caf95)}</h3>
            <Question
              question={q}
              taskID={task.id}
              t={t}
              busy={busy || closed || !state.runtime.enabled}
              mutate={change}
            />
          </section>
        ))}
      {delivery && (
        <section className="panel task-delivery">
          <div className="panel-heading">
            <h3>{t(...uiMessages.taskpage_delivery_f51250)}</h3>
            <span className="pill">
              {delivery.status === "accepted"
                ? t(...uiMessages.taskpage_accepted_0894df)
                : t(...uiMessages.taskpage_needs_acceptance_cded99)}
            </span>
          </div>
          <p className="task-prose">{delivery.summary}</p>
          <ul className="task-checks">
            {delivery.checks.map((c) => (
              <li key={c.criterion}>
                <strong>
                  {c.status === "passed"
                    ? "✓"
                    : c.status === "failed"
                      ? "✕"
                      : "○"}{" "}
                  {c.criterion}
                </strong>
                <p>{c.evidence}</p>
              </li>
            ))}
          </ul>
          {delivery.artifacts.length > 0 && (
            <>
              <h4>{t(...uiMessages.taskpage_files_and_links_99fd62)}</h4>
              <ul>
                {delivery.artifacts.map((a) => (
                  <li key={a}>
                    {/^https?:\/\//.test(a) ? (
                      <a href={a} target="_blank" rel="noreferrer">
                        {a}
                      </a>
                    ) : (
                      <code>{a}</code>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
          {delivery.risks && (
            <>
              <h4>{t(...uiMessages.taskpage_remaining_issues_3f3528)}</h4>
              <p className="task-prose">{delivery.risks}</p>
            </>
          )}
          {current.status === "review" && (
            <button
              className="primary"
              disabled={
                busy ||
                live ||
                delivery.checks.some((c) => c.status !== "passed")
              }
              onClick={() => void change(`/api/tasks/${task.id}/accept`, {})}
            >
              {t(...uiMessages.taskpage_accept_delivery_499bb1)}
            </button>
          )}
        </section>
      )}
      {!delivery && lastReply && !live && (
        <section className="panel task-delivery">
          <h3>
            {current.intent === "discuss"
              ? t(...uiMessages.taskpage_discussion_result_762464)
              : t(...uiMessages.taskpage_current_progress_ec2f3f)}
          </h3>
          <p className="task-prose">{lastReply.result}</p>
        </section>
      )}
      {detail?.reviews?.length ? (
        <details className="panel">
          <summary>{t(...uiMessages.taskpage_review_reports_2bb5f2)}</summary>
          {detail.reviews.map((review) => (
            <article key={review.id}>
              <strong>
                {review.verdict === "approved"
                  ? t(...uiMessages.taskpage_approved_9afdc9)
                  : review.verdict === "changes_requested"
                    ? t(...uiMessages.taskpage_changes_requested_25d719)
                    : t(...uiMessages.taskpage_unverified_7d487b)}
              </strong>
              <p className="task-prose">{review.summary}</p>
            </article>
          ))}
        </details>
      ) : null}
      {detail && detail.questions.some((q) => q.status === "answered") && (
        <details className="panel">
          <summary>{t(...uiMessages.taskpage_saved_decisions_ab631e)}</summary>
          {detail.questions
            .filter((q) => q.status === "answered")
            .map((q) => (
              <div key={q.id}>
                <strong>{q.question}</strong>
                <p className="task-prose">{q.answer}</p>
              </div>
            ))}
        </details>
      )}
      {(detail?.inputs.length ?? 0) > 0 && (
        <section className="task-input-history">
          {detail!.inputs.map((input) => (
            <article key={input.id} className="task-user-input">
              <p className="task-prose">{input.body}</p>
              <small>
                {taskLabel(input.status, t)} ·{" "}
                <DateText date={input.created_at} lang={lang} />
              </small>
            </article>
          ))}
        </section>
      )}
      {sessions.length > 0 && (
        <section className="panel task-process">
          <div className="panel-heading">
            <h3>{t(...uiMessages.taskpage_execution_0d1a07)}</h3>
            <button
              className="text-button"
              aria-expanded={watch}
              onClick={() => setWatch(!watch)}
            >
              {watch
                ? t(...uiMessages.taskpage_hide_process_ac8611)
                : t(...uiMessages.taskpage_show_process_e22968)}
              <Icon name={watch ? "close" : "arrow"} />
            </button>
          </div>
          {watch && (
            <>
              <label>
                {t(...uiMessages.taskpage_conversation_8acaf9)}
                <select
                  value={selected?.id ?? ""}
                  onChange={(e) => setSessionID(e.target.value)}
                >
                  {sessions.map((s, i) => (
                    <option key={s.id} value={s.id}>
                      {state.agents.find((a) => a.id === s.agent_id)?.name ??
                        t(...uiMessages.taskpage_removed_agent_22e81a)}{" "}
                      ·{" "}
                      {s.task_role === "owner"
                        ? t(...uiMessages.taskpage_owner_ddf80b)
                        : s.task_role === "reviewer"
                          ? t(...uiMessages.taskpage_review_5e1a7d)
                          : t(...uiMessages.taskpage_worker_9c94ea)}{" "}
                      · {i + 1}
                    </option>
                  ))}
                </select>
              </label>
              <TaskTimeline
                runs={(detail?.runs ?? []).filter(
                  (r) => r.session_id === selected?.id,
                )}
                events={events}
                agentName={
                  state.agents.find((a) => a.id === selected?.agent_id)?.name ??
                  ""
                }
                t={t}
                lang={lang}
                busy={busy}
                mutate={change}
              />
            </>
          )}
        </section>
      )}
      {state.approvals
        .filter((a) => sessions.some((s) => s.id === a.session_id))
        .map((a) => (
          <ApprovalCard
            key={a.id}
            approval={a}
            t={t}
            busy={busy}
            mutate={change}
          />
        ))}
      {!closed && !stopped && (
        <form
          className="panel task-composer"
          onSubmit={async (e) => {
            e.preventDefault();
            if (
              submitting.current ||
              busy ||
              !body.trim() ||
              steeringUnavailable
            )
              return;
            submitting.current = true;
            const input = { body: body.trim(), intent, action };
            const prior = pendingRequest.current;
            const id =
              prior &&
              prior.body === input.body &&
              prior.intent === intent &&
              prior.action === action
                ? prior.id
                : crypto.randomUUID();
            pendingRequest.current = { ...input, id };
            try {
              await change(
                `/api/tasks/${task.id}/inputs`,
                {
                  ...input,
                  request_id: id,
                  expected_run_id: detail?.can_steer_run_id,
                },
                () => {
                  setBody("");
                  pendingRequest.current = null;
                },
              );
            } finally {
              submitting.current = false;
            }
          }}
        >
          <label htmlFor="task-input">
            {t(...uiMessages.taskpage_add_requirements_or_continue_d8339c)}
          </label>
          <textarea
            id="task-input"
            rows={3}
            maxLength={24000}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onCompositionStart={() => {
              composing.current = true;
            }}
            onCompositionEnd={() => {
              composing.current = false;
            }}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.altKey &&
                !e.ctrlKey &&
                !e.metaKey &&
                !e.repeat &&
                !e.nativeEvent.isComposing &&
                !composing.current &&
                e.nativeEvent.keyCode !== 229
              ) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
          />
          {ownerAgent && ownerSession && (
            <>
              <SessionAccountControls
                key={`account-${ownerSession.id}`}
                accounts={state.accounts ?? []}
                agent={ownerAgent}
                session={ownerSession}
                busy={busy || live}
                demo={demo}
                mutate={change}
                t={t}
              />
              <InferenceControls
                key={ownerSession.id}
                agent={ownerAgent}
                session={ownerSession}
                token={token}
                busy={busy}
                runtimeEnabled={state.runtime.enabled}
                demo={demo}
                mutate={change}
                t={t}
              />
            </>
          )}
          <div className="task-composer-actions">
            <label>
              <span className="sr-only">
                {t(...uiMessages.taskpage_action_56a0d2)}
              </span>
              <select
                value={intent}
                onChange={(e) => {
                  setIntent(e.target.value as TaskIntent);
                  setAction("queue");
                }}
              >
                <option
                  value="develop"
                  disabled={live && current.intent !== "develop"}
                >
                  {t(...uiMessages.taskpage_execute_91f736)}
                </option>
                <option
                  value="discuss"
                  disabled={live && current.intent !== "discuss"}
                >
                  {t(...uiMessages.taskpage_discuss_first_33de82)}
                </option>
                <option value="record">
                  {t(...uiMessages.taskpage_save_note_33a1f3)}
                </option>
              </select>
            </label>
            {(live || action === "steer") && intent !== "record" && (
              <label>
                <span className="sr-only">
                  {t(...uiMessages.taskpage_input_timing_252b41)}
                </span>
                <select
                  value={action}
                  onChange={(e) => setAction(e.target.value)}
                >
                  <option value="queue">
                    {t(...uiMessages.taskpage_queue_f9d3d6)}
                  </option>
                  <option value="steer" disabled={!detail?.can_steer_run_id}>
                    {t(...uiMessages.taskpage_adjust_now_1470ca)}
                  </option>
                </select>
              </label>
            )}
            {steeringUnavailable && (
              <span className="muted">
                {t(
                  ...uiMessages.taskpage_this_turn_ended_or_cannot_be_adjusted_choose_818646,
                )}
              </span>
            )}
            <button
              className="primary"
              disabled={
                busy ||
                !body.trim() ||
                steeringUnavailable ||
                (!state.runtime.enabled && intent !== "record")
              }
            >
              {intent === "record"
                ? t(...uiMessages.taskpage_save_e422d9)
                : live && action === "queue"
                  ? t(...uiMessages.taskpage_queue_35420c)
                  : t(...uiMessages.taskpage_send_0e0949)}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
