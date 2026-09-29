import type { AgentEvent, Language, Mutate, Run, Translate } from "./types";
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
};
export function executionSteps(events: AgentEvent[]): Step[] {
  const steps: Step[] = [];
  const keyed = new Map<string, Step>();
  for (const event of events) {
    const p = payload(event);
    if (
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
    } else if (event.kind === "agent_message_chunk") {
      let step = steps.at(-1);
      if (step?.kind !== "message") {
        step = { id: event.id, kind: "message", text: "" };
        steps.push(step);
      }
      step.text += eventText(event.payload);
    }
  }
  return steps;
}

export default function TaskTimeline({
  runs,
  events,
  agentName,
  t,
  lang,
  busy,
  mutate,
}: {
  runs: Run[];
  events: AgentEvent[];
  agentName: string;
  t: Translate;
  lang: Language;
  busy: boolean;
  mutate: Mutate;
}) {
  const tasks = new Map(runs.map((r) => [r.id, { ...r }]));
  const grouped = new Map<string, AgentEvent[]>();
  const orphaned: AgentEvent[] = [];
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
          const steps = executionSteps(runEvents);
          const modelEvent = runEvents
            .filter((event) => event.kind === "model_info")
            .at(-1);
          const modelInfo = modelEvent ? payload(modelEvent) : {};
          const answerEvent = runEvents
            .slice()
            .reverse()
            .find((e) => e.kind === "assistant_message");
          const answer =
            run.result || (answerEvent ? eventText(answerEvent.payload) : "");
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
              ? t("任务已完成", "Task completed")
              : run.status === "running"
                ? reconnecting
                  ? t("连接中断 · 正在重连", "Connection lost · reconnecting")
                  : waiting
                    ? t("等待授权", "Awaiting approval")
                    : t("任务执行中", "Task running")
                : run.status === "queued"
                  ? t("任务排队中", "Task queued")
                  : run.status === "failed"
                    ? t("任务失败", "Task failed")
                    : run.status === "loading"
                      ? t("正在读取任务…", "Loading task…")
                      : t("任务", "Task") + " · " + statusLabel(run.status, t);
          // A terminal result takes precedence over chunks and survives reopening the app.
          const streaming =
            !answer && run.status === "running"
              ? steps.filter((s) => s.kind === "message").at(-1)?.text
              : "";
          return (
            <article className="task-turn" key={run.id}>
              {run.prompt && (
                <div className="task-prompt">
                  <div className="event-meta">
                    <span>
                      {run.origin === "human"
                        ? t("你", "You")
                        : t("协作任务", "Delegated task")}
                    </span>
                    <DateText date={run.created_at} lang={lang} />
                  </div>
                  <pre>{run.prompt}</pre>
                </div>
              )}
              <div className="task-progress-row">
                <details className={`task-progress ${run.status}`}>
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
                          "客户端返回的模型标识",
                          "Model identifier reported by the CLI",
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
                    aria-label={t("实时执行过程", "Live execution")}
                  >
                    {!steps.length && (
                      <p className="muted">
                        {run.status === "queued"
                          ? t("等待开始", "Waiting to start")
                          : active
                            ? t("等待 Agent 输出…", "Waiting for agent output…")
                            : t("没有执行记录", "No execution details")}
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
                              {step.name || t("工具执行", "Tool execution")}
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
                              ? t("思考", "Thinking")
                              : agentName}
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
                    {t("取消", "Cancel")}
                  </button>
                )}
              </div>
              {run.error && (
                <p className="inline-error" role="status">
                  {errorMessage(run.error, t)}
                </p>
              )}
              {(answer || streaming) && (
                <div className="task-answer">
                  <div className="event-meta">
                    <span>{agentName}</span>
                    {!answer && <span className="status-dot" />}
                  </div>
                  <pre>{answer || streaming}</pre>
                </div>
              )}
            </article>
          );
        })}
      {orphaned
        .filter(
          (e) =>
            !["run_started", "run_finished", "token_usage"].includes(e.kind),
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
