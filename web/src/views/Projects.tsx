import * as uiMessages from "../messages";
import type { DockState, Project, Translate } from "../types";
import type { ProjectView } from "../navigation";
import { Empty, Icon, isArchived } from "../ui";

export function ProjectHeader({
  project,
  projects,
  view,
  pending,
  creating,
  onCreate,
  onSelect,
  onView,
  t,
  onPolicy,
  busy,
}: {
  project?: Project;
  projects: Project[];
  view: ProjectView;
  pending: number;
  creating: boolean;
  onCreate: () => void;
  onSelect: (id: string) => void;
  onView: (view: ProjectView) => void;
  t: Translate;
  onPolicy?: (project: Project) => void;
  busy?: boolean;
}) {
  return (
    <section className="project-header">
      <div className="page-heading">
        <div className="project-title">
          {project && (
            <button
              className="icon-button back-to-agents"
              aria-label={t(...uiMessages.projects_back_to_projects_f5e01a)}
              onClick={() => onSelect("")}
            >
              <span aria-hidden="true">←</span>
            </button>
          )}
          <h1>{project?.name ?? t(...uiMessages.projects_projects_23574c)}</h1>
        </div>
        {project ? (
          <select
            className="project-picker"
            aria-label={t(...uiMessages.projects_switch_project_7f2ed8)}
            value={project.id}
            onChange={(e) => onSelect(e.target.value)}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        ) : (
          <button
            className="primary"
            aria-expanded={creating}
            aria-controls="project-form"
            onClick={onCreate}
          >
            <Icon name="plus" size={18} />
            {t(...uiMessages.projects_new_project_213635)}
          </button>
        )}
      </div>
      {project && onPolicy && (
        <label className="account-check">
          <input
            type="checkbox"
            checked={!!project.confirm_dispatch}
            disabled={busy}
            onChange={() => onPolicy(project)}
          />
          {t(...uiMessages.projects_ask_me_before_agents_delegate_work_16ef3f)}
        </label>
      )}
      {project && (
        <nav
          className="project-tabs"
          aria-label={t(...uiMessages.projects_project_navigation_d53bc5)}
        >
          {(
            [
              ["tasks", "任务", "Tasks"],
              ["agents", "Agent", "Agents"],
              ["memory", "记忆", "Memory"],
            ] as const
          ).map(([key, zh, en]) => (
            <button
              key={key}
              className={view === key ? "selected" : ""}
              aria-current={view === key ? "page" : undefined}
              aria-label={t(zh, en)}
              onClick={() => onView(key)}
            >
              {t(zh, en)}
              {key === "memory" && pending > 0 && (
                <span className="nav-badge">{pending}</span>
              )}
            </button>
          ))}
        </nav>
      )}
    </section>
  );
}

export function ProjectList({
  state,
  onSelect,
  onCreate,
  creating,
  t,
}: {
  state: DockState;
  onSelect: (id: string) => void;
  onCreate: () => void;
  creating: boolean;
  t: Translate;
}) {
  if (!state.projects.length)
    return (
      <section className="panel">
        <Empty
          icon="folder"
          title={t(...uiMessages.projects_no_projects_yet_611f30)}
        >
          {null}
        </Empty>
        <button
          className="primary empty-action"
          aria-expanded={creating}
          aria-controls="project-form"
          onClick={onCreate}
        >
          {t(...uiMessages.projects_create_your_first_project_41d98d)}
        </button>
      </section>
    );
  return (
    <div className="project-grid">
      {state.projects.map((project) => {
        const agents = state.agents.filter(
          (a) => a.project_id === project.id,
        ).length;
        const memories = state.memories.filter(
          (m) => m.project_id === project.id && !isArchived(m),
        ).length;
        const pending = state.proposals.filter(
          (p) => p.project_id === project.id && p.status === "pending",
        ).length;
        return (
          <button
            className="project-card"
            key={project.id}
            aria-label={t(
              `打开项目 ${project.name}`,
              `Open project ${project.name}`,
            )}
            onClick={() => onSelect(project.id)}
          >
            <span className="project-card-icon">
              <Icon name="folder" />
            </span>
            <span className="project-card-body">
              <strong>{project.name}</strong>
              <span>
                {agents} Agent ·{" "}
                {t(`${memories} 条记忆`, `${memories} memories`)}
              </span>
              {pending > 0 && (
                <span className="project-review-count">
                  {t(
                    `${pending} 条记忆待审阅`,
                    `${pending} memories to review`,
                  )}
                </span>
              )}
            </span>
            <Icon name="arrow" size={18} />
          </button>
        );
      })}
    </div>
  );
}
