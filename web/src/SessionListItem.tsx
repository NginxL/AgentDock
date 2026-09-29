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
                  "请先结束此会话的未完成任务。",
                  "Finish this session’s pending tasks first.",
                )
              : t("删除会话", "Delete session")
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
              aria-label={t("关闭", "Close")}
              onClick={dismiss}
            >
              <Icon name="close" size={16} />
            </button>
          </div>
          <p>
            {t(
              "将删除会话及其专属文件，无法撤销。共用项目文件会保留。",
              "Permanently delete this conversation and its private files. Shared project files are kept.",
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
              {t("取消", "Cancel")}
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
                ? t("删除中…", "Deleting…")
                : t("确认删除", "Delete permanently")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
