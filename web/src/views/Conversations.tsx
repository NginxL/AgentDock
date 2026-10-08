import SessionListItem from "../SessionListItem";
import { useEffect, useRef, useState } from "react";
import type {
  DockState,
  Language,
  Mutate,
  Session,
  Translate,
  ProjectTask,
} from "../types";
import { DateText, Empty, Icon, statusLabel } from "../ui";
import ProviderIcon from "../ProviderIcon";
import ConversationAgentFilter from "../ConversationAgentFilter";
import Workspace from "./Workspace";
import { TaskForm } from "./Tasks";

export default function Conversations({
  state,
  sessionID,
  onSelect,
  onAgent,
  onTask,
  token,
  demo,
  busy,
  mutate,
  lang,
  t,
}: {
  state: DockState;
  sessionID: string;
  onSelect: (id: string) => void;
  onAgent: (id: string, projectID: string | null) => void;
  onTask?: (task: ProjectTask) => void;
  token: string;
  demo: boolean;
  busy: boolean;
  mutate: Mutate;
  lang: Language;
  t: Translate;
}) {
  const currentSessionID = useRef(sessionID);
  currentSessionID.current = sessionID;
  const [scope, setScope] = useState("all");
  const [query, setQuery] = useState("");
  const [filterAgents, setFilterAgents] = useState<string[]>([]);
  const [recentOnly, setRecentOnly] = useState(false);
  const [grouped, setGrouped] = useState(false);
  const [now, setNow] = useState(Date.now);
  const [creating, setCreating] = useState(false);
  const [newScope, setNewScope] = useState("");
  const [agentID, setAgentID] = useState("");
  const [title, setTitle] = useState("");
  const [converting, setConverting] = useState(false);
  const selected = state.sessions.find((s) => s.id === sessionID);
  const agent = state.agents.find((a) => a.id === selected?.agent_id);
  const projectName = (session: Session) =>
    state.projects.find((p) => p.id === session.project_id)?.name ??
    t("日常对话", "Everyday chats");
  const matchesScope = (s: Session, value: string) =>
    value === "all" ||
    (value === "daily" ? !s.project_id : s.project_id === value);
  const matchesQuery = (session: Session) => {
    const owner = state.agents.find((a) => a.id === session.agent_id);
    return `${session.title} ${owner?.name ?? ""} ${projectName(session)}`
      .toLocaleLowerCase()
      .includes(query.trim().toLocaleLowerCase());
  };
  const isRecent = (session: Session) =>
    Date.parse(session.updated_at) >= now - 24 * 60 * 60 * 1000;
  useEffect(() => {
    if (!recentOnly) return;
    // The window keeps rolling even when no new server events arrive.
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, [recentOnly]);
  useEffect(() => {
    // Deleted agents must not leave an invisible, stale filter behind.
    setFilterAgents((ids) => {
      const remaining = ids.filter((id) =>
        state.agents.some((a) => a.id === id),
      );
      return remaining.length === ids.length ? ids : remaining;
    });
  }, [state.agents]);
  useEffect(() => {
    // History navigation can restore a conversation outside the current filter.
    if (selected && !matchesScope(selected, scope))
      setScope(selected.project_id || "daily");
    if (
      selected &&
      filterAgents.length &&
      !filterAgents.includes(selected.agent_id)
    )
      setFilterAgents([]);
    if (selected && recentOnly && !isRecent(selected)) setRecentOnly(false);
    if (selected && !matchesQuery(selected)) setQuery("");
  }, [selected?.id]);
  const visible = state.sessions
    .filter((session) => {
      return (
        matchesScope(session, scope) &&
        (!filterAgents.length || filterAgents.includes(session.agent_id)) &&
        (!recentOnly || isRecent(session)) &&
        matchesQuery(session)
      );
    })
    .sort(
      (a, b) =>
        (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0) ||
        a.id.localeCompare(b.id),
    );
  // Map insertion order retains each group's most recently active conversation.
  const groups = new Map<string, Session[]>();
  for (const session of visible) {
    const key = grouped ? session.agent_id : "all";
    const items = groups.get(key) ?? [];
    items.push(session);
    groups.set(key, items);
  }
  const choices = state.agents.filter((a) => (a.project_id ?? "") === newScope);
  return (
    <section className="conversation-hub">
      <aside className="panel conversation-index">
        <div className="panel-heading conversation-heading">
          <h1>{t("对话", "Conversations")}</h1>
          <div
            className="conversation-toolbar"
            role="group"
            aria-label={t("对话工具", "Conversation tools")}
          >
            <ConversationAgentFilter
              agents={state.agents.filter(
                (a) =>
                  scope === "all" ||
                  (scope === "daily" ? !a.project_id : a.project_id === scope),
              )}
              projects={state.projects}
              selected={filterAgents}
              onChange={setFilterAgents}
              t={t}
            />
            <button
              type="button"
              className="icon-button"
              aria-label={t(
                "仅显示最近 24 小时活跃的对话",
                "Show only conversations active in the last 24 hours",
              )}
              title={t(
                "仅显示最近 24 小时活跃的对话",
                "Show only conversations active in the last 24 hours",
              )}
              aria-pressed={recentOnly}
              onClick={() => {
                setNow(Date.now());
                setRecentOnly(!recentOnly);
              }}
            >
              <Icon name="timer" />
            </button>
            <button
              type="button"
              className="icon-button"
              aria-label={t("按 Agent 分组", "Group by agent")}
              title={t("按 Agent 分组", "Group by agent")}
              aria-pressed={grouped}
              onClick={() => setGrouped(!grouped)}
            >
              <Icon name="memory" />
            </button>
            <button
              className="icon-button"
              aria-label={t("新建对话", "New conversation")}
              title={t("新建对话", "New conversation")}
              aria-expanded={creating}
              aria-controls="new-conversation"
              onClick={() => {
                if (!creating) {
                  setNewScope(
                    scope === "all" || scope === "daily" ? "" : scope,
                  );
                  setAgentID("");
                }
                setCreating(!creating);
              }}
            >
              <Icon name="plus" />
            </button>
          </div>
        </div>
        <div className="conversation-filters">
          <input
            aria-label={t("搜索对话", "Search conversations")}
            placeholder={t("搜索对话", "Search conversations")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            aria-label={t("对话范围", "Conversation scope")}
            value={scope}
            onChange={(e) => {
              setScope(e.target.value);
              setFilterAgents([]);
            }}
          >
            <option value="all">{t("全部对话", "All conversations")}</option>
            <option value="daily">{t("日常对话", "Everyday chats")}</option>
            {state.projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        {creating && (
          <form
            id="new-conversation"
            className="conversation-create"
            onSubmit={async (e) => {
              e.preventDefault();
              if (!choices.some((a) => a.id === agentID)) return;
              await mutate(
                "/api/sessions",
                {
                  agent_id: agentID,
                  title: title.trim() || t("新对话", "New conversation"),
                },
                (session) => {
                  setCreating(false);
                  setTitle("");
                  setScope(newScope || "daily");
                  setQuery("");
                  setFilterAgents([]);
                  onSelect(session.id);
                },
              );
            }}
          >
            <div className="panel-heading">
              <strong>{t("新建对话", "New conversation")}</strong>
              <button
                type="button"
                className="icon-button"
                aria-label={t("关闭新建对话", "Close new conversation")}
                onClick={() => setCreating(false)}
              >
                <Icon name="close" />
              </button>
            </div>
            <label>
              {t("所属项目", "Project")}
              <select
                value={newScope}
                onChange={(e) => {
                  setNewScope(e.target.value);
                  setAgentID("");
                }}
              >
                <option value="">{t("日常对话", "Everyday chats")}</option>
                {state.projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Agent
              <select
                required
                value={agentID}
                onChange={(e) => setAgentID(e.target.value)}
              >
                <option value="">{t("选择 Agent", "Select an agent")}</option>
                {choices.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("标题（可选）", "Title (optional)")}
              <input
                maxLength={160}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            {!choices.length && (
              <p className="muted">
                {t(
                  newScope
                    ? "请先为此项目添加 Agent。"
                    : "请先在协作工作台配置独立 Agent。",
                  newScope
                    ? "Add an agent to this project first."
                    : "Configure an independent agent in Workspace first.",
                )}
              </p>
            )}
            <button className="primary" disabled={busy || !agentID}>
              {t("创建对话", "Create conversation")}
            </button>
          </form>
        )}
        <div className="conversation-index-list">
          {Array.from(groups, ([key, sessions]) => (
            <div
              key={key}
              className="conversation-group"
              role={grouped ? "group" : undefined}
              aria-label={
                grouped
                  ? `${state.agents.find((a) => a.id === key)?.name ?? t("已移除的 Agent", "Removed agent")} · ${projectName(sessions[0])}`
                  : undefined
              }
            >
              {grouped && (
                <div className="conversation-group-heading">
                  <span>
                    <strong>
                      {state.agents.find((a) => a.id === key)?.name ??
                        t("已移除的 Agent", "Removed agent")}
                    </strong>
                    <small>{projectName(sessions[0])}</small>
                  </span>
                  <span className="count">{sessions.length}</span>
                </div>
              )}
              {sessions.map((session) => {
                const owner = state.agents.find(
                  (a) => a.id === session.agent_id,
                );
                return (
                  <SessionListItem
                    key={session.id}
                    session={session}
                    state={state}
                    selected={session.id === sessionID}
                    className="conversation-index-item"
                    busy={busy}
                    mutate={mutate}
                    t={t}
                    onSelect={() => onSelect(session.id)}
                    onDeleted={() => {
                      if (currentSessionID.current === session.id) onSelect("");
                    }}
                  >
                    {owner && (
                      <ProviderIcon provider={owner.provider} size={22} />
                    )}
                    <span>
                      <strong>{session.title}</strong>
                      <small>
                        {projectName(session)} · {owner?.name}
                      </small>
                      <small>
                        {statusLabel(session.status, t)} ·{" "}
                        <DateText date={session.updated_at} lang={lang} />
                      </small>
                    </span>
                  </SessionListItem>
                );
              })}
            </div>
          ))}
          {!visible.length && (
            <p className="muted conversation-empty">
              {query.trim() || filterAgents.length || recentOnly
                ? t("没有符合条件的对话", "No matching conversations")
                : t("暂无对话", "No conversations")}
            </p>
          )}
        </div>
      </aside>
      <div className="conversation-detail">
        {selected && agent ? (
          <>
            <div className="conversation-context">
              <span>
                {projectName(selected)} · {agent.name}
              </span>
              {onTask &&
                (selected.work_task_id ? (
                  <button
                    className="text-button"
                    onClick={() => {
                      const task = state.tasks?.find(
                        (task) => task.id === selected.work_task_id,
                      );
                      if (task) onTask(task);
                    }}
                  >
                    {t("打开任务", "Open task")}
                  </button>
                ) : (
                  <button
                    className="text-button"
                    aria-expanded={converting}
                    onClick={() => setConverting(!converting)}
                  >
                    {t("转为项目任务", "Create project task")}
                  </button>
                ))}
              <button
                className="text-button"
                onClick={() => onAgent(agent.id, agent.project_id)}
              >
                {t("打开 Agent", "Open agent")} <Icon name="arrow" size={16} />
              </button>
            </div>
            {converting && onTask && (
              <TaskForm
                key={selected.id}
                state={state}
                t={t}
                busy={busy}
                mutate={mutate}
                source={selected}
                close={() => setConverting(false)}
                onCreated={(task) => {
                  setConverting(false);
                  onTask(task);
                }}
              />
            )}
            <Workspace
              t={t}
              lang={lang}
              state={state}
              agents={state.agents}
              sessions={state.sessions}
              approvals={state.approvals.filter(
                (a) => a.session_id === selected.id && a.status === "pending",
              )}
              token={token}
              demo={demo}
              runtimeEnabled={state.runtime.enabled}
              busy={busy}
              mutate={mutate}
              agentPageID={agent.id}
              sessionPageID={selected.id}
              conversationOnly
            />
          </>
        ) : (
          <section className="panel conversation-placeholder">
            <Empty
              icon="message"
              title={t("选择或新建对话", "Select or start a conversation")}
            >
              {null}
            </Empty>
          </section>
        )}
      </div>
    </section>
  );
}
