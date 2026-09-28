import { useState } from "react";
import { remainingPercent } from "../api";
import type {
  Language,
  Mutate,
  Provider,
  Quota,
  Subscription,
  Translate,
} from "../types";
import { DateText, Icon, PageTitle } from "../ui";

export default function Usage({
  t,
  lang,
  quotas,
  subscriptions,
  runtimeEnabled,
  busy,
  mutate,
}: {
  t: Translate;
  lang: Language;
  quotas: Quota[];
  subscriptions: Subscription[];
  runtimeEnabled: boolean;
  busy: boolean;
  mutate: Mutate;
}) {
  const [editing, setEditing] = useState<Provider | null>(null);
  const [plan, setPlan] = useState("");
  const [renewal, setRenewal] = useState("");
  const [cost, setCost] = useState("");
  const [currency, setCurrency] = useState("USD");
  function edit(provider: Provider) {
    const record = subscriptions.find((s) => s.provider === provider);
    setEditing(provider);
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
        description={t(
          "按需读取 Codex / Claude 额度。订阅信息由你登记，额度未知时明确显示未知。",
          "Fetch Codex / Claude quotas on demand. Enter billing details yourself; missing quota is always shown as unknown.",
        )}
      />
      <div className="usage-grid">
        {(["codex", "claude"] as Provider[]).map((provider) => {
          const quota = quotas.find((q) => q.provider === provider);
          const billing = subscriptions.find((s) => s.provider === provider);
          const available =
            quota?.status === "ok" ||
            quota?.status === "available" ||
            quota?.status === "success";
          return (
            <section className="panel quota-card" key={provider}>
              <header>
                <div className={`provider-symbol ${provider}`}>
                  {provider === "codex" ? "C" : "✳"}
                </div>
                <div>
                  <h2>{provider === "codex" ? "Codex" : "Claude"}</h2>
                  <span>
                    {quota?.plan ||
                      billing?.plan ||
                      t("方案未知", "Plan unknown")}
                  </span>
                </div>
                <span className={`pill ${available ? "good" : ""}`}>
                  {available
                    ? t("已读取", "Fetched")
                    : quota?.status === "stale"
                      ? t("缓存已过期", "Outdated cache")
                      : t("未知 / 不可用", "Unknown / unavailable")}
                </span>
              </header>
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
                {quota?.error && (
                  <p className="inline-error">
                    {quotaError(quota.error_code, quota.error, t)}
                  </p>
                )}
              </div>
              <div className="quota-source">
                <span>
                  {quota?.source === "demo"
                    ? t("演示数据", "Demo data")
                    : quota?.source || "AgentDock"}{" "}
                  · <DateText date={quota?.fetched_at} lang={lang} />
                </span>
                <button
                  className="text-button"
                  disabled={busy || !runtimeEnabled}
                  onClick={() =>
                    void mutate("/api/quotas/refresh", { provider })
                  }
                >
                  <Icon name="refresh" size={15} />
                  {t("读取额度", "Fetch usage")}
                </button>
              </div>
              {provider === "claude" && quota?.source !== "AgentMeter" && (
                <button
                  className="text-button"
                  disabled={busy || !runtimeEnabled}
                  onClick={() =>
                    void mutate("/api/quotas/authorize", { provider: "claude" })
                  }
                >
                  {t(
                    "连接 Claude（钥匙串授权）",
                    "Connect Claude (Keychain access)",
                  )}
                </button>
              )}
              <div className="billing-info">
                <div className="record-heading">
                  <h3>{t("手动订阅记录", "Manual billing record")}</h3>
                  <button
                    className="text-button"
                    onClick={() => edit(provider)}
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
      {!runtimeEnabled && (
        <p className="form-hint">
          {t(
            "执行未启用，额度读取按钮已禁用。连接或刷新工作台不会自动查询远端服务。",
            "Quota fetching is disabled while execution is off. Connecting or refreshing the workspace does not contact remote usage services.",
          )}
        </p>
      )}
      {editing && (
        <section className="panel inset-form">
          <div className="panel-heading">
            <h2>
              {t("编辑订阅记录", "Edit billing record")} ·{" "}
              {editing === "codex" ? "Codex" : "Claude"}
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
                  provider: editing,
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
                "仅登记信息，不会购买、续费或更改任何订阅。实际计费由本机 CLI 使用的账户与服务方案决定。",
                "This records information only; it does not purchase, renew or change subscriptions. Actual billing follows the account and plan used by the local CLI.",
              )}
            </p>
            <button className="primary" disabled={busy}>
              {t("保存记录", "Save record")}
            </button>
          </form>
        </section>
      )}
      <div className="usage-explainer">
        <Icon name="shield" size={22} />
        <div>
          <h3>{t("只展示有来源的数据", "Show only data with a source")}</h3>
          <p>
            {t(
              "内置读取组件使用提供方的本机登录，账户凭据不传入浏览器。当前工作台不估算 token 费用，也不会把额度重置当作续费时间。",
              "The built-in reader uses existing provider logins; account credentials never enter the browser. This workspace does not estimate token costs or treat quota reset as subscription renewal.",
            )}
          </p>
        </div>
      </div>
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
    authorization_required: [
      "请点击“连接 Claude”，授权读取已有的钥匙串凭据。",
      "Choose Connect Claude to approve access to the existing Keychain credential.",
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
