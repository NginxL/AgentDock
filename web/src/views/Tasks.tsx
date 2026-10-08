import { useEffect, useRef, useState } from "react";
import { request } from "../api";
import type {
  AgentEvent,
  DockState,
  Language,
  Mutate,
  ProjectTask,
  Session,
  TaskDetail,
  TaskIntent,
  TaskQuestion,
  Translate,
} from "../types";
import { ApprovalCard, DateText, Empty, Icon } from "../ui";
import { followSession } from "../sessionEvents";
import TaskTimeline from "../TaskTimeline";
import InferenceControls from "../InferenceControls";
import { SessionAccountControls } from "../AccountSelection";
import Messages from "./Messages";

export function taskLabel(status: string, t: Translate) {
  const labels: Record<string, [string, string]> = {
    draft: ["待开始", "Draft"],
    active: ["进行中", "In progress"],
    waiting_input: ["待你确认", "Needs your input"],
    review: ["待验收", "Ready for acceptance"],
    completed: ["已完成", "Completed"],
    interrupted: ["执行中断", "Interrupted"],
    paused: ["已暂停", "Paused"],
    cancelled: ["已取消", "Cancelled"],
    archived: ["已归档", "Archived"],
    recorded: ["已记录", "Recorded"],
    queued: ["已排队", "Queued"],
    pending: ["正在送达", "Sending"],
    accepted: ["已送达", "Delivered"],
    processed: ["本轮已结束", "Turn ended"],
    rejected: ["未送达", "Rejected"],
    unknown: ["送达待核实", "Delivery unknown"],
  };
  return labels[status] ? t(...labels[status]) : status;
}

type Common = { state: DockState; t: Translate; busy: boolean; mutate: Mutate };

