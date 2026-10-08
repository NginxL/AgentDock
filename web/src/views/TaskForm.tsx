import * as uiMessages from "../messages";
import { useDraft } from "../useDraft";
import { useRef, useState } from "react";
import type { ProjectTask, Session, TaskIntent } from "../types";
import { Icon } from "../ui";
import { type Common } from "./taskShared";
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
  const draft = useDraft({
    projectID: initialProject ?? source?.project_id ?? "",
    title: source?.title ?? "",
    goal: "",
    criteria: "",
    ownerID: "",
    intent: "develop" as TaskIntent,
    policy: "owner",
    review: false,
    workspace: "shared",
  });
  const {
    projectID,
    title,
    goal,
    criteria,
    ownerID,
    intent,
    policy,
    review,
    workspace,
  } = draft.values;
  const setProjectID = draft.set("projectID");
  const setTitle = draft.set("title");
  const setGoal = draft.set("goal");
  const setCriteria = draft.set("criteria");
  const setOwnerID = draft.set("ownerID");
  const setIntent = draft.set("intent");
  const setPolicy = draft.set("policy");
  const setReview = draft.set("review");
  const setWorkspace = draft.set("workspace");

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
            ? t(...uiMessages.taskform_create_task_from_conversation_0ec088)
            : t(...uiMessages.taskform_new_task_01f649)}
        </h2>
        <button
          className="icon-button"
          type="button"
          onClick={close}
          aria-label={t(...uiMessages.taskform_close_new_task_117712)}
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
            {t(...uiMessages.taskform_project_de4129)}
            <select
              required
              value={projectID}
              onChange={(e) => setProjectID(e.target.value)}
            >
              <option value="">
                {t(...uiMessages.taskform_choose_project_b6d551)}
              </option>
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
          {t(...uiMessages.taskform_task_title_a240b7)}
          <input
            required
            maxLength={160}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <label>
          {t(...uiMessages.taskform_goal_b574a3)}
          <textarea
            required
            maxLength={16000}
            rows={3}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
        </label>
        <label>
          {t(...uiMessages.taskform_acceptance_criteria_one_per_line_d65916)}
          <textarea
            required
            maxLength={8000}
            rows={3}
            value={criteria}
            onChange={(e) => setCriteria(e.target.value)}
            placeholder={t(
              ...uiMessages.taskform_example_show_a_clear_login_error_and_verify_s_33473d,
            )}
          />
        </label>
        <div className="task-form-grid">
          <label>
            {t(...uiMessages.taskform_task_owner_4079a1)}
            <select
              required
              value={chosen}
              onChange={(e) => setOwnerID(e.target.value)}
            >
              {!agents.length && (
                <option value="">
                  {t(
                    ...uiMessages.taskform_add_an_agent_to_this_project_first_5fee18,
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
            {t(...uiMessages.taskform_action_56a0d2)}
            <select
              value={intent}
              onChange={(e) => setIntent(e.target.value as TaskIntent)}
            >
              <option value="develop">
                {t(...uiMessages.taskform_execute_91f736)}
              </option>
              <option value="discuss">
                {t(...uiMessages.taskform_discuss_first_33de82)}
              </option>
              <option value="record">
                {t(...uiMessages.taskform_save_draft_846a6d)}
              </option>
            </select>
          </label>
        </div>
        <details>
          <summary>{t(...uiMessages.taskform_task_settings_0ba2d2)}</summary>
          <div className="task-form-grid">
            <label>
              {t(...uiMessages.taskform_acceptance_d68747)}
              <select
                value={policy}
                onChange={(e) => setPolicy(e.target.value)}
              >
                <option value="owner">
                  {t(
                    ...uiMessages.taskform_owner_verifies_every_criterion_d3c5eb,
                  )}
                </option>
                <option value="human">
                  {t(
                    ...uiMessages.taskform_i_confirm_after_verification_b3f540,
                  )}
                </option>
              </select>
            </label>
            <label>
              {t(...uiMessages.taskform_working_files_7486aa)}
              <select
                value={workspace}
                onChange={(e) => setWorkspace(e.target.value)}
              >
                <option value="shared">
                  {t(...uiMessages.taskform_shared_project_directory_d3451f)}
                </option>
                <option value="worktree">
                  {t(...uiMessages.taskform_isolated_git_worktrees_68ea12)}
                </option>
              </select>
            </label>
            <label className="task-checkbox">
              <input
                type="checkbox"
                checked={review}
                onChange={(e) => setReview(e.target.checked)}
              />
              {t(...uiMessages.taskform_require_another_agent_to_review_bb74d3)}
            </label>
          </div>
          {workspace === "worktree" && (
            <p className="muted">
              {t(
                ...uiMessages.taskform_creates_worktrees_from_a_clean_project_commit_d9b784,
              )}
            </p>
          )}
        </details>
        <div className="button-row">
          <button type="button" className="secondary" onClick={close}>
            {t(...uiMessages.taskform_cancel_68f563)}
          </button>
          <button
            className="primary"
            disabled={
              busy || !chosen || (!state.runtime.enabled && intent !== "record")
            }
          >
            {intent === "record"
              ? t(...uiMessages.taskform_save_task_2994ef)
              : intent === "discuss"
                ? t(...uiMessages.taskform_create_and_discuss_e862f9)
                : t(...uiMessages.taskform_create_and_execute_36466c)}
          </button>
        </div>
      </form>
    </section>
  );
}
