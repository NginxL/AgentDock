import type { ReactNode } from "react";
import type {
  AgentEvent,
  Approval,
  Language,
  Memory,
  Mutate,
  Translate,
} from "./types";

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
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
      idle: t("待命", "Idle"),
      queued: t("排队中", "Queued"),
      waiting: t("等待协作结果", "Waiting for results"),
      dispatched: t("已派发", "Dispatched"),
      accepted: t("已接收", "Accepted"),
      delivering: t("派发中", "Dispatching"),
      reply_queued: t("回复排队中", "Reply queued"),
      replied: t("已回传", "Replied"),
      pending: t("待处理", "Pending"),
      running: t("运行中", "Running"),
      completed: t("完成", "Completed"),
      declined: t("已拒绝", "Declined"),
      failed: t("失败", "Failed"),
      cancelled: t("已取消", "Cancelled"),
      interrupted: t("已中断", "Interrupted"),
    }[status] ?? status
  );
}

export function eventLabel(kind: string, t: Translate) {
  const labels: Record<string, string> = {
    prompt: t("你的任务", "Your task"),
    user_message: t("你的任务", "Your task"),
    agent_message: t("Agent 回复", "Agent response"),
    agent_output: t("Agent 回复", "Agent response"),
    assistant_message: t("Agent 回复", "Agent response"),
    assistant: t("Agent 回复", "Agent response"),
    run_queued: t("任务已排队", "Task queued"),
    run_started: t("开始执行", "Run started"),
    run_completed: t("执行完成", "Run completed"),
    run_failed: t("执行失败", "Run failed"),
    run_cancelled: t("任务已取消", "Run cancelled"),
    run_finished: t("执行结束", "Run finished"),
    task_settled: t("协作任务已结束", "Collaboration settled"),
    reply_queued: t("结果待回传", "Result queued for return"),
    reply_not_scheduled: t("结果未回传", "Result not returned"),
    approval_required: t("等待授权", "Approval required"),
    approval_resolved: t("授权已处理", "Approval resolved"),
    memory_proposed: t("记忆提案待审阅", "Memory proposal awaiting review"),
    agent_message_chunk: t("Agent 回复", "Agent response"),
    message_queued: t("派工已排队", "Dispatch queued"),
    message_sent: t("任务已派发", "Task dispatched"),
    tool_call: t("工具调用", "Tool call"),
    tool_result: t("工具结果", "Tool result"),
    session_bound: t("原生会话已绑定", "Native session bound"),
    permission_request: t("等待授权", "Approval requested"),
  };
  return labels[kind] ?? t("会话事件", "Session event");
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
      "任务已进入此会话的执行队列。",
      "The task joined this session’s execution queue.",
    );
  if (event.kind === "run_started")
    return t(
      "正在使用原生会话处理任务。",
      "Processing the task in the native session.",
    );
  if (event.kind === "run_finished" || event.kind === "task_settled")
    return `${statusLabel(String(payload.status ?? "completed"), t)}${payload.error ? ` · ${payload.error}` : ""}`;
  if (event.kind === "message_queued")
    return t(
      "协作任务已派发，等待目标 Agent 处理。",
      "The delegated task is waiting for the target agent to process it.",
    );
  if (event.kind === "reply_queued")
    return t(
      "协作结果将提交给原会话，继续原任务。",
      "The result will return to the original session to continue the task.",
    );
  if (event.kind === "reply_not_scheduled")
    return t(
      "原任务已停止或达到协作限制，结果未自动提交给原会话。",
      "The original task stopped or reached a collaboration limit; the result was not automatically submitted.",
    );
  if (event.kind === "approval_required")
    return t("请核对下面的操作请求。", "Review the requested action below.");
  if (event.kind === "approval_resolved")
    return t("你的授权选择已提交。", "Your approval decision was submitted.");
  if (event.kind === "memory_proposed")
    return t(
      "请在共享记忆中审阅 Agent 的提案。",
      "Review the agent’s proposal in Shared memory.",
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
        {t("此操作需要你的授权", "Your approval is required")}
      </h3>
      <p>
        {t(
          "以下内容由 Agent 提供。核对实际命令和作用范围后再选择；超时将拒绝。",
          "The agent supplied this request. Review its command and scope before deciding. Requests are denied on timeout.",
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
              ? t("仅允许这一次", "Allow once")
              : option.name === "Deny"
                ? t("拒绝", "Deny")
                : option.name}
            <small>
              {option.kind === "allow_once"
                ? t("单次授权", "One-time permission")
                : option.kind === "reject_once"
                  ? t("不执行此操作", "Do not execute")
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
}: {
  eyebrow: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}