export function TaskForm({
  state,
  t,
  busy,
  mutate,
  projectID: initialProject,
  source,
  close,
  onCreated,
}: Common & {
  projectID?: string;
  source?: Session;
  close: () => void;
  onCreated: (task: ProjectTask) => void;
}) {
  const [projectID, setProjectID] = useState(
    initialProject ?? source?.project_id ?? "",
  );
  const [title, setTitle] = useState(source?.title ?? "");
  const [goal, setGoal] = useState("");
  const [criteria, setCriteria] = useState("");
  const [ownerID, setOwnerID] = useState("");
  const [intent, setIntent] = useState<TaskIntent>("develop");
  const [policy, setPolicy] = useState("owner");
  const [review, setReview] = useState(false);
  const [workspace, setWorkspace] = useState("shared");
  const submitting = useRef(false);
  const agents = state.agents.filter(
    (a) =>
      a.project_id === projectID &&
      (a.environment_id ?? "local") ===
        (state.projects.find((p) => p.id === projectID)?.environment_id ??
          "local"),
  );
  const chosen = agents.some((a) => a.id === ownerID)
    ? ownerID
    : (agents[0]?.id ?? "");
  return (
    <section className="panel task-create">
      <div className="panel-heading">
        <h2>
          {source
            ? t("转为项目任务", "Create task from conversation")
            : t("新建任务", "New task")}
        </h2>
        <button
          className="icon-button"
          type="button"
          onClick={close}
          aria-label={t("关闭新建任务", "Close new task")}
        >
          <Icon name="close" />
        </button>
      </div>
      <form
        className="task-form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (submitting.current || busy) return;
          submitting.current = true;
          try {
            let created: ProjectTask | undefined;
            await mutate(
              "/api/tasks",
              {
                project_id: projectID,
                title,
                goal,
                criteria,
                owner_id: chosen,
                acceptance_policy: policy,
                review_required: review,
                workspace_mode: workspace,
                source_session_id: source?.id,
              },
              (task: ProjectTask) => {
                created = task;
              },
            );
            if (created) {
              if (intent !== "record")
                await mutate(`/api/tasks/${created.id}/inputs`, {
                  body: goal,
                  intent,
                  request_id: crypto.randomUUID(),
                });
              onCreated(created);
            }
          } finally {
            submitting.current = false;
          }
        }}
      >
        {!initialProject && (
          <label>
            {t("项目", "Project")}
            <select
              required
              value={projectID}
              onChange={(e) => setProjectID(e.target.value)}
            >
              <option value="">{t("选择项目", "Choose project")}</option>
              {state.projects
                .filter(
                  (p) => !source?.project_id || p.id === source.project_id,
                )
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
            </select>
          </label>
        )}
        <label>
          {t("任务名称", "Task title")}
          <input
            required
            maxLength={160}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <label>
          {t("目标", "Goal")}
          <textarea
            required
            maxLength={16000}
            rows={3}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
        </label>
        <label>
          {t("验收要求（每行一项）", "Acceptance criteria (one per line)")}
          <textarea
            required
            maxLength={8000}
            rows={3}
            value={criteria}
            onChange={(e) => setCriteria(e.target.value)}
            placeholder={t(
              "例如：登录失败时显示清晰提示，并验证成功与失败两种情况",
              "Example: Show a clear login error and verify success and failure cases",
            )}
          />
        </label>
        <div className="task-form-grid">
          <label>
            {t("负责人", "Task owner")}
            <select
              required
              value={chosen}
              onChange={(e) => setOwnerID(e.target.value)}
            >
              {!agents.length && (
                <option value="">
                  {t(
                    "先在项目中添加 Agent",
                    "Add an Agent to this project first",
                  )}
                </option>
              )}
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("处理方式", "Action")}
            <select
              value={intent}
              onChange={(e) => setIntent(e.target.value as TaskIntent)}
            >
              <option value="develop">{t("直接执行", "Execute")}</option>
              <option value="discuss">{t("先讨论", "Discuss first")}</option>
              <option value="record">{t("仅记录", "Save draft")}</option>
            </select>
          </label>
        </div>
        <details>
          <summary>{t("任务设置", "Task settings")}</summary>
          <div className="task-form-grid">
            <label>
              {t("验收方式", "Acceptance")}
              <select
                value={policy}
                onChange={(e) => setPolicy(e.target.value)}
              >
                <option value="owner">
                  {t("负责人逐项验证后完成", "Owner verifies every criterion")}
                </option>
                <option value="human">
                  {t("验证后由我确认", "I confirm after verification")}
                </option>
              </select>
            </label>
            <label>
              {t("工作文件", "Working files")}
              <select
                value={workspace}
                onChange={(e) => setWorkspace(e.target.value)}
              >
                <option value="shared">
                  {t("共用项目目录", "Shared project directory")}
                </option>
                <option value="worktree">
                  {t("独立 Git 工作区", "Isolated Git worktrees")}
                </option>
              </select>
            </label>
            <label className="task-checkbox">
              <input
                type="checkbox"
                checked={review}
                onChange={(e) => setReview(e.target.checked)}
              />
              {t(
                "完成前需要另一位 Agent 审查",
                "Require another Agent to review",
              )}
            </label>
          </div>
          {workspace === "worktree" && (
            <p className="muted">
              {t(
                "从干净的项目提交创建独立工作区。负责人负责整合各 Agent 的提交，项目原目录保持原状。",
                "Creates worktrees from a clean project commit. The owner integrates teammate commits; the original checkout stays in place.",
              )}
            </p>
          )}
        </details>
        <div className="button-row">
          <button type="button" className="secondary" onClick={close}>
            {t("取消", "Cancel")}
          </button>
          <button
            className="primary"
            disabled={
              busy || !chosen || (!state.runtime.enabled && intent !== "record")
            }
          >
            {intent === "record"
              ? t("保存任务", "Save task")
              : intent === "discuss"
                ? t("创建并讨论", "Create and discuss")
                : t("创建并执行", "Create and execute")}
          </button>
        </div>
      </form>
    </section>
  );
}

