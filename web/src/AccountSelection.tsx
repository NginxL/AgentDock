import * as uiMessages from "./messages";
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
          {t(...uiMessages.accountselection_subscription_account_41185d)}
          <select
            value={value.account_id ?? ""}
            onChange={(event) =>
              onChange({ ...value, account_id: event.target.value || null })
            }
          >
            <option value="">
              {policy === "manual"
                ? t(...uiMessages.accountselection_use_device_login_bc3caa)
                : t(
                    ...uiMessages.accountselection_choose_an_available_account_8c52e4,
                  )}
            </option>
            {missing && (
              <option value={value.account_id!} disabled>
                {t(...uiMessages.accountselection_account_unavailable_addd41)}
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
          {t(...uiMessages.accountselection_account_selection_7f336b)}
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
            <option value="manual">
              {t(...uiMessages.accountselection_fixed_account_0b00b2)}
            </option>
            <option value="auto">
              {t(...uiMessages.accountselection_automatic_selection_f49778)}
            </option>
            <option value="failover" disabled={!failoverEnabled}>
              {t(
                ...uiMessages.accountselection_switch_on_quota_or_sign_in_failure_57df9a,
              )}
            </option>
          </select>
        </label>
      </div>
      {policy !== "manual" && (
        <p className="form-hint">
          {policy === "auto"
            ? t(
                ...uiMessages.accountselection_choose_an_available_account_for_the_first_run_7d73b7,
              )
            : t(
                ...uiMessages.accountselection_switch_only_after_a_definite_quota_or_sign_in_c7fa4e,
              )}
        </p>
      )}
      {policy !== "manual" && (
        <div className="account-pool">
          <span>
            {t(...uiMessages.accountselection_allowed_accounts_aa8b5c)}
          </span>
          <p className="form-hint">
            {t(
              ...uiMessages.accountselection_leave_unchecked_to_use_all_available_accounts_5fde72,
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
                ...uiMessages.accountselection_add_a_subscription_for_this_device_on_the_acc_9e121e,
              )}
            </p>
          )}
        </div>
      )}
      <a className="text-button account-manage-link" href="#/accounts">
        {t(...uiMessages.accountselection_manage_subscription_accounts_32da58)}{" "}
        ↗
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
      ? t(...uiMessages.accountselection_account_unavailable_addd41)
      : (session.account_policy ?? "manual") !== "manual"
        ? t(...uiMessages.accountselection_automatic_account_8f9e23)
        : t(...uiMessages.accountselection_use_device_login_bc3caa));
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
              aria-label={t(
                ...uiMessages.accountselection_conversation_account_224495,
              )}
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
                <strong>
                  {t(
                    ...uiMessages.accountselection_conversation_account_224495,
                  )}
                </strong>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={t(
                    ...uiMessages.accountselection_close_account_settings_e031b9,
                  )}
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
                      ...uiMessages.accountselection_change_accounts_after_the_current_task_finish_44c0b1,
                    )
                  : t(
                      ...uiMessages.accountselection_continue_with_the_new_account_existing_replie_55c58e,
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
                  ? t(...uiMessages.accountselection_saving_8f287b)
                  : t(
                      ...uiMessages.accountselection_save_account_settings_a733d4,
                    )}
              </button>
            </section>
          </div>,
          document.body,
        )}
    </div>
  );
}
