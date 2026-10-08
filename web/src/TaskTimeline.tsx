import * as uiMessages from "./messages";
import AccountAttempts from "./AccountAttempts";
import type {
  Account,
  AccountAttempt,
  AgentEvent,
  Language,
  Mutate,
  Run,
  Translate,
} from "./types";
import {
  DateText,
  eventDescription,
  eventLabel,
  eventText,
  errorMessage,
  statusLabel,
} from "./ui";

type Payload = Record<string, any>;
function payload(event: AgentEvent): Payload {
  return event.payload && typeof event.payload === "object"
    ? (event.payload as Payload)
    : {};
}
function toolText(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value))
    return value.map(toolText).filter(Boolean).join("\n");
  if (value && typeof value === "object" && "text" in value)
    return String(value.text);
  return value == null ? "" : JSON.stringify(value, null, 2);
}

type Step = {
  id: string;
  kind: "reasoning" | "tool" | "message";
  text: string;
  name?: string;
  input?: string;
  status?: string;
  itemId?: string;
  phase?: string;
};
export function executionSteps(events: AgentEvent[]): Step[] {
  const steps: Step[] = [];
  const keyed = new Map<string, Step>();
  for (const event of events) {
    const p = payload(event);
    if (event.kind === "output_truncated") {
      steps.push({
        id: event.id,
        kind: "message",
        text: typeof p.text === "string" ? p.text : "Progress truncated",
      });
    } else if (
      event.kind === "reasoning_chunk" ||
      event.kind === "reasoning_message"
    ) {
      const id = `thought:${p.item_id ?? event.id}:${p.part ?? 0}`;
      let step = keyed.get(id);
      if (!step) {
        step = { id, kind: "reasoning", text: "" };
        keyed.set(id, step);
        steps.push(step);
      }
      const text = typeof p.text === "string" ? p.text : "";
      step.text = event.kind === "reasoning_message" ? text : step.text + text;
    } else if (
      ["tool_call", "tool_result", "tool_output"].includes(event.kind)
    ) {
      const item = p.item ?? {};
      const id = `tool:${p.item_id ?? item.id ?? item.tool_use_id ?? event.id}`;
      let step = keyed.get(id);
      if (!step) {
        step = { id, kind: "tool", text: "", status: "running" };
        keyed.set(id, step);
        steps.push(step);
      }
      const name = item.command ?? item.name ?? item.tool;
      if (typeof name === "string") step.name = name;
      if (item.input != null || item.arguments != null)
        step.input = toolText(item.input ?? item.arguments);
      if (event.kind === "tool_output")
        step.text += typeof p.text === "string" ? p.text : "";
      if (event.kind === "tool_result") {
        const result =
          item.aggregatedOutput ??
          item.content ??
          item.result ??
          item.output ??
          item.changes;
        if (result != null) step.text = toolText(result);
        step.status =
          item.status === "declined"
            ? "declined"
            : item.is_error ||
                item.status === "failed" ||
                (typeof item.exitCode === "number" && item.exitCode !== 0)
              ? "failed"
              : "completed";
      }
    } else if (["agent_message_chunk", "agent_message"].includes(event.kind)) {
      const itemId = typeof p.item_id === "string" ? p.item_id : undefined;
      const id = itemId
        ? `message:${p.provider ?? "cli"}:${itemId}:${p.part ?? 0}`
        : event.id;
      let step = itemId ? keyed.get(id) : steps.at(-1);
      if (step?.kind !== "message" || (!itemId && step.itemId)) {
        step = { id, kind: "message", text: "", itemId };
        keyed.set(id, step);
        steps.push(step);
      }
      if (typeof p.phase === "string") step.phase = p.phase;
      const text = eventText(event.payload);
      step.text = event.kind === "agent_message" ? text : step.text + text;
    }
  }
  return steps;
}

export function turnContent(events: AgentEvent[], storedAnswer: string) {
  const steps = executionSteps(events);
  const messages = steps.filter((step) => step.kind === "message");
  let answer = storedAnswer;
  // Older versions joined unphased Codex items into the saved result. Only
  // separate them when the complete event groups reproduce that exact result.
  if (
    answer &&
    messages.length > 1 &&
    steps.at(-1)?.kind === "message" &&
    messages.every((step) => !step.itemId && !step.phase) &&
    messages.map((step) => step.text).join("\n") === answer
  ) {
    answer = messages.at(-1)!.text;
  }
  const replyIds = new Set<string>();
  if (answer) {
    const suffix: Step[] = [];
    for (const step of steps.slice().reverse()) {
      if (step.kind !== "message") break;
      suffix.unshift(step);
      if (suffix.map((part) => part.text).join("\n") === answer) {
        suffix.forEach((part) => replyIds.add(part.id));
        break;
      }
    }
  }
  return {
    answer,
    steps: steps.filter(
      (step) =>
        !answer || (!replyIds.has(step.id) && step.phase !== "final_answer"),
    ),
  };
}

