import { useEffect, useId, useRef, useState } from "react";
import type { Agent, Mutate, Translate } from "./types";

export default function AgentDeletion({
  agent,
  sessionCount,
  active,
  busy,
  mutate,
  onDeleted,
  t,
}: {
  agent: Agent;
  sessionCount: number;
  active: boolean;
  busy: boolean;
  mutate: Mutate;
  onDeleted: () => void;
  t: Translate;
}) {
  const [confirm, setConfirm] = useState(false);
  const dialogID = useId();
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!confirm) return;
    cancel.current?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setConfirm(false);
        trigger.current?.focus();
      }
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
    <div className="agent-delete" ref={container}>
      <button
        type="button"
        ref={trigger}
        className="secondary danger-text"
        aria-expanded={confirm}
        aria-controls={confirm ? dialogID : undefined}
        aria-haspopup="dialog"
        title={
          active
            ? t(
                "请先结束该 Agent 的未完成任务，再删除。",
                "Finish this agent’s pending tasks before deleting it.",
              )
            : undefined
        }
        disabled={busy || active}
        onClick={() => setConfirm(!confirm)}
      >
        {t("删除 Agent", "Delete agent")}
      </button>
      {confirm && (
        <div
          id={dialogID}
          className="agent-delete-confirm"
          role="alertdialog"
          aria-label={t("删除 Agent", "Delete agent")}
        >
          <div className="panel-heading">
            <strong>
              {t(`删除「${agent.name}」？`, `Delete “${agent.name}”?`)}
            </strong>
            <button
              type="button"
              className="icon-button"
              aria-label={t("关闭", "Close")}
              onClick={() => setConfirm(false)}
            >
              ×
            </button>
          </div>
          <p>
            {agent.project_id
              ? t(
                  `将删除此项目中的「${agent.name}」、${sessionCount} 个会话及其私有文件，无法撤销。其他项目的 Agent 和共用项目文件会保留。`,
                  `This permanently deletes “${agent.name}” in this project, its ${sessionCount} conversations and their private files. Agents in other projects and shared project files are kept.`,
                )
              : t(
                  `将删除此 Agent、${sessionCount} 个会话及其私有文件，无法撤销。共用项目文件和原生 CLI 配置会保留。`,
                  `This permanently deletes the agent, its ${sessionCount} conversations and their private files. Shared project files and native CLI settings are kept.`,
                )}
          </p>
          <div className="button-row">
            <button
              type="button"
              ref={cancel}
              className="secondary"
              disabled={busy}
              onClick={() => setConfirm(false)}
            >
              {t("取消", "Cancel")}
            </button>
            <button
              type="button"
              className="danger"
              disabled={busy || active}
              onClick={async () => {
                await mutate(
                  `/api/agents/${encodeURIComponent(agent.id)}/delete`,
                  {},
                  () => {
                    setConfirm(false);
                    onDeleted();
                  },
                );
              }}
            >
              {t("确认删除", "Delete permanently")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
