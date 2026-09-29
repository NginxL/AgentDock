import SessionListItem from "../SessionListItem";
import { useEffect, useRef, useState } from "react";
import type { DockState, Language, Mutate, Session, Translate } from "../types";
import { DateText, Empty, Icon, statusLabel } from "../ui";
import ProviderIcon from "../ProviderIcon";
import Workspace from "./Workspace";

export default function Conversations({
  state,
  sessionID,
  onSelect,
  onAgent,
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
  const [creating, setCreating] = useState(false);
  const [newScope, setNewScope] = useState("");
  const [agentID, setAgentID] = useState("");
  const [title, setTitle] = useState("");
  const selected = state.sessions.find((s) => s.id === sessionID);
  const agent = state.agents.find((a) => a.id === selected?.agent_id);
  const projectName = (session: Session) =>
    state.projects.find((p) => p.id === session.project_id)?.name ??
    t("日常对话", "Everyday chats");
  const matchesScope = (s: Session, value: string) =>
    value === "all" ||
    (value === "daily" ? !s.project_id : s.project_id === value);
  useEffect(() => {
    // History navigation can restore a conversation outside the current filter.
    if (selected && !matchesScope(selected, scope))
      setScope(selected.project_id || "daily");
  }, [selected?.id]);
  const visible = state.sessions
    .filter((session) => {
      const owner = state.agents.find((a) => a.id === session.agent_id);
      return (
        matchesScope(session, scope) &&
        `${session.title} ${owner?.name ?? ""} ${projectName(session)}`
          .toLocaleLowerCase()
          .includes(query.trim().toLocaleLowerCase())
      );
    })
    .sort(
      (a, b) =>
        b.updated_at.localeCompare(a.updated_at) || a.id.localeCompare(b.id),
    );
  const choices = state.agents.filter((a) => (a.project_id ?? "") === newScope);
  return (
    <section className="conversation-hub">
      <aside className="panel conversation-index">
        <div className="panel-heading">
          <h1>{t("对话", "Conversations")}</h1>
          <button
            className="icon-button"
            aria-label={t("新建对话", "New conversation")}
            aria-expanded={creating}
            aria-controls="new-conversation"
            onClick={() => {
              if (!creating) {
                setNewScope(scope === "all" || scope === "daily" ? "" : scope);
                setAgentID("");
              }
              setCreating(!creating);
            }}
          >
            <Icon name="plus" />
          </button>
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
              if (selected && !matchesScope(selected, e.target.value))
                onSelect("");
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
          {visible.map((session) => {
            const owner = state.agents.find((a) => a.id === session.agent_id);
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
                {owner && <ProviderIcon provider={owner.provider} size={22} />}
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
          {!visible.length && (
            <p className="muted conversation-empty">
              {t("暂无对话", "No conversations")}
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
              <button
                className="text-button"
                onClick={() => onAgent(agent.id, agent.project_id)}
              >
                {t("打开 Agent", "Open agent")} <Icon name="arrow" size={16} />
              </button>
            </div>
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
