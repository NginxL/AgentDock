import * as uiMessages from "../messages";
import { useState } from "react";
import { remainingPercent } from "../api";
import type {
  Agent,
  Account,
  Session,
  Environment,
  Language,
  Mutate,
  Provider,
  Quota,
  Subscription,
  Translate,
} from "../types";
import { DateText, Empty, Icon, PageTitle } from "../ui";
import ProviderIcon from "../ProviderIcon";
import { providerNames } from "../ProviderIcon";
import { usageTargets } from "../usageTargets";
import { accountStatus } from "../AccountSelection";

export default function Usage({
  t,
  lang,
  quotas,
  subscriptions,
  agents,
  sessions = [],
  accounts = [],
  environments = [],
  onAddAgent,
  refreshing,
  refreshFailed,
  busy,
  mutate,
}: {
  t: Translate;
  lang: Language;
  quotas: Quota[];
  subscriptions: Subscription[];
  agents: Agent[];
  sessions?: Session[];
  accounts?: Account[];
  environments?: Environment[];
  onAddAgent: () => void;
  refreshing: boolean;
  refreshFailed: boolean;
  busy: boolean;
  mutate: Mutate;
}) {
  const [editing, setEditing] = useState<{
    provider: Provider;
    environment: string;
  } | null>(null);
  const [plan, setPlan] = useState("");
  const [renewal, setRenewal] = useState("");
  const [cost, setCost] = useState("");
  const [currency, setCurrency] = useState("USD");
  const targets = usageTargets(agents, sessions, accounts);
  function edit(provider: Provider, environment: string) {
    if (editing?.provider === provider && editing.environment === environment) {
      setEditing(null);
      return;
    }
    const record = subscriptions.find(
      (s) =>
        s.provider === provider &&
        (s.environment_id ?? "local") === environment,
    );
    setEditing({ provider, environment });
    setPlan(record?.plan ?? "");
    setRenewal(record?.renewal_date ?? "");
    setCost(record?.monthly_cost == null ? "" : String(record.monthly_cost));
    setCurrency(record?.currency ?? "USD");
  }
  return (
    <>
      <PageTitle
        eyebrow={t(...uiMessages.usage_account_overview_d105eb)}
        title={t(...uiMessages.usage_usage_billing_59a0e5)}
      />
      {!agents.length && (
        <section className="panel">
          <Empty
            icon="dock"
            title={t(...uiMessages.usage_no_agents_yet_be317a)}
          >
            {t(
              ...uiMessages.usage_add_an_agent_to_view_usage_and_billing_a23800,
            )}
            <div>
              <button className="primary" onClick={onAddAgent}>
                {t(...uiMessages.usage_add_agent_3bb60f)}
              </button>
            </div>
          </Empty>
        </section>
      )}
      {refreshFailed && !!agents.length && (
        <p className="inline-error" role="status">
          {t(
            ...uiMessages.usage_usage_update_failed_retrying_automatically_9e241c,
          )}
        </p>
      )}
      <div className="usage-grid">
        {targets.map((target) => {
          const { provider, environment, account, managed } = target;
          const agentNames = target.agentNames.join(" · ");
          const quota: Quota | undefined = managed
            ? account?.quota
              ? {
                  provider,
                  source: "managed-account",
                  status: account.quota.status ?? "unknown",
                  fetched_at: account.quota.fetched_at,
                  plan: account.identity?.plan,
                  windows: (account.quota.windows ?? []).map((window) => ({
                    ...window,
                    label:
                      window.label ??
                      {
                        primary: t(...uiMessages.usage_current_window_2bfa6f),
                        secondary: t(
                          ...uiMessages.usage_additional_window_8e7cb3,
                        ),
                        session: t(...uiMessages.usage_session_limit_3f78ff),
                        weekly: t(...uiMessages.usage_weekly_limit_775852),
                      }[window.name ?? ""] ??
                      window.name ??
                      t(...uiMessages.usage_quota_5b9897),
                  })),
                }
              : undefined
            : quotas.find(
                (q) =>
                  q.provider === provider &&
                  (q.environment_id ?? "local") === environment,
              );
          const billing = !managed
            ? subscriptions.find(
                (s) =>
                  s.provider === provider &&
                  (s.environment_id ?? "local") === environment,
              )
            : undefined;
          const available =
            quota?.status === "ok" ||
            quota?.status === "ready" ||
            quota?.status === "available" ||
            quota?.status === "success" ||
            quota?.status === "exhausted";
          return (
            <section className="panel quota-card" key={target.key}>
              <header>
                <div className="provider-symbol" aria-hidden="true">
                  <ProviderIcon provider={provider} />
                </div>
                <div>
                  <h2>
                    {managed
                      ? (account?.label ??
                        (target.accountID
                          ? t(...uiMessages.usage_account_unavailable_addd41)
                          : t(...uiMessages.usage_no_account_selected_e5c4da)))
                      : agentNames}
                  </h2>
                  <small className="quota-identity">
                    {providerNames[provider]} ·{" "}
                    {environment === "local"
                      ? t(...uiMessages.usage_this_mac_e21573)
                      : (environments.find((e) => e.id === environment)?.name ??
                        t(...uiMessages.usage_remote_device_be5b9e))}{" "}
                    ·{" "}
                    {managed
                      ? t(...uiMessages.usage_subscription_account_41185d)
                      : t(...uiMessages.usage_device_login_5ac5e5)}
                  </small>
                  <span>
                    {quota?.plan ||
                      (managed && account?.identity?.plan) ||
                      billing?.plan ||
                      t(...uiMessages.usage_plan_unknown_d27bfa)}
                  </span>
                </div>
                <span className={`pill ${available ? "good" : ""}`}>
                  {refreshing
                    ? t(...uiMessages.usage_updating_246dca)
                    : available
                      ? t(...uiMessages.usage_fetched_3fa906)
                      : quota?.status === "stale"
                        ? t(...uiMessages.usage_update_pending_b91a30)
                        : t(...uiMessages.usage_unknown_unavailable_125154)}
                </span>
              </header>
              {managed && (
                <p className="quota-binding">
                  {agentNames}
                  {account ? ` · ${accountStatus(account, t)}` : ""}
                </p>
              )}
              {!!target.sessionNames.length && (
                <p className="quota-binding">
                  {t(...uiMessages.usage_conversations_53bf2d)}:{" "}
                  {target.sessionNames.join(" · ")}
                </p>
              )}
              <div className="quota-windows">
                {quota?.windows?.length ? (
                  quota.windows.map((window, index) => (
                    <QuotaWindow
                      key={`${window.label}-${index}`}
                      window={window}
                      t={t}
                      lang={lang}
                    />
                  ))
                ) : (
                  <div className="quota-unknown">
                    <strong>—</strong>
                    <p>
                      {t(...uiMessages.usage_no_available_quota_data_1b817d)}
                    </p>
                  </div>
                )}
                {quota?.error && quota.error_code !== "outdated_cache" && (
                  <p className="inline-error">
                    {quotaError(quota.error_code, quota.error, t)}
                  </p>
                )}
              </div>
              <div className="quota-source">
                <span>
                  {managed
                    ? t(...uiMessages.usage_account_quota_107b7b)
                    : quota?.source === "demo"
                      ? t(...uiMessages.usage_demo_data_9029c5)
                      : quota?.source === "claude-desktop-snapshot"
                        ? t(...uiMessages.usage_claude_local_snapshot_b92980)
                        : provider === "codex"
                          ? "Codex"
                          : t(
                              ...uiMessages.usage_previously_saved_data_ff28d7,
                            )}{" "}
                  · {t(...uiMessages.usage_data_updated_1bf097)}{" "}
                  <DateText date={quota?.fetched_at} lang={lang} />
                </span>
              </div>
              {managed ? (
                <div className="billing-info">
                  <a href="#/accounts" className="text-button">
                    {t(...uiMessages.usage_manage_account_15a367)} ↗
                  </a>
                </div>
              ) : (
                <div className="billing-info">
                  <div className="record-heading">
                    <h3>
                      {t(...uiMessages.usage_manual_billing_record_859630)}
                    </h3>
                    <button
                      className="text-button"
                      aria-expanded={
                        editing?.provider === provider &&
                        editing.environment === environment
                      }
                      aria-controls="billing-form"
                      onClick={() => edit(provider, environment)}
                    >
                      {t(...uiMessages.usage_edit_b936a3)}
                    </button>
                  </div>
                  <dl>
                    <div>
                      <dt>{t(...uiMessages.usage_next_renewal_bf5cbd)}</dt>
                      <dd>
                        {billing?.renewal_date ||
                          t(...uiMessages.usage_not_recorded_8a37c3)}
                      </dd>
                    </div>
                    <div>
                      <dt>{t(...uiMessages.usage_monthly_cost_b8c3cd)}</dt>
                      <dd>
                        {billing?.monthly_cost == null
                          ? t(...uiMessages.usage_not_recorded_8a37c3)
                          : `${billing.currency} ${Number(billing.monthly_cost).toFixed(2)}`}
                      </dd>
                    </div>
                  </dl>
                </div>
              )}
            </section>
          );
        })}
      </div>
      {editing && (
        <section className="panel inset-form" id="billing-form">
          <div className="panel-heading">
            <h2>
              {t(...uiMessages.usage_edit_billing_record_428d8b)} ·{" "}
              {targets
                .find(
                  (target) =>
                    !target.managed &&
                    target.provider === editing.provider &&
                    target.environment === editing.environment,
                )
                ?.agentNames.join(" · ")}
            </h2>
            <button
              className="icon-button"
              onClick={() => setEditing(null)}
              aria-label={t(...uiMessages.usage_close_billing_editor_b77c8c)}
            >
              <Icon name="close" />
            </button>
          </div>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              await mutate(
                "/api/subscriptions",
                {
                  provider: editing.provider,
                  environment_id: editing.environment,
                  plan: plan.trim(),
                  renewal_date: renewal,
                  monthly_cost: cost.trim() === "" ? null : Number(cost),
                  currency,
                },
                () => setEditing(null),
              );
            }}
          >
            <div className="form-grid">
              <label>
                {t(...uiMessages.usage_plan_ea3c2d)}
                <input
                  value={plan}
                  onChange={(e) => setPlan(e.target.value)}
                  maxLength={100}
                  placeholder="Pro / Max / Plus"
                />
              </label>
              <label>
                {t(...uiMessages.usage_next_renewal_date_0ad1f4)}
                <input
                  type="date"
                  value={renewal}
                  onChange={(e) => setRenewal(e.target.value)}
                />
              </label>
              <label>
                {t(...uiMessages.usage_monthly_cost_optional_3bc94d)}
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={cost}
                  onChange={(e) => setCost(e.target.value)}
                />
              </label>
              <label>
                {t(...uiMessages.usage_currency_ab7a51)}
                <select
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value)}
                >
                  <option>USD</option>
                  <option>CNY</option>
                  <option>EUR</option>
                  <option>GBP</option>
                  <option>JPY</option>
                  <option>HKD</option>
                </select>
              </label>
            </div>
            <p className="form-hint">
              {t(
                ...uiMessages.usage_this_records_information_only_it_does_not_pur_5f498f,
              )}
            </p>
            <button className="primary" disabled={busy}>
              {t(...uiMessages.usage_save_record_22f48a)}
            </button>
          </form>
        </section>
      )}
    </>
  );
}

