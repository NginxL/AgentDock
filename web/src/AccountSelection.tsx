import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type {
  Account,
  AccountSettings,
  Agent,
  Mutate,
  Provider,
  Session,
  Translate,
} from "./types";
import { useFeature } from "./ExperimentalFeatures";
import { Icon } from "./ui";

export const deviceAccount: AccountSettings = {
  account_id: null,
  account_policy: "manual",
  account_ids: [],
};
export const supportsAccounts = (provider: Provider) =>
  provider === "codex" || provider === "claude";
export function accountStatus(account: Account, t: Translate) {
  const labels = {
    pending: ["待登录", "Not signed in"],
    ready: ["已登录", "Signed in"],
    expired: ["需重新登录", "Sign in again"],
    cooldown: ["等待额度恢复", "Waiting for quota"],
    disabled: ["已停用", "Disabled"],
    removed: ["已删除", "Removed"],
  } as const;
  const label = labels[account.status] ?? labels.pending;
  return t(label[0], label[1]);
}
export function accountSettings(value: AccountSettings): AccountSettings {
  return {
    account_id: value.account_id ?? null,
    account_policy: value.account_policy ?? "manual",
    account_ids: value.account_ids ?? [],
  };
}

export default function AccountSelection({
  accounts,
  provider,
  environment,
  value,
  onChange,
  disabled,
  t,
}: {
  accounts: Account[];
  provider: Provider;
  environment: string;
  value: AccountSettings;
  onChange: (value: AccountSettings) => void;
  disabled?: boolean;
  t: Translate;
}) {
  const failoverEnabled = useFeature("automatic_failover");
  if (!supportsAccounts(provider)) return null;
  const matching = accounts.filter(
    (account) =>
      account.status !== "removed" &&
      account.provider === provider &&
      account.environment_id === environment,
  );
  const policy = value.account_policy ?? "manual";
  const missing =
    value.account_id && !matching.some((a) => a.id === value.account_id);
  return (
    <fieldset className="account-selection" disabled={disabled}>
      <div className="form-grid">
        <label>
          {t("订阅账号", "Subscription account")}
          <select
            value={value.account_id ?? ""}
            onChange={(event) =>
              onChange({ ...value, account_id: event.target.value || null })
            }
          >
            <option value="">
              {policy === "manual"
                ? t("沿用设备登录", "Use device login")
                : t("自动选择可用账号", "Choose an available account")}
            </option>
            {missing && (
              <option value={value.account_id!} disabled>
                {t("账号不可用", "Account unavailable")}
              </option>
            )}
            {matching.map((account) => (
              <option
                key={account.id}
                value={account.id}
                disabled={
                  account.status === "disabled" ||
                  account.status === "pending" ||
                  account.status === "expired"
                }
              >
                {account.label} · {accountStatus(account, t)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("账号使用方式", "Account selection")}
          <select
            value={policy}
            onChange={(event) =>
              onChange({
                ...value,
                account_policy: event.target
                  .value as AccountSettings["account_policy"],
              })
            }
          >
            <option value="manual">{t("固定账号", "Fixed account")}</option>
            <option value="auto">{t("自动选择", "Automatic selection")}</option>
            <option value="failover" disabled={!failoverEnabled}>
              {t("限额或登录失效时切换", "Switch on quota or sign-in failure")}
            </option>
          </select>
        </label>
      </div>
      {policy !== "manual" && (
        <p className="form-hint">
          {policy === "auto"
            ? t(
                "首次运行选择可用账号，之后保持使用该账号。",
                "Choose an available account for the first run, then keep using it.",
              )
            : t(
                "仅在明确限额或登录失效时切换；执行中的任务不会强行换号。",
                "Switch only after a definite quota or sign-in failure; never replace an account during execution.",
              )}
        </p>
      )}
      {policy !== "manual" && (
        <div className="account-pool">
          <span>{t("可使用的账号", "Allowed accounts")}</span>
          <p className="form-hint">
            {t(
              "不勾选时使用此设备、此服务下的全部可用账号。",
              "Leave unchecked to use all available accounts for this device and service.",
            )}
          </p>
          {matching.map((account) => (
            <label className="account-check" key={account.id}>
              <input
                type="checkbox"
                checked={value.account_ids?.includes(account.id) ?? false}
                disabled={
                  account.status === "disabled" &&
                  !value.account_ids?.includes(account.id)
                }
                onChange={(event) =>
                  onChange({
                    ...value,
                    account_ids: event.target.checked
                      ? [...(value.account_ids ?? []), account.id]
                      : (value.account_ids ?? []).filter(
                          (id) => id !== account.id,
                        ),
                  })
                }
              />
              <span>
                {account.label} <small>{accountStatus(account, t)}</small>
              </span>
            </label>
          ))}
          {!matching.length && (
            <p className="muted">
              {t(
                "请先在“账号”页面添加此设备的订阅账号。",
                "Add a subscription for this device on the Accounts page first.",
              )}
            </p>
          )}
        </div>
      )}
      <a className="text-button account-manage-link" href="#/accounts">
        {t("管理订阅账号", "Manage subscription accounts")} ↗
      </a>
    </fieldset>
  );
}

export function SessionAccountControls({
  accounts,
  agent,
  session,
  busy,
  demo,
  openRequest = 0,
  mutate,
  t,
}: {
  accounts: Account[];
  agent: Agent;
  session: Session;
  busy: boolean;
  demo: boolean;
  openRequest?: number;
  mutate: Mutate;
  t: Translate;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<AccountSettings>(accountSettings(session));
  const [saving, setSaving] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const previousRequest = useRef(openRequest);
  useEffect(() => {
    if (previousRequest.current === openRequest) return;
    previousRequest.current = openRequest;
    setDraft(accountSettings(session));
    setOpen(true);
  }, [openRequest, session]);
  useEffect(() => {
    if (!open) return;
    panel.current?.focus();
    return () => trigger.current?.focus();
  }, [open]);
  if (!supportsAccounts(agent.provider)) return null;
  const selected = accounts.find(
    (account) => account.id === session.account_id,
  );
  const title =
    (selected
      ? `${selected.label}${selected.status !== "ready" ? ` · ${accountStatus(selected, t)}` : ""}`
      : undefined) ??
    (session.account_id
      ? t("账号不可用", "Account unavailable")
      : (session.account_policy ?? "manual") !== "manual"
        ? t("自动选择账号", "Automatic account")
        : t("沿用设备登录", "Use device login"));
  return (
    <div className="session-account-controls">
      <button
        ref={trigger}
        type="button"
        className="text-button"
        aria-expanded={open}
        onClick={() => {
          if (!open) setDraft(accountSettings(session));
          setOpen(!open);
        }}
      >
        <Icon name="shield" size={16} />
        {title}
        <span aria-hidden="true">⌄</span>
      </button>
      {open &&
        createPortal(
          <div
            className="session-account-overlay"
            onPointerDown={(event) => {
              if (event.target === event.currentTarget) setOpen(false);
            }}
          >
            <section
              ref={panel}
              tabIndex={-1}
              className="session-account-panel"
              role="dialog"
              aria-modal="true"
              aria-label={t("会话账号", "Conversation account")}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.stopPropagation();
                  setOpen(false);
                } else if (event.key === "Tab") {
                  const controls = Array.from(
                    event.currentTarget.querySelectorAll<HTMLElement>(
                      "button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href]",
                    ),
                  );
                  const first = controls[0],
                    last = controls.at(-1);
                  if (
                    event.shiftKey &&
                    (document.activeElement === first ||
                      document.activeElement === event.currentTarget)
                  ) {
                    event.preventDefault();
                    last?.focus();
                  } else if (
                    !event.shiftKey &&
                    document.activeElement === last
                  ) {
                    event.preventDefault();
                    first?.focus();
                  }
                }
              }}
            >
              <div className="panel-heading">
                <strong>{t("会话账号", "Conversation account")}</strong>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={t("关闭账号设置", "Close account settings")}
                  onClick={() => setOpen(false)}
                >
                  <Icon name="close" />
                </button>
              </div>
              <AccountSelection
                accounts={accounts}
                provider={agent.provider}
                environment={
                  session.environment_id ?? agent.environment_id ?? "local"
                }
                value={draft}
                onChange={setDraft}
                disabled={busy || saving || demo}
                t={t}
              />
              <p className="form-hint">
                {busy
                  ? t(
                      "任务结束后可更换账号。",
                      "Change accounts after the current task finishes.",
                    )
                  : t(
                      "切换后将用新账号继续；已有回复保留，其他会话不受影响。",
                      "Continue with the new account. Existing replies stay here; other conversations keep their accounts.",
                    )}
              </p>
              <button
                type="button"
                className="primary"
                disabled={busy || saving || demo}
                onClick={async () => {
                  setSaving(true);
                  try {
                    if (
                      await mutate(
                        `/api/sessions/${encodeURIComponent(session.id)}/account`,
                        accountSettings(draft),
                      )
                    )
                      setOpen(false);
                  } finally {
                    setSaving(false);
                  }
                }}
              >
                {saving
                  ? t("保存中…", "Saving…")
                  : t("保存账号设置", "Save account settings")}
              </button>
            </section>
          </div>,
          document.body,
        )}
    </div>
  );
}
