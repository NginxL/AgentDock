import { useState } from "react";
import { remainingPercent } from "../api";
import type {
  Agent,
  Environment,
  Language,
  Mutate,
  Provider,
  Quota,
  Subscription,
  Translate,
} from "../types";
import { DateText, Empty, Icon, PageTitle } from "../ui";

export default function Usage({
  t,
  lang,
  quotas,
  subscriptions,
  agents,
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
  function edit(provider: Provider, environment: string) {
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
        eyebrow={t("账户概览", "ACCOUNT OVERVIEW")}
        title={t("额度与订阅", "Usage & billing")}
      />
      {!agents.length && (
        <section className="panel">
          <Empty icon="dock" title={t("暂无 Agent", "No agents yet")}>
            {t(
              "添加 Agent 后查看额度与订阅。",
              "Add an agent to view usage and billing.",
            )}
            <div>
              <button className="primary" onClick={onAddAgent}>
                {t("添加 Agent", "Add agent")}
              </button>
            </div>
          </Empty>
        </section>
      )}
      {refreshFailed && !!agents.length && (
        <p className="inline-error" role="status">
          {t(
            "额度更新失败，稍后自动重试。",
            "Usage update failed. Retrying automatically.",
          )}
        </p>
      )}
      <div className="usage-grid">
        {[
          ...new Map(
            agents.map((agent) => [
              `${agent.environment_id ?? "local"}:${agent.provider}`,
              agent,
            ]),
          ).values(),
        ].map((agent) => {
          const provider = agent.provider;
          const environment = agent.environment_id ?? "local";
          const quota = quotas.find(
            (q) =>
              q.provider === provider &&
              (q.environment_id ?? "local") === environment,
          );
          const billing = subscriptions.find(
            (s) =>
              s.provider === provider &&
              (s.environment_id ?? "local") === environment,
          );
          const available =
            quota?.status === "ok" ||
            quota?.status === "available" ||
            quota?.status === "success";
          return (
            <section
              className="panel quota-card"
              key={`${environment}:${provider}`}
            >
              <header>
                <div className={`provider-symbol ${provider}`}>
                  {provider === "codex" ? "C" : "✳"}
                </div>
                <div>
                  <h2>{provider === "codex" ? "Codex" : "Claude"}</h2>
                  <span className="environment-name">
                    {environment === "local"
                      ? t("本机", "This Mac")
                      : (environments.find((e) => e.id === environment)?.name ??
                        t("远端", "Remote"))}
                  </span>
                  <span>
                    {quota?.plan ||
                      billing?.plan ||
                      t("方案未知", "Plan unknown")}
                  </span>
                </div>
                <span className={`pill ${available ? "good" : ""}`}>
                  {refreshing
                    ? t("更新中", "Updating")
                    : available
                      ? t("已读取", "Fetched")
                      : quota?.status === "stale"
                        ? t("待更新", "Update pending")
                        : t("未知 / 不可用", "Unknown / unavailable")}
                </span>
              </header>
              <p className="quota-agents">
                {agents
                  .filter(
                    (a) =>
                      a.provider === provider &&
                      (a.environment_id ?? "local") === environment,
                  )
                  .map((a) => a.name)
                  .join(" · ")}
              </p>
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
                    <p>{t("尚无可用额度数据", "No available quota data")}</p>
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
                  {quota?.source === "demo"
                    ? t("演示数据", "Demo data")
                    : quota?.source === "claude-desktop-snapshot"
                      ? t("Claude 本地快照", "Claude local snapshot")
                      : provider === "codex"
                        ? "Codex"
                        : t("上次保存的数据", "Previously saved data")}{" "}
                  · {t("数据更新于", "Data updated")}{" "}
                  <DateText date={quota?.fetched_at} lang={lang} />
                </span>
              </div>
              <div className="billing-info">
                <div className="record-heading">
                  <h3>{t("手动订阅记录", "Manual billing record")}</h3>
                  <button
                    className="text-button"
                    onClick={() => edit(provider, environment)}
                  >
                    {t("编辑", "Edit")}
                  </button>
                </div>
                <dl>
                  <div>
                    <dt>{t("下次续费", "Next renewal")}</dt>
                    <dd>
                      {billing?.renewal_date || t("未登记", "Not recorded")}
                    </dd>
                  </div>
                  <div>
                    <dt>{t("每月费用", "Monthly cost")}</dt>
                    <dd>
                      {billing?.monthly_cost == null
                        ? t("未登记", "Not recorded")
                        : `${billing.currency} ${Number(billing.monthly_cost).toFixed(2)}`}
                    </dd>
                  </div>
                </dl>
              </div>
            </section>
          );
        })}
      </div>
      {editing && (
        <section className="panel inset-form">
          <div className="panel-heading">
            <h2>
              {t("编辑订阅记录", "Edit billing record")} ·{" "}
              {editing.provider === "codex" ? "Codex" : "Claude"}
            </h2>
            <button
              className="icon-button"
              onClick={() => setEditing(null)}
              aria-label={t("关闭订阅编辑器", "Close billing editor")}
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
                {t("订阅方案", "Plan")}
                <input
                  value={plan}
                  onChange={(e) => setPlan(e.target.value)}
                  maxLength={100}
                  placeholder="Pro / Max / Plus"
                />
              </label>
              <label>
                {t("下次续费日期", "Next renewal date")}
                <input
                  type="date"
                  value={renewal}
                  onChange={(e) => setRenewal(e.target.value)}
                />
              </label>
              <label>
                {t("每月费用（可留空）", "Monthly cost (optional)")}
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={cost}
                  onChange={(e) => setCost(e.target.value)}
                />
              </label>
              <label>
                {t("币种", "Currency")}
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
                "仅登记信息，不会购买、续费或更改任何订阅。实际计费由所选环境 CLI 使用的账户与服务方案决定。",
                "This records information only; it does not purchase, renew or change subscriptions. Actual billing follows the account and plan used by the selected environment’s CLI.",
              )}
            </p>
            <button className="primary" disabled={busy}>
              {t("保存记录", "Save record")}
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
    主要窗口: t("主要窗口", "Primary window"),
    次要窗口: t("次要窗口", "Secondary window"),
    "300m": t("5 小时", "5 hours"),
    "10080m": t("7 天", "7 days"),
    "5 小时": t("5 小时", "5 hours"),
    "7 天": t("7 天", "7 days"),
    Weekly: t("每周额度", "Weekly"),
    "Weekly window": t("每周额度", "Weekly window"),
    "5-hour window": t("5 小时额度", "5-hour window"),
    "5 hours": t("5 小时额度", "5 hours"),
    "5-hour": t("5 小时额度", "5-hour"),
    Session: t("当前会话额度", "Session"),
    Quota: t("额度", "Quota"),
    每周额度: t("每周额度", "Weekly window"),
    "5 小时额度": t("5 小时额度", "5-hour window"),
  };
  const label = labels[window.label] ?? window.label;
  return (
    <div className="quota-window">
      <div className="record-heading">
        <span>{label}</span>
        <strong>
          {remaining == null
            ? t("未知", "Unknown")
            : `${Math.round(remaining * 10) / 10}%`}
          <small>{remaining != null ? t(" 剩余", " left") : ""}</small>
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
          aria-label={t("剩余额度未知", "Remaining quota unknown")}
        />
      )}
      <p>
        {t("重置", "Resets")} <DateText date={window.reset_at} lang={lang} />
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
