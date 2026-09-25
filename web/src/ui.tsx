import type { ReactNode } from "react";
import type { Approval, Language, Memory, Mutate, Translate } from "./types";

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    dock: (
      <>
        <path d="M4 5h6v14H4zM14 5h6v6h-6zM14 15h6v4h-6z" />
      </>
    ),
    work: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="3" />
        <path d="M9 5v14M3 10h6" />
      </>
    ),
    message: (
      <>
        <path d="M20 14a4 4 0 0 1-4 4H9l-5 3V7a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4z" />
        <path d="M8 8h8M8 12h5" />
      </>
    ),
    memory: (
      <>
        <path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5" />
      </>
    ),
    usage: (
      <>
        <path d="M4 20h17M6 16v-5M12 16V4M18 16V8" />
      </>
    ),
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    plus: <path d="M12 5v14M5 12h14" />,
    refresh: (
      <>
        <path d="M20 7v5h-5M4 17v-5h5" />
        <path d="M6.2 6.2a8 8 0 0 1 13 3.8M4.8 14a8 8 0 0 0 13 3.8" />
      </>
    ),
    shield: (
      <>
        <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z" />
        <path d="m8 12 3 3 5-6" />
      </>
    ),
    search: (
      <>
        <circle cx="10" cy="10" r="6" />
        <path d="m15 15 6 6" />
      </>
    ),
    close: <path d="m6 6 12 12M6 18 18 6" />,
    bolt: <path d="m13 2-9 12h7l-1 8 10-13h-7z" />,
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] ?? paths.dock}
    </svg>
  );
}

export function DateText({
  date,
  lang,
}: {
  date?: string | null;
  lang: Language;
}) {
  if (!date) return <span>—</span>;
  const value = new Date(date);
  return (
    <time dateTime={date}>
      {Number.isNaN(value.getTime())
        ? "—"
        : value.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
    </time>
  );
}

export function Empty({
  icon,
  title,
  children,
}: {
  icon: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name={icon} size={26} />
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

export function Brand({ small = false }: { small?: boolean }) {
  return (
    <div className={`brand ${small ? "small" : ""}`}>
      <span className="brand-symbol">
        <Icon name="dock" size={24} />
      </span>
      <span>
        AgentDock<small>ONE SPACE. MANY MINDS.</small>
      </span>
    </div>
  );
}

export function Stat({
  value,
  label,
  icon,
}: {
  value: number;
  label: string;
  icon: string;
}) {
  return (
    <div className="stat">
      <span>
        <Icon name={icon} />
        {label}
      </span>
      <strong>{value.toString().padStart(2, "0")}</strong>
    </div>
  );
}
export function statusLabel(status: string, t: Translate) {
  return (
    {
      idle: t("待命", "Idle"),
      running: t("运行中", "Running"),
      completed: t("完成", "Completed"),
      failed: t("失败", "Failed"),
      cancelled: t("已取消", "Cancelled"),
      interrupted: t("已中断", "Interrupted"),
    }[status] ?? status
  );
}
export function eventText(payload: unknown): string {
  if (typeof payload === "string") return payload;
  if (payload && typeof payload === "object") {
    const value = payload as Record<string, unknown>;
    if (typeof value.text === "string") return value.text;
    if (typeof value.content === "string") return value.content;
    const content = value.content as Record<string, unknown> | undefined;
    if (content && typeof content.text === "string") return content.text;
  }
  return JSON.stringify(payload, null, 2) ?? "";
}

export function ApprovalCard({
  approval,
  t,
  busy,
  mutate,
}: {
  approval: Approval;
  t: Translate;
  busy: boolean;
  mutate: Mutate;
}) {
  return (
    <section className="approval-card">
      <h3>
        <Icon name="shield" size={18} />
        {t("此操作需要你的授权", "Your approval is required")}
      </h3>
      <p>
        {t(
          "以下内容由 Agent 提供。核对实际命令和作用范围后再选择；超时将拒绝。",
          "The agent supplied this request. Review its command and scope before deciding. Requests are denied on timeout.",
        )}
      </p>
      <pre>{eventText(approval.request)}</pre>
      <div className="button-row">
        {approval.options.map((option) => (
          <button
            key={option.optionId}
            className={
              option.kind.startsWith("reject") ? "secondary" : "approval-allow"
            }
            disabled={busy}
            onClick={() =>
              void mutate(`/api/approvals/${encodeURIComponent(approval.id)}`, {
                option_id: option.optionId,
              })
            }
          >
            {option.name}
            <small>{option.kind}</small>
          </button>
        ))}
      </div>
    </section>
  );
}

export function isArchived(memory: Memory) {
  return (
    memory.archived || !!memory.archived_at || memory.status === "archived"
  );
}
export function PageTitle({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
