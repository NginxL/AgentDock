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
        eyebrow="USAGE, WITHOUT THE GUESSWORK"
        title={t("额度与账单，各自清楚", "Know your usage and your billing")}
        description={t(
          "按需调用本机 AgentMeter 读取 Codex / Claude 额度。订阅信息由你登记，额度未知时明确显示未知。",
          "Fetch Codex / Claude quotas on demand through local AgentMeter. Enter billing details yourself; missing quota is always shown as unknown.",
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
                {quota?.error && <p className="inline-error">{quota.error}</p>}
              </div>
              <div className="quota-source">
                <span>
                  AgentMeter · <DateText date={quota?.fetched_at} lang={lang} />
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
                "仅登记信息，不会购买、续费或更改任何订阅。Claude 的 ACP 执行费用由 API 账户另行结算。",
                "This records information only; it does not purchase, renew or change subscriptions. Claude ACP execution is billed separately to the API account.",
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
              "额度来自你安装的 AgentMeter，账户凭据不传入浏览器。当前工作台不估算 token 费用，也不会把额度重置当作续费时间。",
              "Quotas come from your installed AgentMeter; account credentials never enter the browser. This workspace does not estimate token costs or treat quota reset as subscription renewal.",
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
  return (
    <div className="quota-window">
      <div className="record-heading">
        <span>{window.label}</span>
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
          aria-label={window.label}
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
