import * as uiMessages from "./messages";
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
        t(...uiMessages.accountattempts_removed_account_250a5c))
      : t(...uiMessages.accountattempts_device_login_5ac5e5);
  const status = (value: string) =>
    ({
      started: t(...uiMessages.accountattempts_started_a775f1),
      running: t(...uiMessages.accountattempts_in_use_12e59e),
      completed: t(...uiMessages.accountattempts_completed_066012),
      failed: t(...uiMessages.accountattempts_failed_840d25),
      rejected: t(...uiMessages.accountattempts_account_unavailable_c22d50),
      interrupted: t(...uiMessages.accountattempts_interrupted_464894),
      rate_limited: t(...uiMessages.accountattempts_quota_reached_da5aeb),
      expired: t(...uiMessages.accountattempts_sign_in_required_e04e32),
      cancelled: t(...uiMessages.accountattempts_cancelled_2dbec7),
      waiting: t(...uiMessages.accountattempts_waiting_for_an_account_afd8d7),
    })[value] ?? value;
  const last = activity.at(-1);
  const needsAction =
    actionRequired && last?.kind === "account_action_required";
  return (
    <div className="account-attempts">
      {active && last?.kind === "account_waiting" && (
        <p role="status">
          {t(
            ...uiMessages.accountattempts_waiting_for_an_available_subscription_account_0b2ddd,
          )}
        </p>
      )}
      {needsAction && (
        <div className="account-action-required" role="status">
          <p>
            {t(
              ...uiMessages.accountattempts_execution_progress_is_preserved_choose_an_acc_f88fd1,
            )}
          </p>
          {onConfigureAccount && (
            <button
              type="button"
              className="secondary"
              onClick={onConfigureAccount}
            >
              {t(
                ...uiMessages.accountattempts_choose_an_account_to_continue_d01241,
              )}
            </button>
          )}
        </div>
      )}
      <details>
        <summary>
          {t(...uiMessages.accountattempts_account_activity_b7719e)}
        </summary>
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
                    ? t(
                        ...uiMessages.accountattempts_subscription_accounts_49009b,
                      )
                    : name(payload.account_id ?? payload.to_account_id)}
                </strong>
                <span>
                  {event.kind === "account_switched" ||
                  event.kind === "account_changed"
                    ? t(...uiMessages.accountattempts_account_switched_00b6ad)
                    : event.kind === "account_action_required"
                      ? t(
                          ...uiMessages.accountattempts_account_selection_required_8d1231,
                        )
                      : event.kind === "account_waiting"
                        ? t(
                            ...uiMessages.accountattempts_waiting_for_an_account_afd8d7,
                          )
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