export default function TaskTimeline({
  runs,
  events,
  agentName,
  accounts,
  accountAttempts,
  onConfigureAccount,
  t,
  lang,
  busy,
  mutate,
}: {
  runs: Run[];
  events: AgentEvent[];
  agentName: string;
  accounts?: Account[];
  accountAttempts?: AccountAttempt[];
  onConfigureAccount?: () => void;
  t: Translate;
  lang: Language;
  busy: boolean;
  mutate: Mutate;
}) {
  const tasks = new Map(runs.map((r) => [r.id, { ...r }]));
  const grouped = new Map<string, AgentEvent[]>();
  const orphaned: AgentEvent[] = [];
  const lastAccountChange = events
    .filter((event) =>
      [
        "account_action_required",
        "account_changed",
        "account_switched",
        "account_attempt",
      ].includes(event.kind),
    )
    .at(-1);
  for (const event of events) {
    const p = payload(event);
    if (typeof p.run_id !== "string") {
      orphaned.push(event);
      continue;
    }
    const id = p.run_id;
    if (!tasks.has(id))
      tasks.set(id, {
        id,
        session_id: event.session_id,
        agent_id: "",
        project_id: event.project_id,
        prompt: "",
        status: "loading",
        origin: "human",
        depth: 0,
        created_at: event.created_at,
        updated_at: event.created_at,
      });
    const run = tasks.get(id)!;
    if (event.kind === "user_message")
      run.prompt =
        typeof p.text === "string" ? p.text : eventText(event.payload);
    if (
      event.kind === "run_started" &&
      ["loading", "queued"].includes(run.status)
    )
      run.status = "running";
    if (event.kind === "run_finished" && typeof p.status === "string")
      run.status = p.status;
    if (event.kind === "run_finished" && typeof p.error === "string")
      run.error = p.error;
    const group = grouped.get(id) ?? [];
    group.push(event);
    grouped.set(id, group);
  }
  return (
    <div className="task-timeline">
      {[...tasks.values()]
        .sort((a, b) => a.created_at.localeCompare(b.created_at))
        .map((run) => {
          const runEvents = grouped.get(run.id) ?? [];
          const modelEvent = runEvents
            .filter((event) => event.kind === "model_info")
            .at(-1);
          const modelInfo = modelEvent ? payload(modelEvent) : {};
          const answerEvent = runEvents
            .slice()
            .reverse()
            .find((e) => e.kind === "assistant_message");
          const { answer, steps } = turnContent(
            runEvents,
            run.result || (answerEvent ? eventText(answerEvent.payload) : ""),
          );
          const active = ["running", "queued"].includes(run.status);
          const waiting =
            runEvents.filter((e) => e.kind === "approval_required").length >
            runEvents.filter((e) => e.kind === "approval_resolved").length;
          const connection = runEvents
            .filter((e) => e.kind === "transport_status")
            .at(-1);
          const reconnecting =
            active &&
            connection &&
            payload(connection).status === "reconnecting";
          const label =
            run.status === "completed"
              ? run.work_task_id
                ? t(...uiMessages.tasktimeline_run_finished_3a0e76)
                : t(...uiMessages.tasktimeline_task_completed_bdb582)
              : run.status === "running"
                ? reconnecting
                  ? t(
                      ...uiMessages.tasktimeline_connection_lost_reconnecting_0274a0,
                    )
                  : waiting
                    ? t(...uiMessages.tasktimeline_awaiting_approval_caad1d)
                    : t(...uiMessages.tasktimeline_task_running_0604a8)
                : run.status === "queued"
                  ? t(...uiMessages.tasktimeline_task_queued_b7058d)
                  : run.status === "failed"
                    ? t(...uiMessages.tasktimeline_task_failed_e053ac)
                    : run.status === "loading"
                      ? t(...uiMessages.tasktimeline_loading_task_5c1733)
                      : t(...uiMessages.tasktimeline_task_e8ed2b) +
                        " · " +
                        statusLabel(run.status, t);
          return (
            <article className="task-turn" key={run.id}>
              {run.prompt && (
                <div
                  className={`task-prompt ${run.origin === "human" ? "from-user" : "delegated"}`}
                >
                  <div className="event-meta">
                    <span>
                      {run.origin === "human"
                        ? t(...uiMessages.tasktimeline_you_d1c11b)
                        : t(...uiMessages.tasktimeline_delegated_task_b17737)}
                    </span>
                    <DateText date={run.created_at} lang={lang} />
                  </div>
                  <pre>{run.prompt}</pre>
                </div>
              )}
              <div className="task-progress-row">
                {/* Native toggles survive polling; changing this default on final
                    arrival collapses once, then the user can reopen it freely. */}
                <details
                  className={`task-progress ${run.status}`}
                  open={
                    !answer && !["completed", "loading"].includes(run.status)
                  }
                >
                  <summary>
                    <span
                      className={`task-indicator ${active && run.status === "running" ? "spinning" : ""}`}
                    >
                      {run.status === "completed" ? "✓" : active ? "◌" : "·"}
                    </span>
                    <span>{label}</span>
                    <span className="task-chevron">›</span>
                    {typeof modelInfo.model === "string" && (
                      <small
                        className="task-model"
                        title={t(
                          ...uiMessages.tasktimeline_model_identifier_reported_by_the_cli_7e8617,
                        )}
                      >
                        {modelInfo.model}
                        {typeof modelInfo.effort === "string"
                          ? ` · ${modelInfo.effort}`
                          : ""}
                      </small>
                    )}
                  </summary>
                  <div
                    className="task-steps"
                    role="log"
                    aria-label={t(
                      ...uiMessages.tasktimeline_live_execution_ce86e3,
                    )}
                  >
                    {!steps.length && (
                      <p className="muted">
                        {run.status === "queued"
                          ? t(
                              ...uiMessages.tasktimeline_waiting_to_start_59a4fb,
                            )
                          : active
                            ? t(
                                ...uiMessages.tasktimeline_waiting_for_agent_output_470f31,
                              )
                            : t(
                                ...uiMessages.tasktimeline_no_execution_details_a6e3d1,
                              )}
                      </p>
                    )}
                    {steps.map((step) =>
                      step.kind === "tool" ? (
                        <details
                          className="task-tool"
                          key={step.id}
                          open={step.status === "running" && active}
                        >
                          <summary>
                            <span>
                              {step.name ||
                                t(
                                  ...uiMessages.tasktimeline_tool_execution_bd5475,
                                )}
                            </span>
                            <small>
                              {step.status === "running" && !active
                                ? statusLabel(
                                    run.status === "completed"
                                      ? "interrupted"
                                      : run.status,
                                    t,
                                  )
                                : statusLabel(step.status ?? "running", t)}
                            </small>
                          </summary>
                          {step.input && <pre>{step.input}</pre>}
                          {step.text && <pre>{step.text}</pre>}
                        </details>
                      ) : (
                        <div className={`task-step ${step.kind}`} key={step.id}>
                          <small>
                            {step.kind === "reasoning"
                              ? t(...uiMessages.tasktimeline_thinking_e891a0)
                              : step.phase === "final_answer"
                                ? t(
                                    ...uiMessages.tasktimeline_composing_reply_a78a01,
                                  )
                                : t(...uiMessages.tasktimeline_progress_cdc159)}
                          </small>
                          <pre>{step.text}</pre>
                        </div>
                      ),
                    )}
                  </div>
                </details>
                {active && (
                  <button
                    type="button"
                    className="text-button task-cancel"
                    disabled={busy}
                    onClick={() =>
                      void mutate(
                        `/api/runs/${encodeURIComponent(run.id)}/cancel`,
                        {},
                      )
                    }
                  >
                    {t(...uiMessages.tasktimeline_cancel_68f563)}
                  </button>
                )}
              </div>
              <AccountAttempts
                accounts={accounts}
                attempts={accountAttempts?.filter(
                  (attempt) => attempt.run_id === run.id,
                )}
                events={runEvents}
                active={active}
                actionRequired={
                  lastAccountChange?.kind === "account_action_required" &&
                  payload(lastAccountChange).run_id === run.id
                }
                onConfigureAccount={onConfigureAccount}
                t={t}
              />
              {run.error && (
                <p className="inline-error" role="status">
                  {errorMessage(run.error, t)}
                </p>
              )}
              {answer && (
                <div
                  className="task-answer"
                  aria-label={t(...uiMessages.tasktimeline_agent_reply_8131a8)}
                >
                  <div className="event-meta">
                    <span>{agentName}</span>
                    <span className="task-reply-label">
                      {t(...uiMessages.tasktimeline_reply_0754fa)}
                    </span>
                  </div>
                  <pre>{answer}</pre>
                </div>
              )}
            </article>
          );
        })}
      <AccountAttempts
        accounts={accounts}
        events={orphaned}
        active={false}
        actionRequired={
          lastAccountChange?.kind === "account_action_required" &&
          !payload(lastAccountChange).run_id
        }
        onConfigureAccount={onConfigureAccount}
        t={t}
      />
      {orphaned
        .filter(
          (e) =>
            ![
              "run_started",
              "run_finished",
              "token_usage",
              "account_attempt",
              "account_switched",
              "account_changed",
              "account_action_required",
              "account_waiting",
            ].includes(e.kind),
        )
        .map((event) => (
          <article className="event" key={event.id}>
            <div className="event-meta">
              <span>{eventLabel(event.kind, t)}</span>
              <DateText date={event.created_at} lang={lang} />
            </div>
            <pre>{eventDescription(event, t)}</pre>
          </article>
        ))}
    </div>
  );
}
