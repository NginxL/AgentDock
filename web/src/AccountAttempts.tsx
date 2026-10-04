import { accountError } from "./accountDisplay";
import type { Account, AccountAttempt, AgentEvent, Translate } from "./types";

export default function AccountAttempts({
  attempts = [],
  events,
  accounts = [],
  t,
  active = true,
  actionRequired = true,
  onConfigureAccount,
}: {
  attempts?: AccountAttempt[];
  events: AgentEvent[];
  accounts?: Account[];
  t: Translate;
  active?: boolean;
  actionRequired?: boolean;
  onConfigureAccount?: () => void;
}) {
  const managedAttempts = attempts.filter((attempt) => !!attempt.account_id);
  const activity = events.filter(
    (event) =>
      [
        "account_attempt",
        "account_switched",
        "account_changed",
        "account_waiting",
        "account_action_required",
      ].includes(event.kind) &&
      (event.kind === "account_waiting" ||
        event.kind === "account_action_required" ||
        (event.payload &&
          typeof event.payload === "object" &&
          ["account_id", "to_account_id", "previous_account_id"].some(
            (key) => !!(event.payload as Record<string, unknown>)[key],
          ))),
  );
  if (!managedAttempts.length && !activity.length) return null;
  const name = (id: unknown) =>
    typeof id === "string"
      ? (accounts.find((account) => account.id === id)?.label ??
        t("已移除的账号", "Removed account"))
      : t("设备登录", "Device login");
  const status = (value: string) =>
    ({
      started: t("开始使用", "Started"),
      running: t("使用中", "In use"),
      completed: t("完成", "Completed"),
      failed: t("失败", "Failed"),
      rejected: t("账号暂不可用", "Account unavailable"),
      interrupted: t("已中断", "Interrupted"),
      rate_limited: t("额度受限", "Quota reached"),
      expired: t("需要登录", "Sign-in required"),
      cancelled: t("已取消", "Cancelled"),
      waiting: t("等待可用账号", "Waiting for an account"),
    })[value] ?? value;
  const last = activity.at(-1);
  const needsAction =
    actionRequired && last?.kind === "account_action_required";
  return (
    <div className="account-attempts">
      {active && last?.kind === "account_waiting" && (
        <p role="status">
          {t(
            "正在等待可用订阅账号。",
            "Waiting for an available subscription account.",
          )}
        </p>
      )}
      {needsAction && (
        <div className="account-action-required" role="status">
          <p>
            {t(
              "已保留执行现场，请选择账号后继续。",
              "Execution progress is preserved. Choose an account to continue.",
            )}
          </p>
          {onConfigureAccount && (
            <button
              type="button"
              className="secondary"
              onClick={onConfigureAccount}
            >
              {t("选择账号后继续", "Choose an account to continue")}
            </button>
          )}
        </div>
      )}
      <details>
        <summary>{t("账号使用记录", "Account activity")}</summary>
        <ol>
          {managedAttempts.map((attempt) => (
            <li key={attempt.id}>
              <strong>{name(attempt.account_id)}</strong>
              <span>{status(attempt.status)}</span>
              {attempt.error_code && (
                <small>{accountError(attempt.error_code, t)}</small>
              )}
            </li>
          ))}
          {activity.map((event) => {
            const payload =
              event.payload && typeof event.payload === "object"
                ? (event.payload as Record<string, unknown>)
                : {};
            return (
              <li key={event.id}>
                <strong>
                  {event.kind === "account_waiting" && !payload.account_id
                    ? t("订阅账号", "Subscription accounts")
                    : name(payload.account_id ?? payload.to_account_id)}
                </strong>
                <span>
                  {event.kind === "account_switched" ||
                  event.kind === "account_changed"
                    ? t("已切换账号", "Account switched")
                    : event.kind === "account_action_required"
                      ? t("等待选择账号", "Account selection required")
                      : event.kind === "account_waiting"
                        ? t("等待可用账号", "Waiting for an account")
                        : status(
                            typeof payload.status === "string"
                              ? payload.status
                              : "started",
                          )}
                </span>
              </li>
            );
          })}
        </ol>
      </details>
    </div>
  );
}
