import { errorCopy, legacyErrorCodes } from "./errorMessages";
import * as uiMessages from "./messages";
import type { ReactNode } from "react";
import type {
  AgentEvent,
  Approval,
  Language,
  Memory,
  Mutate,
  Translate,
} from "./types";

export function errorMessage(message: string, t: Translate): string {
  if (message.startsWith("internal_error:")) {
    return (
      t(...uiMessages.ui_operation_failed_export_diagnostics_error_id_d1917f) +
      message.slice(15)
    );
  }

  const key = message.startsWith("error_code:")
    ? message.slice(11)
    : legacyErrorCodes[message];
  return errorCopy[key] ? t(...errorCopy[key]) : message;
}

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    agent: (
      <>
        <rect x="5" y="7" width="14" height="13" rx="3" />
        <path d="M12 3v4M10 3h4M2 12v4M22 12v4M9 12v3M15 12v3" />
      </>
    ),
    timer: (
      <>
        <circle cx="12" cy="14" r="8" />
        <path d="M10 2h4M19 5l1.5-1.5M12 14l3-4" />
      </>
    ),
    folder: (
      <path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Zm0 2h18" />
    ),
    dock: (
      <>
        <path d="M4 5h6v14H4zM14 5h6v6h-6zM14 15h6v4h-6z" />
      </>
    ),
    work: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="3" />
        <path d="M9 5v14M3 10h6" />
      </>
    ),
    message: (
      <>
        <path d="M20 14a4 4 0 0 1-4 4H9l-5 3V7a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4z" />
        <path d="M8 8h8M8 12h5" />
      </>
    ),
    memory: (
      <>
        <path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5" />
      </>
    ),
    usage: (
      <>
        <path d="M4 20h17M6 16v-5M12 16V4M18 16V8" />
      </>
    ),
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    back: <path d="M19 12H5m5-5-5 5 5 5" />,
    edit: <path d="m15 4 5 5M4 20l5-1L21 7a2.1 2.1 0 0 0-5-5L4 14v6Z" />,
    plus: <path d="M12 5v14M5 12h14" />,
    refresh: (
      <>
        <path d="M20 7v5h-5M4 17v-5h5" />
        <path d="M6.2 6.2a8 8 0 0 1 13 3.8M4.8 14a8 8 0 0 0 13 3.8" />
      </>
    ),
    shield: (
      <>
        <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z" />
        <path d="m8 12 3 3 5-6" />
      </>
    ),
    search: (
      <>
        <circle cx="10" cy="10" r="6" />
        <path d="m15 15 6 6" />
      </>
    ),
    close: <path d="m6 6 12 12M6 18 18 6" />,
    bolt: <path d="m13 2-9 12h7l-1 8 10-13h-7z" />,
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] ?? paths.dock}
    </svg>
  );
}