export default function Tasks({
  state,
  t,
  busy,
  mutate,
  projectID,
  taskID,
  onSelect,
  token,
  demo,
  lang,
}: Common & {
  projectID: string;
  taskID: string;
  onSelect: (id: string) => void;
  token: string;
  demo: boolean;
  lang: Language;
}) {
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState("open");
  const [legacy, setLegacy] = useState(false);
  const tasks = (state.tasks ?? []).filter(
    (task) => task.project_id === projectID,
  );
  const chosen = tasks.find((task) => task.id === taskID);
  if (chosen)
    return (
      <TaskPage
        key={chosen.id}
        task={chosen}
        state={state}
        t={t}
        busy={busy}
        mutate={mutate}
        token={token}
        demo={demo}
        lang={lang}
        back={() => onSelect("")}
      />
    );
  const questions = (state.task_questions ?? []).filter((q) =>
    tasks.some(
      (task) =>
        task.id === q.task_id &&
        !["cancelled", "archived"].includes(task.status),
    ),
  );
  return (
    <>
      <div className="page-title">
        <h2>{t("任务", "Tasks")}</h2>
        <button
          className="primary"
          aria-expanded={creating}
          onClick={() => setCreating(!creating)}
        >
          <Icon name="plus" />
          {t("新建任务", "New task")}
        </button>
      </div>
      {creating && (
        <TaskForm
          state={state}
          t={t}
          busy={busy}
          mutate={mutate}
          projectID={projectID}
          close={() => setCreating(false)}
          onCreated={(task) => {
            setCreating(false);
            onSelect(task.id);
          }}
        />
      )}
      {questions.length > 0 && (
        <section className="task-inbox panel">
          <h3>
            {t("待你确认", "Needs your input")} · {questions.length}
          </h3>
          {questions.map((q) => (
            <button
              key={q.id}
              className="task-inbox-item"
              onClick={() => onSelect(q.task_id)}
            >
              <strong>
                {tasks.find((task) => task.id === q.task_id)?.title}
              </strong>
              <span>{q.question}</span>
              <Icon name="arrow" />
            </button>
          ))}
        </section>
      )}
      <div
        className="task-filters"
        role="group"
        aria-label={t("筛选任务", "Filter tasks")}
      >
        {(["open", "all", "archived"] as const).map((key) => (
          <button
            key={key}
            className={filter === key ? "selected" : ""}
            aria-pressed={filter === key}
            onClick={() => setFilter(key)}
          >
            {key === "open"
              ? t("未完成", "Open")
              : key === "all"
                ? t("全部", "All")
                : t("已归档", "Archived")}
          </button>
        ))}
      </div>
      <div className="project-task-list">
        {tasks
          .filter(
            (task) =>
              filter === "all" ||
              (filter === "archived"
                ? task.status === "archived"
                : !["completed", "cancelled", "archived"].includes(
                    task.status,
                  )),
          )
          .map((task) => (
            <button
              key={task.id}
              className="project-task-card"
              onClick={() => onSelect(task.id)}
            >
              <span>
                <strong>{task.title}</strong>
                <small>
                  {state.agents.find((a) => a.id === task.owner_id)?.name ??
                    t("负责人已移除", "Owner removed")}{" "}
                  · <DateText date={task.updated_at} lang={lang} />
                </small>
              </span>
              <span
                className={`pill ${task.status === "completed" ? "good" : ""}`}
              >
                {taskLabel(task.status, t)}
              </span>
              <Icon name="arrow" />
            </button>
          ))}
        {!tasks.length && (
          <div className="panel">
            <Empty
              icon="work"
              title={t("创建第一项任务", "Create your first task")}
            >
              {null}
            </Empty>
          </div>
        )}
      </div>
      {(state.messages.some((m) => m.project_id === projectID) ||
        state.sessions.some(
          (s) => s.project_id === projectID && !s.work_task_id,
        )) && (
        <div className="task-legacy">
          <button
            className="text-button"
            aria-expanded={legacy}
            onClick={() => setLegacy(!legacy)}
          >
            {t("派工记录", "Dispatch history")}{" "}
            <Icon name={legacy ? "close" : "arrow"} />
          </button>
          {legacy && (
            <Messages
              state={state}
              t={t}
              lang={lang}
              projectID={projectID}
              agents={state.agents.filter((a) => a.project_id === projectID)}
              busy={busy}
              mutate={mutate}
            />
          )}
        </div>
      )}
    </>
  );
}

function TaskSettings({
  task,
  t,
  busy,
  mutate,
  close,
}: {
  task: ProjectTask;
  t: Translate;
  busy: boolean;
  mutate: Mutate;
  close: () => void;
}) {
  const [title, setTitle] = useState(task.title),
    [goal, setGoal] = useState(task.goal),
    [criteria, setCriteria] = useState(task.criteria);
  const [policy, setPolicy] = useState(task.acceptance_policy),
    [review, setReview] = useState(!!task.review_required);
  return (
    <form
      className="panel task-form"
      onSubmit={async (e) => {
        e.preventDefault();
        await mutate(
          `/api/tasks/${task.id}/settings`,
          {
            title,
            goal,
            criteria,
            acceptance_policy: policy,
            review_required: review,
          },
          close,
        );
      }}
    >
      <div className="panel-heading">
        <h3>{t("编辑任务要求", "Edit requirements")}</h3>
        <button
          type="button"
          className="icon-button"
          aria-label={t("关闭编辑", "Close editor")}
          onClick={close}
        >
          <Icon name="close" />
        </button>
      </div>
      <label>
        {t("任务名称", "Task title")}
        <input
          required
          maxLength={160}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <label>
        {t("目标", "Goal")}
        <textarea
          required
          rows={3}
          maxLength={16000}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
        />
      </label>
      <label>
        {t("验收要求（每行一项）", "Acceptance criteria (one per line)")}
        <textarea
          required
          rows={3}
          maxLength={8000}
          value={criteria}
          onChange={(e) => setCriteria(e.target.value)}
        />
      </label>
      <label>
        {t("验收方式", "Acceptance")}
        <select
          value={policy}
          onChange={(e) => setPolicy(e.target.value as "owner" | "human")}
        >
          <option value="owner">
            {t("负责人逐项验证后完成", "Owner verifies every criterion")}
          </option>
          <option value="human">
            {t("验证后由我确认", "I confirm after verification")}
          </option>
        </select>
      </label>
      <label className="task-checkbox">
        <input
          type="checkbox"
          checked={review}
          onChange={(e) => setReview(e.target.checked)}
        />
        {t("完成前需要另一位 Agent 审查", "Require another Agent to review")}
      </label>
      <p className="muted">
        {t(
          "修改要求后，需要按新要求重新验证。",
          "Changed requirements need fresh verification.",
        )}
      </p>
      <button className="primary" disabled={busy}>
        {t("保存要求", "Save requirements")}
      </button>
    </form>
  );
}

