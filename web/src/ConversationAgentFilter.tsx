import { useEffect, useId, useRef, useState } from "react";
import ProviderIcon from "./ProviderIcon";
import type { Agent, Project, Translate } from "./types";
import { Icon } from "./ui";

export default function ConversationAgentFilter({
  agents,
  projects,
  selected,
  onChange,
  t,
}: {
  agents: Agent[];
  projects: Project[];
  selected: string[];
  onChange: (ids: string[]) => void;
  t: Translate;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const first = useRef<HTMLButtonElement>(null);
  const label = t("按 Agent 筛选对话", "Filter conversations by agent");
  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };
  useEffect(() => {
    if (!open) return;
    first.current?.focus();
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open]);

  return (
    <div
      className="conversation-agent-filter"
      ref={root}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (open && event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          close();
        }
      }}
    >
      <button
        type="button"
        ref={trigger}
        className={`icon-button${selected.length ? " active" : ""}`}
        aria-label={label}
        title={label}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen(!open)}
      >
        <Icon name="agent" />
        {selected.length > 0 && <span className="filter-dot" />}
      </button>
      {open && (
        <div
          id={id}
          className="conversation-agent-options"
          role="group"
          aria-label={label}
        >
          <div className="panel-heading">
            <strong>{t("筛选 Agent", "Filter agents")}</strong>
            <button
              type="button"
              className="icon-button"
              aria-label={t("关闭 Agent 筛选", "Close agent filter")}
              onClick={close}
            >
              <Icon name="close" size={16} />
            </button>
          </div>
          <button
            ref={first}
            type="button"
            className="conversation-agent-all"
            aria-pressed={!selected.length}
            onClick={() => onChange([])}
          >
            {t("全部 Agent", "All agents")}
            {!selected.length && <span aria-hidden="true">✓</span>}
          </button>
          <div className="conversation-agent-choices">
            {agents.map((agent) => (
              <label key={agent.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(agent.id)}
                  onChange={(event) =>
                    onChange(
                      event.target.checked
                        ? [...selected, agent.id]
                        : selected.filter((value) => value !== agent.id),
                    )
                  }
                />
                <ProviderIcon provider={agent.provider} size={20} />
                <span>
                  <strong>{agent.name}</strong>
                  <small>
                    {projects.find((p) => p.id === agent.project_id)?.name ??
                      t("日常对话", "Everyday chats")}
                  </small>
                </span>
              </label>
            ))}
            {!agents.length && (
              <p className="muted">{t("暂无 Agent", "No agents")}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
