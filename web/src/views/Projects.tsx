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
}) {
  return (
    <section className="project-header">
      <div className="page-heading">
        <div className="project-title">
          {project && (
            <button
              className="icon-button back-to-agents"
              aria-label={t("返回项目列表", "Back to projects")}
              onClick={() => onSelect("")}
            >
              <span aria-hidden="true">←</span>
            </button>
          )}
          <h1>{project?.name ?? t("项目", "Projects")}</h1>
        </div>
        {project ? (
          <select
            className="project-picker"
            aria-label={t("切换项目", "Switch project")}
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
            {t("新建项目", "New project")}
          </button>
        )}
      </div>
      {project && (
        <nav
          className="project-tabs"
          aria-label={t("项目导航", "Project navigation")}
        >
          {(
            [
              ["agents", "Agent", "Agents"],
              ["tasks", "任务", "Tasks"],
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
        <Empty icon="folder" title={t("暂无项目", "No projects yet")}>
          {null}
        </Empty>
        <button
          className="primary empty-action"
          aria-expanded={creating}
          aria-controls="project-form"
          onClick={onCreate}
        >
          {t("创建第一个项目", "Create your first project")}
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