function Question({
  question,
  taskID,
  t,
  busy,
  mutate,
}: {
  question: TaskQuestion;
  taskID: string;
  t: Translate;
  busy: boolean;
  mutate: Mutate;
}) {
  const [answer, setAnswer] = useState("");
  return (
    <form
      className="task-question"
      onSubmit={async (e) => {
        e.preventDefault();
        await mutate(
          `/api/tasks/${taskID}/questions/${question.id}/answer`,
          { answer },
          () => setAnswer(""),
        );
      }}
    >
      <strong>{question.question}</strong>
      {question.options.length > 0 && (
        <div className="task-answer-options">
          {question.options.map((option) => (
            <button
              className={answer === option ? "selected" : ""}
              type="button"
              key={option}
              onClick={() => setAnswer(option)}
            >
              {option}
            </button>
          ))}
        </div>
      )}
      <label className="sr-only" htmlFor={`answer-${question.id}`}>
        {t("你的决定", "Your decision")}
      </label>
      <textarea
        id={`answer-${question.id}`}
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        maxLength={8000}
        rows={2}
      />
      <button className="primary" disabled={busy || !answer.trim()}>
        {t("确认并继续", "Answer and continue")}
      </button>
    </form>
  );
}

function TaskPage({
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
            t("任务读取失败，请重试", "Could not load this task. Retry."),
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
          aria-label={t("返回任务列表", "Back to tasks")}
        >
          <Icon name="back" />
        </button>
        <h2>{current.title}</h2>
        <span className="pill">{taskLabel(current.status, t)}</span>
      </header>
      {error && (
        <div role="alert" className="alert">
          {error}
          <button onClick={refresh}>{t("重试", "Retry")}</button>
        </div>
      )}
      <section className="panel task-brief">
        <p className="task-prose">{current.goal}</p>
        <details>
          <summary>
            {t("验收要求与任务设置", "Acceptance criteria and task settings")}
          </summary>
          <ul>
            {current.criteria.split("\n").map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <p>
            {t("验收方式", "Acceptance")}：
            {current.acceptance_policy === "owner"
              ? t("负责人逐项验证", "Owner verifies every criterion")
              : t("由我确认", "Human confirmation")}
          </p>
          <p>
            {current.review_required
              ? t("需要独立审查", "Independent review required")
              : t("负责人按需安排审查", "Owner arranges review as needed")}
          </p>
          <p>
            {current.workspace_mode === "shared"
              ? t("共用项目目录", "Shared project directory")
              : t("独立 Git 工作区", "Isolated Git worktrees")}
          </p>
        </details>
        {!closed && (
          <button
            className="text-button"
            disabled={live}
            aria-expanded={editing}
            onClick={() => setEditing(!editing)}
          >
            {t("编辑任务要求", "Edit requirements")}{" "}
            <Icon name={editing ? "close" : "edit"} />
          </button>
        )}
        <div className="task-controls">
          <label>
            {t("负责人", "Task owner")}
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
                ? t("更换负责人并继续", "Reassign and continue")
                : t("接续任务", "Continue task")}
            </button>
          )}
          {!closed && current.status !== "paused" && (
            <button
              className="secondary"
              disabled={busy || !state.runtime.enabled}
              onClick={() => void change(`/api/tasks/${task.id}/pause`, {})}
            >
              {t("暂停任务", "Pause task")}
            </button>
          )}
          {!closed && (
            <button
              className="text-button danger"
              disabled={busy || !state.runtime.enabled}
              onClick={() => void change(`/api/tasks/${task.id}/cancel`, {})}
            >
              {t("取消任务", "Cancel task")}
            </button>
          )}
          {["completed", "cancelled"].includes(current.status) && (
            <>
              <button
                className="secondary"
                disabled={busy}
                onClick={() => void change(`/api/tasks/${task.id}/reopen`, {})}
              >
                {t("重新打开", "Reopen")}
              </button>
              <button
                className="text-button"
                disabled={busy}
                onClick={() => void change(`/api/tasks/${task.id}/archive`, {})}
              >
                {t("归档", "Archive")}
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
            <h3>{t("待你确认", "Needs your input")}</h3>
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
            <h3>{t("交付结果", "Delivery")}</h3>
            <span className="pill">
              {delivery.status === "accepted"
                ? t("已验收", "Accepted")
                : t("待验收", "Needs acceptance")}
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
              <h4>{t("成果文件与链接", "Files and links")}</h4>
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
              <h4>{t("遗留问题", "Remaining issues")}</h4>
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
              {t("确认验收", "Accept delivery")}
            </button>
          )}
        </section>
      )}
      {!delivery && lastReply && !live && (
        <section className="panel task-delivery">
          <h3>
            {current.intent === "discuss"
              ? t("讨论结果", "Discussion result")
              : t("当前进展", "Current progress")}
          </h3>
          <p className="task-prose">{lastReply.result}</p>
        </section>
      )}
      {detail?.reviews?.length ? (
        <details className="panel">
          <summary>{t("审查结果", "Review reports")}</summary>
          {detail.reviews.map((review) => (
            <article key={review.id}>
              <strong>
                {review.verdict === "approved"
                  ? t("审查通过", "Approved")
                  : review.verdict === "changes_requested"
                    ? t("需要修改", "Changes requested")
                    : t("尚未验证", "Unverified")}
              </strong>
              <p className="task-prose">{review.summary}</p>
            </article>
          ))}
        </details>
      ) : null}
      {detail && detail.questions.some((q) => q.status === "answered") && (
        <details className="panel">
          <summary>{t("已确认的决定", "Saved decisions")}</summary>
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
            <h3>{t("执行过程", "Execution")}</h3>
            <button
              className="text-button"
              aria-expanded={watch}
              onClick={() => setWatch(!watch)}
            >
              {watch
                ? t("收起过程", "Hide process")
                : t("查看过程", "Show process")}
              <Icon name={watch ? "close" : "arrow"} />
            </button>
          </div>
          {watch && (
            <>
              <label>
                {t("会话", "Conversation")}
                <select
                  value={selected?.id ?? ""}
                  onChange={(e) => setSessionID(e.target.value)}
                >
                  {sessions.map((s, i) => (
                    <option key={s.id} value={s.id}>
                      {state.agents.find((a) => a.id === s.agent_id)?.name ??
                        t("已移除的 Agent", "Removed agent")}{" "}
                      ·{" "}
                      {s.task_role === "owner"
                        ? t("负责人", "Owner")
                        : s.task_role === "reviewer"
                          ? t("审查", "Review")
                          : t("执行", "Worker")}{" "}
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
            {t("补充需求或继续任务", "Add requirements or continue")}
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
              <span className="sr-only">{t("处理方式", "Action")}</span>
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
                  {t("直接执行", "Execute")}
                </option>
                <option
                  value="discuss"
                  disabled={live && current.intent !== "discuss"}
                >
                  {t("先讨论", "Discuss first")}
                </option>
                <option value="record">{t("仅记录", "Save note")}</option>
              </select>
            </label>
            {(live || action === "steer") && intent !== "record" && (
              <label>
                <span className="sr-only">{t("发送时机", "Input timing")}</span>
                <select
                  value={action}
                  onChange={(e) => setAction(e.target.value)}
                >
                  <option value="queue">{t("排队处理", "Queue")}</option>
                  <option value="steer" disabled={!detail?.can_steer_run_id}>
                    {t("立即调整", "Adjust now")}
                  </option>
                </select>
              </label>
            )}
            {steeringUnavailable && (
              <span className="muted">
                {t(
                  "本轮已结束或暂不支持调整，请选择排队处理",
                  "This turn ended or cannot be adjusted. Choose Queue to continue.",
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
                ? t("记录", "Save")
                : live && action === "queue"
                  ? t("加入队列", "Queue")
                  : t("发送", "Send")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
