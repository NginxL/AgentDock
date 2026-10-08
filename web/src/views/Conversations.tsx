import * as uiMessages from "../messages";
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
    t(...uiMessages.conversations_everyday_chats_0dc423);
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
          <h1>{t(...uiMessages.conversations_conversations_d3714e)}</h1>
          <div
            className="conversation-toolbar"
            role="group"
            aria-label={t(
              ...uiMessages.conversations_conversation_tools_bcce11,
            )}
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
                ...uiMessages.conversations_show_only_conversations_active_in_the_last_24_7b70e3,
              )}
              title={t(
                ...uiMessages.conversations_show_only_conversations_active_in_the_last_24_7b70e3,
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
              aria-label={t(...uiMessages.conversations_group_by_agent_4e82ca)}
              title={t(...uiMessages.conversations_group_by_agent_4e82ca)}
              aria-pressed={grouped}
              onClick={() => setGrouped(!grouped)}
            >
              <Icon name="memory" />
            </button>
            <button
              className="icon-button"
              aria-label={t(
                ...uiMessages.conversations_new_conversation_f0bb24,
              )}
              title={t(...uiMessages.conversations_new_conversation_f0bb24)}
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
            aria-label={t(
              ...uiMessages.conversations_search_conversations_eae0c2,
            )}
            placeholder={t(
              ...uiMessages.conversations_search_conversations_eae0c2,
            )}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            aria-label={t(
              ...uiMessages.conversations_conversation_scope_486170,
            )}
            value={scope}
            onChange={(e) => {
              setScope(e.target.value);
              setFilterAgents([]);
            }}
          >
            <option value="all">
              {t(...uiMessages.conversations_all_conversations_9ab276)}
            </option>
            <option value="daily">
              {t(...uiMessages.conversations_everyday_chats_0dc423)}
            </option>
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
                  title:
                    title.trim() ||
                    t(...uiMessages.conversations_new_conversation_0747d6),
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
              <strong>
                {t(...uiMessages.conversations_new_conversation_f0bb24)}
              </strong>
              <button
                type="button"
                className="icon-button"
                aria-label={t(
                  ...uiMessages.conversations_close_new_conversation_d174d4,
                )}
                onClick={() => setCreating(false)}
              >
                <Icon name="close" />
              </button>
            </div>
            <label>
              {t(...uiMessages.conversations_project_4eca63)}
              <select
                value={newScope}
                onChange={(e) => {
                  setNewScope(e.target.value);
                  setAgentID("");
                }}
              >
                <option value="">
                  {t(...uiMessages.conversations_everyday_chats_0dc423)}
                </option>
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
                <option value="">
                  {t(...uiMessages.conversations_select_an_agent_08897f)}
                </option>
                {choices.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t(...uiMessages.conversations_title_optional_bda802)}
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
              {t(...uiMessages.conversations_create_conversation_5889a6)}
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
                  ? `${state.agents.find((a) => a.id === key)?.name ?? t(...uiMessages.conversations_removed_agent_22e81a)} · ${projectName(sessions[0])}`
                  : undefined
              }
            >
              {grouped && (
                <div className="conversation-group-heading">
                  <span>
                    <strong>
                      {state.agents.find((a) => a.id === key)?.name ??
                        t(...uiMessages.conversations_removed_agent_22e81a)}
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
                ? t(
                    ...uiMessages.conversations_no_matching_conversations_b3bdf3,
                  )
                : t(...uiMessages.conversations_no_conversations_9ac294)}
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
                    {t(...uiMessages.conversations_open_task_ff4a5d)}
                  </button>
                ) : (
                  <button
                    className="text-button"
                    aria-expanded={converting}
                    onClick={() => setConverting(!converting)}
                  >
                    {t(...uiMessages.conversations_create_project_task_11cca7)}
                  </button>
                ))}
              <button
                className="text-button"
                onClick={() => onAgent(agent.id, agent.project_id)}
              >
                {t(...uiMessages.conversations_open_agent_f26aad)}{" "}
                <Icon name="arrow" size={16} />
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
              title={t(
                ...uiMessages.conversations_select_or_start_a_conversation_cb5b4d,
              )}
            >
              {null}
            </Empty>
          </section>
        )}
      </div>
    </section>
  );
}