export function QuotaWindow({
  window,
  t,
  lang,
}: {
  window: Quota["windows"][number];
  t: Translate;
  lang: Language;
}) {
  const remaining = remainingPercent(window.remaining_percent);
  const labels: Record<string, string> = {
    主要窗口: t(...uiMessages.usage_primary_window_399035),
    次要窗口: t(...uiMessages.usage_secondary_window_d549c2),
    "300m": t(...uiMessages.usage_5_hours_c6a364),
    "10080m": t(...uiMessages.usage_7_days_98d1df),
    "5 小时": t(...uiMessages.usage_5_hours_c6a364),
    "7 天": t(...uiMessages.usage_7_days_98d1df),
    Weekly: t(...uiMessages.usage_weekly_14df0d),
    "Weekly window": t(...uiMessages.usage_weekly_window_d98769),
    "5-hour window": t(...uiMessages.usage_5_hour_window_d8f429),
    "5 hours": t(...uiMessages.usage_5_hours_ca0722),
    "5-hour": t(...uiMessages.usage_5_hour_d96bae),
    Session: t(...uiMessages.usage_session_449fbc),
    Quota: t(...uiMessages.usage_quota_5b9897),
    每周额度: t(...uiMessages.usage_weekly_window_d98769),
    "5 小时额度": t(...uiMessages.usage_5_hour_window_d8f429),
  };
  const label = labels[window.label] ?? window.label;
  return (
    <div className="quota-window">
      <div className="record-heading">
        <span>{label}</span>
        <strong>
          {remaining == null
            ? t(...uiMessages.usage_unknown_6c2018)
            : `${Math.round(remaining * 10) / 10}%`}
          <small>
            {remaining != null ? t(...uiMessages.usage__left_ec8259) : ""}
          </small>
        </strong>
      </div>
      {remaining != null ? (
        <div
          className={`meter ${remaining <= 15 ? "low" : ""}`}
          role="progressbar"
          aria-label={label}
          aria-valuenow={remaining}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <span style={{ width: `${remaining}%` }} />
        </div>
      ) : (
        <div
          className="meter unknown"
          aria-label={t(...uiMessages.usage_remaining_quota_unknown_97a65c)}
        />
      )}
      <p>
        {t(...uiMessages.usage_resets_156b0a)}{" "}
        <DateText date={window.reset_at} lang={lang} />
      </p>
    </div>
  );
}

