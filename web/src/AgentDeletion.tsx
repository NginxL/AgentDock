import { useEffect, useRef, useState } from "react";
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
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!confirm) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setConfirm(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [confirm]);
  return (
    <div className="agent-delete">
      <button
        type="button"
        ref={trigger}
        className="text-button danger-text"
        aria-expanded={confirm}
        disabled={busy || active}
        onClick={() => setConfirm(!confirm)}
      >
        {t("删除 Agent", "Delete agent")}
      </button>
      {active && (
        <p className="form-hint">
          {t(
            "请先结束该 Agent 的未完成任务，再删除。",
            "Finish this agent’s pending tasks before deleting it.",
          )}
        </p>
      )}
      {confirm && (
        <div
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
            {t(
              `将删除此 Agent、${sessionCount} 个会话及其私有文件，无法撤销。共用项目文件和原生 CLI 配置会保留。`,
              `This permanently deletes the agent, its ${sessionCount} conversations and their private files. Shared project files and native CLI settings are kept.`,
            )}
          </p>
          <div className="button-row">
            <button
              type="button"
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
                  onDeleted,
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
