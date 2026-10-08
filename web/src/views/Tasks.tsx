import * as uiMessages from "../messages";
import { useState } from "react";
import type { Language } from "../types";
import { DateText, Empty, Icon } from "../ui";
import Messages from "./Messages";
import { TaskForm } from "./TaskForm";
import TaskPage from "./TaskPage";
import { taskLabel, type Common } from "./taskShared";
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
        <h2>{t(...uiMessages.tasks_tasks_4d26bc)}</h2>
        <button
          className="primary"
          aria-expanded={creating}
          onClick={() => setCreating(!creating)}
        >
          <Icon name="plus" />
          {t(...uiMessages.tasks_new_task_01f649)}
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
            {t(...uiMessages.tasks_needs_your_input_3caf95)} ·{" "}
            {questions.length}
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
        aria-label={t(...uiMessages.tasks_filter_tasks_22b52a)}
      >
        {(["open", "all", "archived"] as const).map((key) => (
          <button
            key={key}
            className={filter === key ? "selected" : ""}
            aria-pressed={filter === key}
            onClick={() => setFilter(key)}
          >
            {key === "open"
              ? t(...uiMessages.tasks_open_d73635)
              : key === "all"
                ? t(...uiMessages.tasks_all_fa9560)
                : t(...uiMessages.tasks_archived_c1c10b)}
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
                    t(...uiMessages.tasks_owner_removed_b81010)}{" "}
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
              title={t(...uiMessages.tasks_create_your_first_task_76db68)}
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
            {t(...uiMessages.tasks_dispatch_history_b6e370)}{" "}
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
export { TaskForm } from "./TaskForm";
export { taskLabel } from "./taskShared";