function quotaError(code: string | undefined, fallback: string, t: Translate) {
  const messages: Record<string, [string, string]> = {
    outdated_cache: [
      "显示的是上次额度数据，系统会自动更新。",
      "Showing previous usage. Updates run automatically.",
    ],
    disabled: [
      "启用执行后才能读取额度。",
      "Enable execution before fetching usage.",
    ],
    helper_unconfigured: [
      "请先配置本地额度读取组件。",
      "Configure the local usage helper first.",
    ],
    helper_config_invalid: [
      "额度读取组件的命令配置无效，请检查本地配置。",
      "The usage helper command is invalid. Check the local configuration.",
    ],
    refresh_throttled: [
      "刷新过于频繁，请稍后再试。",
      "Please wait before refreshing again.",
    ],
    invalid_snapshot: [
      "读取到的额度数据格式无效，请稍后重试。",
      "The usage helper returned an invalid snapshot. Try again later.",
    ],
    read_failed: [
      "额度读取失败，请检查本机客户端的登录状态和权限。",
      "Could not read usage. Check the local client login and permissions.",
    ],
    authorization_required: [
      "旧版额度数据不可用，正在等待本地快照。",
      "Legacy usage data is unavailable. Waiting for the local snapshot.",
    ],
    not_installed: [
      "未找到服务的命令行客户端，请检查安装。",
      "The provider CLI was not found. Check its installation.",
    ],
    not_signed_in: [
      "请先在官方客户端登录订阅账号。",
      "Sign in to a subscription account in the official client first.",
    ],
    expired: [
      "登录已过期，请在官方客户端重新登录。",
      "Login has expired. Sign in again in the official client.",
    ],
    rate_limited: [
      "提供方暂时限流，请稍后重试。",
      "The provider is rate limiting requests. Try again later.",
    ],
    timeout: [
      "额度读取超时，请稍后重试。",
      "The usage request timed out. Try again later.",
    ],
    unavailable: [
      "额度暂不可用，请检查登录、订阅与网络。",
      "Usage is unavailable. Check the login, subscription and network.",
    ],
  };
  const message = code ? messages[code] : undefined;
  return message ? t(...message) : fallback;
}
