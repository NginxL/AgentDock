import * as uiMessages from "./messages";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { DockState, Mutate, Session, Translate } from "./types";
import { Icon } from "./ui";

function hasPendingTasks(session: Session, state: DockState) {
  const active = (status?: string) =>
    ["queued", "running", "waiting", "waiting_approval"].includes(status ?? "");
  return (
    active(session.status) ||
    (state.runs ?? []).some(
      (run) => run.session_id === session.id && active(run.status),
    ) ||
    state.approvals.some(
      (approval) =>
        approval.session_id === session.id && approval.status === "pending",
    ) ||
    state.messages.some((message) => {
      if (
        message.sender_session_id !== session.id &&
        message.recipient_session_id !== session.id
      )
        return false;
      const reply = (state.runs ?? []).find(
        (run) => run.id === message.reply_run_id,
      );
      return active(message.status) || active(reply?.status);
    })
  );
}

export default function SessionListItem({
  session,
  state,
  selected,
  className,
  children,
  onSelect,
  onDeleted,
  busy,
  mutate,
  t,
}: {
  session: Session;
  state: DockState;
  selected: boolean;
  className: string;
  children: ReactNode;
  onSelect: () => void;
  onDeleted: () => void;
  busy: boolean;
  mutate: Mutate;
  t: Translate;
}) {
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const dialogID = useId();
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const pending = useRef(false);
  const active = hasPendingTasks(session, state);
  const blocked = busy || deleting || active;
  function dismiss() {
    setConfirm(false);
    trigger.current?.focus();
  }
  useEffect(() => {
    if (!confirm) return;
    cancel.current?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss();
    };
    const outside = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setConfirm(false);
    };
    document.addEventListener("keydown", escape);
    document.addEventListener("pointerdown", outside);
    return () => {
      document.removeEventListener("keydown", escape);
      document.removeEventListener("pointerdown", outside);
    };
  }, [confirm]);
  return (
    <div className="session-list-row" ref={container}>
      <div className="session-row-main">
        <button
          type="button"
          className={`${className} ${selected ? "active" : ""}`}
          aria-current={selected ? "true" : undefined}
          onClick={() => {
            setConfirm(false);
            onSelect();
          }}
        >
          {children}
        </button>
        <button
          type="button"
          className="icon-button session-remove"
          ref={trigger}
          aria-label={t(
            `删除会话「${session.title}」`,
            `Delete session “${session.title}”`,
          )}
          title={
            active
              ? t(
                  ...uiMessages.sessionlistitem_finish_this_session_s_pending_tasks_first_964d1f,
                )
              : t(...uiMessages.sessionlistitem_delete_session_5b8934)
          }
          aria-expanded={confirm}
          aria-controls={confirm ? dialogID : undefined}
          aria-haspopup="dialog"
          disabled={blocked}
          onClick={() => setConfirm(!confirm)}
        >
          <Icon name="close" size={16} />
        </button>
      </div>
      {confirm && (
        <div
          className="session-delete-confirm"
          id={dialogID}
          role="alertdialog"
          aria-label={t(
            `删除「${session.title}」？`,
            `Delete “${session.title}”?`,
          )}
        >
          <div className="panel-heading">
            <strong>
              {t(`删除「${session.title}」？`, `Delete “${session.title}”?`)}
            </strong>
            <button
              type="button"
              className="icon-button"
              aria-label={t(...uiMessages.sessionlistitem_close_f09d50)}
              onClick={dismiss}
            >
              <Icon name="close" size={16} />
            </button>
          </div>
          <p>
            {t(
              ...uiMessages.sessionlistitem_permanently_delete_this_conversation_and_its_227666,
            )}
          </p>
          <div className="button-row">
            <button
              type="button"
              ref={cancel}
              className="secondary"
              disabled={busy || deleting}
              onClick={dismiss}
            >
              {t(...uiMessages.sessionlistitem_cancel_68f563)}
            </button>
            <button
              type="button"
              className="danger"
              disabled={blocked}
              onClick={async () => {
                if (blocked || pending.current) return;
                pending.current = true;
                setDeleting(true);
                try {
                  await mutate(
                    `/api/sessions/${encodeURIComponent(session.id)}/delete`,
                    {},
                    () => {
                      setConfirm(false);
                      onDeleted();
                    },
                  );
                } finally {
                  pending.current = false;
                  setDeleting(false);
                }
              }}
            >
              {deleting
                ? t(...uiMessages.sessionlistitem_deleting_99ae94)
                : t(...uiMessages.sessionlistitem_delete_permanently_da50a4)}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