export function DateText({
  date,
  lang,
}: {
  date?: string | null;
  lang: Language;
}) {
  if (!date) return <span>—</span>;
  const value = new Date(date);
  return (
    <time dateTime={date}>
      {Number.isNaN(value.getTime())
        ? "—"
        : value.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
    </time>
  );
}

export function Empty({
  icon,
  title,
  children,
}: {
  icon: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name={icon} size={26} />
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

export function Brand({ small = false }: { small?: boolean }) {
  return (
    <div className={`brand ${small ? "small" : ""}`}>
      <span className="brand-symbol">
        <Icon name="dock" size={24} />
      </span>
      <span>AgentDock</span>
    </div>
  );
}

export function Stat({
  value,
  label,
  icon,
}: {
  value: number;
  label: string;
  icon: string;
}) {
  return (
    <div className="stat">
      <span>
        <Icon name={icon} />
        {label}
      </span>
      <strong>{value}</strong>
    </div>
  );
}
export function statusLabel(status: string, t: Translate) {
  return (
    {
      idle: t(...uiMessages.ui_idle_1f7cc9),
      queued: t(...uiMessages.ui_queued_db5a74),
      waiting: t(...uiMessages.ui_waiting_for_results_5e0b4b),
      dispatched: t(...uiMessages.ui_dispatched_32dc8c),
      accepted: t(...uiMessages.ui_accepted_00dcaf),
      delivering: t(...uiMessages.ui_dispatching_7d78c8),
      reply_queued: t(...uiMessages.ui_reply_queued_5226ff),
      replied: t(...uiMessages.ui_replied_afe565),
      pending: t(...uiMessages.ui_pending_7f25ba),
      running: t(...uiMessages.ui_running_79c71e),
      completed: t(...uiMessages.ui_completed_066012),
      declined: t(...uiMessages.ui_declined_db04ae),
      failed: t(...uiMessages.ui_failed_840d25),
      cancelled: t(...uiMessages.ui_cancelled_2dbec7),
      interrupted: t(...uiMessages.ui_interrupted_464894),
      deleting: t(...uiMessages.ui_deleting_retry_available_a4711c),
    }[status] ?? status
  );
}

export function eventLabel(kind: string, t: Translate) {
  const labels: Record<string, string> = {
    prompt: t(...uiMessages.ui_your_task_c33aa7),
    user_message: t(...uiMessages.ui_your_task_c33aa7),
    agent_message: t(...uiMessages.ui_agent_response_54d6cb),
    agent_output: t(...uiMessages.ui_agent_response_54d6cb),
    assistant_message: t(...uiMessages.ui_agent_response_54d6cb),
    assistant: t(...uiMessages.ui_agent_response_54d6cb),
    run_queued: t(...uiMessages.ui_task_queued_958695),
    run_started: t(...uiMessages.ui_run_started_528089),
    run_completed: t(...uiMessages.ui_run_completed_e09737),
    run_failed: t(...uiMessages.ui_run_failed_e49e28),
    run_cancelled: t(...uiMessages.ui_run_cancelled_3b697c),
    run_finished: t(...uiMessages.ui_run_finished_461742),
    task_settled: t(...uiMessages.ui_collaboration_settled_b48558),
    reply_queued: t(...uiMessages.ui_result_queued_for_return_33125f),
    reply_not_scheduled: t(...uiMessages.ui_result_not_returned_05b489),
    approval_required: t(...uiMessages.ui_approval_required_a53e84),
    approval_resolved: t(...uiMessages.ui_approval_resolved_c6b751),
    memory_proposed: t(...uiMessages.ui_memory_proposal_awaiting_review_d844b8),
    agent_message_chunk: t(...uiMessages.ui_agent_response_54d6cb),
    message_queued: t(...uiMessages.ui_dispatch_queued_163ce4),
    message_sent: t(...uiMessages.ui_task_dispatched_d85725),
    tool_call: t(...uiMessages.ui_tool_call_4f62df),
    tool_result: t(...uiMessages.ui_tool_result_6f77db),
    session_bound: t(...uiMessages.ui_native_session_bound_f1bea9),
    permission_request: t(...uiMessages.ui_approval_requested_7e0be4),
  };
  return labels[kind] ?? t(...uiMessages.ui_session_event_fd5247);
}

export function eventText(payload: unknown): string {
  if (typeof payload === "string") return payload;
  if (payload && typeof payload === "object") {
    const value = payload as Record<string, unknown>;
    if (typeof value.text === "string") return value.text;
    if (typeof value.content === "string") return value.content;
    const content = value.content as Record<string, unknown> | undefined;
    if (content && typeof content.text === "string") return content.text;
  }
  return JSON.stringify(payload, null, 2) ?? "";
}

/** Merge text deltas for readability; a final response replaces its own streamed preview. */
export function conversationEvents(events: AgentEvent[]): AgentEvent[] {
  const result: AgentEvent[] = [];
  const runId = (event: AgentEvent) =>
    (event.payload as Record<string, unknown> | null)?.run_id;
  for (const event of events) {
    const previous = result[result.length - 1];
    if (
      event.kind === "agent_message_chunk" &&
      previous?.kind === event.kind &&
      runId(previous) === runId(event)
    ) {
      result[result.length - 1] = {
        ...previous,
        payload: {
          text: eventText(previous.payload) + eventText(event.payload),
          run_id: runId(event),
        },
      };
    } else {
      if (event.kind === "assistant_message" && runId(event)) {
        for (let i = result.length - 1; i >= 0; i--) {
          if (
            result[i].kind === "agent_message_chunk" &&
            runId(result[i]) === runId(event)
          )
            result.splice(i, 1);
        }
      }
      result.push(event);
    }
  }
  return result;
}

export function eventDescription(event: AgentEvent, t: Translate): string {
  const payload = event.payload as Record<string, unknown> | null;
  if (!payload || typeof payload !== "object") return eventText(event.payload);
  if (event.kind === "run_queued")
    return t(
      ...uiMessages.ui_the_task_joined_this_session_s_execution_queu_55a64a,
    );
  if (event.kind === "run_started")
    return t(...uiMessages.ui_processing_the_task_in_the_native_session_3eb07b);
  if (event.kind === "run_finished" || event.kind === "task_settled")
    return `${statusLabel(String(payload.status ?? "completed"), t)}${payload.error ? ` · ${payload.error}` : ""}`;
  if (event.kind === "message_queued")
    return t(
      ...uiMessages.ui_the_delegated_task_is_waiting_for_the_target_155f49,
    );
  if (event.kind === "reply_queued")
    return t(
      ...uiMessages.ui_the_result_will_return_to_the_original_sessio_e6a107,
    );
  if (event.kind === "reply_not_scheduled")
    return t(
      ...uiMessages.ui_the_original_task_stopped_or_reached_a_collab_13f914,
    );
  if (event.kind === "approval_required")
    return t(...uiMessages.ui_review_the_requested_action_below_a9ed7d);
  if (event.kind === "approval_resolved")
    return t(...uiMessages.ui_your_approval_decision_was_submitted_0a1365);
  if (event.kind === "memory_proposed")
    return t(
      ...uiMessages.ui_review_the_agent_s_proposal_in_shared_memory_1a801e,
    );
  return eventText(event.payload);
}

export function ApprovalCard({
  approval,
  t,
  busy,
  mutate,
}: {
  approval: Approval;
  t: Translate;
  busy: boolean;
  mutate: Mutate;
}) {
  return (
    <section className="approval-card">
      <h3>
        <Icon name="shield" size={18} />
        {t(...uiMessages.ui_your_approval_is_required_1e515c)}
      </h3>
      <p>
        {t(
          ...uiMessages.ui_the_agent_supplied_this_request_review_its_co_1eaed4,
        )}
      </p>
      <pre>{eventText(approval.request)}</pre>
      <div className="button-row">
        {approval.options.map((option) => (
          <button
            key={option.optionId}
            className={
              option.kind.startsWith("reject") ? "secondary" : "approval-allow"
            }
            disabled={busy}
            onClick={() =>
              void mutate(`/api/approvals/${encodeURIComponent(approval.id)}`, {
                option_id: option.optionId,
              })
            }
          >
            {option.name === "Allow once"
              ? t(...uiMessages.ui_allow_once_8cb57a)
              : option.name === "Deny"
                ? t(...uiMessages.ui_deny_b2d888)
                : option.name}
            <small>
              {option.kind === "allow_once"
                ? t(...uiMessages.ui_one_time_permission_b78090)
                : option.kind === "reject_once"
                  ? t(...uiMessages.ui_do_not_execute_9ddfc9)
                  : option.kind}
            </small>
          </button>
        ))}
      </div>
    </section>
  );
}

export function isArchived(memory: Memory) {
  return (
    memory.archived || !!memory.archived_at || memory.status === "archived"
  );
}
export function PageTitle({
  eyebrow,
  title,
  description,
  action,
  headingLevel = 1,
}: {
  headingLevel?: 1 | 2;
  eyebrow: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  const Heading = headingLevel === 2 ? "h2" : "h1";
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <Heading>{title}</Heading>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}
