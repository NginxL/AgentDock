import * as uiMessages from "../messages";
import { useState } from "react";
import type { Mutate, ProjectTask, Translate } from "../types";
import { Icon } from "../ui";
export default function TaskSettings({
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
        <h3>{t(...uiMessages.tasksettings_edit_requirements_63057f)}</h3>
        <button
          type="button"
          className="icon-button"
          aria-label={t(...uiMessages.tasksettings_close_editor_39d65e)}
          onClick={close}
        >
          <Icon name="close" />
        </button>
      </div>
      <label>
        {t(...uiMessages.tasksettings_task_title_a240b7)}
        <input
          required
          maxLength={160}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <label>
        {t(...uiMessages.tasksettings_goal_b574a3)}
        <textarea
          required
          rows={3}
          maxLength={16000}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
        />
      </label>
      <label>
        {t(...uiMessages.tasksettings_acceptance_criteria_one_per_line_d65916)}
        <textarea
          required
          rows={3}
          maxLength={8000}
          value={criteria}
          onChange={(e) => setCriteria(e.target.value)}
        />
      </label>
      <label>
        {t(...uiMessages.tasksettings_acceptance_d68747)}
        <select
          value={policy}
          onChange={(e) => setPolicy(e.target.value as "owner" | "human")}
        >
          <option value="owner">
            {t(
              ...uiMessages.tasksettings_owner_verifies_every_criterion_d3c5eb,
            )}
          </option>
          <option value="human">
            {t(...uiMessages.tasksettings_i_confirm_after_verification_b3f540)}
          </option>
        </select>
      </label>
      <label className="task-checkbox">
        <input
          type="checkbox"
          checked={review}
          onChange={(e) => setReview(e.target.checked)}
        />
        {t(...uiMessages.tasksettings_require_another_agent_to_review_bb74d3)}
      </label>
      <p className="muted">
        {t(
          ...uiMessages.tasksettings_changed_requirements_need_fresh_verification_e3ab2b,
        )}
      </p>
      <button className="primary" disabled={busy}>
        {t(...uiMessages.tasksettings_save_requirements_fa0b15)}
      </button>
    </form>
  );
}
