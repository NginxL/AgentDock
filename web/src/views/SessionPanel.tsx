import * as uiMessages from "../messages";
import SessionListItem from "../SessionListItem";
import { DateText, Icon, statusLabel } from "../ui";
import type { WorkspaceView } from "./WorkspaceController";
export default function SessionPanel({
  view,
}: {
  view: Pick<
    WorkspaceView,
    | "t"
    | "selectedAgent"
    | "relevantSessions"
    | "state"
    | "sessionID"
    | "busy"
    | "mutate"
    | "setSessionID"
    | "setPrompts"
    | "setSessionSelections"
    | "agentID"
    | "lang"
    | "sessionTitle"
    | "setSessionTitle"
  >;
}) {
  const {
    t,
    selectedAgent,
    relevantSessions,
    state,
    sessionID,
    busy,
    mutate,
    setSessionID,
    setPrompts,
    setSessionSelections,
    agentID,
    lang,
    sessionTitle,
    setSessionTitle,
  } = view;
  return (
    <section className="panel session-panel">
      <div className="panel-heading">
        <div>
          <h2>{t(...uiMessages.sessionpanel_sessions_7fcc00)}</h2>
          <p>{selectedAgent?.name}</p>
        </div>
        <span className="count-badge">{relevantSessions.length}</span>
      </div>
      <div className="session-list">
        {relevantSessions.map((session) => (
          <SessionListItem
            key={session.id}
            session={session}
            state={state}
            selected={session.id === sessionID}
            className="session-item"
            busy={busy}
            mutate={mutate}
            t={t}
            onSelect={() => setSessionID(session.id)}
            onDeleted={() => {
              setPrompts((current) => {
                const next = { ...current };
                delete next[session.id];
                return next;
              });
              setSessionSelections((current) =>
                current[agentID] === session.id
                  ? { ...current, [agentID]: "" }
                  : current,
              );
            }}
          >
            <strong>{session.title}</strong>
            <span>
              {statusLabel(session.status, t)}
              <span>·</span>
              <DateText date={session.updated_at} lang={lang} />
            </span>
          </SessionListItem>
        ))}
        {!relevantSessions.length && (
          <p className="muted small-text">
            {t(
              ...uiMessages.sessionpanel_no_sessions_yet_create_a_task_for_this_agent_e388c7,
            )}
          </p>
        )}
      </div>
      <form
        className="session-create"
        onSubmit={async (e) => {
          e.preventDefault();
          await mutate(
            "/api/sessions",
            { agent_id: agentID, title: sessionTitle.trim() },
            (result) => {
              setSessionID(result.id);
              setSessionTitle("");
            },
          );
        }}
      >
        <label htmlFor="session-title">
          {t(...uiMessages.sessionpanel_new_session_title_98d8b6)}
        </label>
        <input
          id="session-title"
          value={sessionTitle}
          onChange={(e) => setSessionTitle(e.target.value)}
          required
          maxLength={160}
          placeholder={t(
            ...uiMessages.sessionpanel_for_example_review_sign_in_679ec2,
          )}
        />
        <button
          className="secondary full"
          disabled={busy || !sessionTitle.trim()}
        >
          <Icon name="plus" size={16} />
          {t(...uiMessages.sessionpanel_create_session_6d7aa5)}
        </button>
      </form>
    </section>
  );
}
