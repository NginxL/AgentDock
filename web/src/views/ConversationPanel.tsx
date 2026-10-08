import * as uiMessages from "../messages";
import { SessionAccountControls } from "../AccountSelection";
import InferenceControls from "../InferenceControls";
import TaskTimeline from "../TaskTimeline";
import { ApprovalCard, Empty, Icon, statusLabel } from "../ui";
import type { WorkspaceView } from "./WorkspaceController";
export default function ConversationPanel({
  view,
}: {
  view: Pick<
    WorkspaceView,
    | "selectedSession"
    | "t"
    | "running"
    | "eventLoading"
    | "eventError"
    | "events"
    | "sessionRuns"
    | "selectedAgent"
    | "state"
    | "setAccountSelectionRequest"
    | "lang"
    | "busy"
    | "mutate"
    | "approvals"
    | "sessionID"
    | "submittingPrompt"
    | "runtimeEnabled"
    | "demo"
    | "prompt"
    | "setPrompt"
    | "composingPrompt"
    | "accountSelectionRequest"
    | "hasSessionTasks"
    | "token"
  >;
}) {
  const {
    selectedSession,
    t,
    running,
    eventLoading,
    eventError,
    events,
    sessionRuns,
    selectedAgent,
    state,
    setAccountSelectionRequest,
    lang,
    busy,
    mutate,
    approvals,
    sessionID,
    submittingPrompt,
    runtimeEnabled,
    demo,
    prompt,
    setPrompt,
    composingPrompt,
    accountSelectionRequest,
    hasSessionTasks,
    token,
  } = view;
  return (
    <section className="panel conversation-panel">
      <div className="panel-heading">
        <div>
          <h2>
            {selectedSession?.title ||
              t(...uiMessages.conversationpanel_select_a_session_cbf07d)}
          </h2>
        </div>
        {selectedSession && (
          <span className={`pill ${running ? "live" : ""}`}>
            <span className={`status-dot ${running ? "" : "idle"}`} />
            {statusLabel(selectedSession.status, t)}
          </span>
        )}
      </div>
      {selectedSession ? (
        <>
          <div
            className="event-feed"
            aria-label={t(
              ...uiMessages.conversationpanel_session_events_4b742f,
            )}
            aria-busy={eventLoading}
          >
            {eventError && (
              <p className="inline-error" role="status">
                {eventError}
              </p>
            )}
            {eventLoading && !events.length ? (
              <p className="muted">
                {t(...uiMessages.conversationpanel_loading_events_19c4e4)}
              </p>
            ) : !events.length && !sessionRuns.length ? (
              <Empty
                icon="message"
                title={t(
                  ...uiMessages.conversationpanel_this_session_has_no_events_yet_eaae44,
                )}
              >
                {t(
                  ...uiMessages.conversationpanel_send_your_first_message_to_start_a_conversati_e5ac55,
                )}
              </Empty>
            ) : (
              <TaskTimeline
                runs={sessionRuns}
                events={events}
                agentName={selectedAgent?.name ?? "Agent"}
                accounts={state.accounts}
                accountAttempts={state.account_attempts}
                onConfigureAccount={() =>
                  setAccountSelectionRequest((value) => value + 1)
                }
                t={t}
                lang={lang}
                busy={busy}
                mutate={mutate}
              />
            )}
          </div>
          {approvals
            .filter((a) => a.session_id === sessionID)
            .map((approval) => (
              <ApprovalCard
                key={approval.id}
                approval={approval}
                busy={busy}
                mutate={mutate}
                t={t}
              />
            ))}
          <form
            className="prompt-form"
            onSubmit={async (e) => {
              e.preventDefault();
              if (
                submittingPrompt.current ||
                busy ||
                !runtimeEnabled ||
                demo ||
                !prompt.trim()
              )
                return;
              submittingPrompt.current = true;
              try {
                await mutate(
                  `/api/sessions/${encodeURIComponent(sessionID)}/run`,
                  { prompt: prompt.trim() },
                  () => setPrompt(""),
                );
              } finally {
                submittingPrompt.current = false;
              }
            }}
          >
            <label htmlFor="run-prompt">
              {t(...uiMessages.conversationpanel_task_for_this_agent_870d7e)}
            </label>
            <textarea
              id="run-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onCompositionStart={() => {
                composingPrompt.current = true;
              }}
              onCompositionEnd={() => {
                composingPrompt.current = false;
              }}
              onKeyDown={(e) => {
                if (
                  e.key !== "Enter" ||
                  e.shiftKey ||
                  e.altKey ||
                  e.ctrlKey ||
                  e.metaKey ||
                  composingPrompt.current ||
                  e.nativeEvent.isComposing ||
                  e.nativeEvent.keyCode === 229
                )
                  return;
                e.preventDefault();
                if (
                  !e.repeat &&
                  !busy &&
                  runtimeEnabled &&
                  !demo &&
                  prompt.trim() &&
                  !submittingPrompt.current
                )
                  e.currentTarget.form?.requestSubmit();
              }}
              rows={3}
              required
              maxLength={24000}
              disabled={busy}
              placeholder={t(
                ...uiMessages.conversationpanel_describe_the_goal_constraints_and_expected_ou_b5de6a,
              )}
            />
            {selectedAgent && selectedSession && (
              <SessionAccountControls
                key={`account-${sessionID}`}
                openRequest={accountSelectionRequest}
                accounts={state.accounts ?? []}
                agent={selectedAgent}
                session={selectedSession}
                busy={busy || hasSessionTasks}
                demo={demo}
                mutate={mutate}
                t={t}
              />
            )}
            <div className="prompt-footer">
              {selectedAgent && selectedSession && (
                <InferenceControls
                  key={sessionID}
                  agent={selectedAgent}
                  session={selectedSession}
                  token={token}
                  accountGeneration={
                    state.accounts?.find(
                      (account) => account.id === selectedSession.account_id,
                    )?.generation
                  }
                  busy={busy}
                  runtimeEnabled={runtimeEnabled}
                  demo={demo}
                  mutate={mutate}
                  t={t}
                />
              )}
              <div className="button-row">
                {hasSessionTasks && (
                  <button
                    className="secondary"
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void mutate(
                        `/api/sessions/${encodeURIComponent(sessionID)}/cancel`,
                        {},
                      )
                    }
                  >
                    {t(
                      ...uiMessages.conversationpanel_cancel_session_tasks_9c5cd5,
                    )}
                  </button>
                )}
                <button
                  className="primary"
                  disabled={busy || !runtimeEnabled || !prompt.trim()}
                  title={t(
                    ...uiMessages.conversationpanel_enter_to_send_shift_enter_for_a_new_line_673fd6,
                  )}
                  aria-keyshortcuts="Enter"
                >
                  <Icon name="arrow" size={17} />
                  {running
                    ? t(...uiMessages.conversationpanel_queue_task_31c5f9)
                    : t(...uiMessages.conversationpanel_run_task_2d710b)}
                </button>
              </div>
            </div>
          </form>
        </>
      ) : (
        <Empty
          icon="work"
          title={t(
            ...uiMessages.conversationpanel_create_a_session_to_begin_c203ca,
          )}
        >
          {t(
            ...uiMessages.conversationpanel_sessions_preserve_execution_events_creating_o_f7e4d1,
          )}
        </Empty>
      )}
    </section>
  );
}
