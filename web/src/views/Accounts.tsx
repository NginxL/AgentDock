import * as uiMessages from "../messages";
import { useEffect, useState } from "react";
import type { Account, DockState, Mutate, Translate } from "../types";
import { request, remainingPercent } from "../api";
import { accountStatus } from "../AccountSelection";
import ProviderIcon from "../ProviderIcon";
import { Empty, Icon } from "../ui";
import {
  accountError,
  resetCountdown,
  quotaWindow,
  quotaSource,
} from "../accountDisplay";
import ExperimentalFeatures, { useFeature } from "../ExperimentalFeatures";
import NativeAccounts from "../NativeAccounts";
import { exactTokens } from "../metrics";
import { clearModelCatalog } from "../modelCatalog";

type LoginJob = {
  status:
    | "idle"
    | "starting"
    | "waiting"
    | "running"
    | "completed"
    | "failed"
    | "cancelled"
    | "cancelling";
  url?: string;
  code?: string;
  device_code?: string;
  error?: string;
  error_code?: string;
  input_required?: boolean;
};
function authorizationURL(value?: string) {
  try {
    const url = new URL(value ?? "");
    return url.protocol === "https:" ||
      (url.protocol === "http:" &&
        ["localhost", "127.0.0.1"].includes(url.hostname))
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}

function AccountLogin({
  account,
  token,
  busy,
  mutate,
  onChanged,
  onSettled,
  close,
  t,
}: {
  account: Account;
  token: string;
  busy: boolean;
  mutate: Mutate;
  onChanged: () => void;
  onSettled: () => void;
  close: () => void;
  t: Translate;
}) {
  const [job, setJob] = useState<LoginJob>();
  const [code, setCode] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let previous = "";
    async function poll() {
      try {
        const next = await request<LoginJob>(
          token,
          `/api/accounts/${encodeURIComponent(account.id)}/login`,
          undefined,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setJob(next);
        setFailed(false);
        if (next.status === "completed" && previous !== "completed") {
          clearModelCatalog();
          onChanged();
        }
        if (["completed", "failed", "cancelled"].includes(next.status))
          onSettled();
        previous = next.status;
        if (
          ["running", "idle", "starting", "waiting", "cancelling"].includes(
            next.status,
          )
        )
          timer = setTimeout(poll, 1500);
      } catch {
        if (!controller.signal.aborted) {
          setFailed(true);
          timer = setTimeout(poll, 3000);
        }
      }
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [account.id, token]);
  const url = authorizationURL(job?.url);
  return (
    <section
      className="account-login"
      aria-label={t(`登录 ${account.label}`, `Sign in to ${account.label}`)}
    >
      <div className="panel-heading">
        <strong>{t(...uiMessages.accounts_authorize_account_83a506)}</strong>
        <button
          type="button"
          className="icon-button"
          aria-label={t(...uiMessages.accounts_close_sign_in_panel_37ff5b)}
          onClick={close}
        >
          <Icon name="close" />
        </button>
      </div>
      {failed ? (
        <p className="inline-error" role="status">
          {t(...uiMessages.accounts_cannot_read_sign_in_status_retrying_00162f)}
        </p>
      ) : (
        <p role="status">
          {job?.status === "completed"
            ? t(...uiMessages.accounts_signed_in_this_account_is_ready_14509f)
            : job?.status === "failed"
              ? accountError(job.error_code ?? "native_login_failed", t)
              : job?.status === "cancelled"
                ? t(...uiMessages.accounts_sign_in_cancelled_b2e73f)
                : t(
                    ...uiMessages.accounts_complete_authorization_in_your_browser_9ce850,
                  )}
        </p>
      )}
      {job && ["running", "starting", "waiting"].includes(job.status) && (
        <>
          {url && (
            <a
              className="primary account-login-link"
              href={url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t(...uiMessages.accounts_open_sign_in_page_da262f)} ↗
            </a>
          )}
          {(job.code || job.device_code) && (
            <p>
              {t(...uiMessages.accounts_verification_code_75e7d2)}：
              <code className="account-device-code">
                {job.code || job.device_code}
              </code>
            </p>
          )}
          {(job.input_required ||
            (account.provider === "claude" && job.status === "waiting")) && (
            <form
              onSubmit={async (event) => {
                event.preventDefault();
                if (
                  await mutate(
                    `/api/accounts/${encodeURIComponent(account.id)}/input`,
                    { code: code.trim() },
                  )
                )
                  setCode("");
              }}
            >
              <label>
                {t(
                  ...uiMessages.accounts_authorization_code_only_if_provided_by_the_si_7c83a7,
                )}
                <input
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  autoComplete="off"
                />
              </label>
              <button className="secondary" disabled={busy || !code.trim()}>
                {t(...uiMessages.accounts_submit_code_4918d6)}
              </button>
            </form>
          )}
          <button
            type="button"
            className="text-button"
            disabled={busy}
            onClick={() =>
              void mutate(
                `/api/accounts/${encodeURIComponent(account.id)}/cancel`,
                {},
                () => {
                  setJob({ status: "cancelled" });
                  onSettled();
                },
              )
            }
          >
            {t(...uiMessages.accounts_cancel_sign_in_92777a)}
          </button>
        </>
      )}
    </section>
  );
}

function AccountCard({
  account,
  now,
  state,
  token,
  busy,
  mutate,
  onChanged,
  t,
}: {
  account: Account;
  now: number;
  state: DockState;
  token: string;
  busy: boolean;
  mutate: Mutate;
  onChanged: () => void;
  t: Translate;
}) {
  const nativeEnabled = useFeature("native_switching");
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(account.label);
  const [priority, setPriority] = useState(account.priority ?? 0);
  const [login, setLogin] = useState(false);
  const [loginVersion, setLoginVersion] = useState(0);
  const [loginStarted, setLoginStarted] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [native, setNative] = useState(false);
  const env = state.environments?.find(
    (environment) => environment.id === account.environment_id,
  );
  const active = (state.runs ?? []).some(
    (run) =>
      run.account_id === account.id &&
      ["queued", "running", "waiting"].includes(run.status),
  );
  const disabled = account.status === "disabled" || account.enabled === false;
  const remoteCodex =
    account.provider === "codex" && account.environment_id !== "local";
  const path = `/api/accounts/${encodeURIComponent(account.id)}`;
  async function startLogin(method: "browser" | "device") {
    if (await mutate(`${path}/login`, { method })) {
      setLoginVersion((v) => v + 1);
      setLoginStarted(true);
      setLogin(true);
    }
  }
  return (
    <article className="panel account-card">
      <div className="account-card-heading">
        <ProviderIcon provider={account.provider} />
        <div>
          <h2>{account.label}</h2>
          <small>
            {account.provider === "codex" ? "Codex" : "Claude Code"} ·{" "}
            {account.environment_id === "local"
              ? t(...uiMessages.accounts_this_mac_e21573)
              : (env?.name ?? t(...uiMessages.accounts_remote_device_be5b9e))}
          </small>
        </div>
        <span className={`account-status ${account.status}`}>
          {accountStatus(account, t)}
        </span>
      </div>
      {(account.identity?.email || account.identity?.plan) && (
        <p className="account-identity">
          {[account.identity.email, account.identity.plan]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
      {account.error && (
        <p className="account-error" role="status">
          {accountError(account.error, t)}
        </p>
      )}
      <div className="account-quota">
        {account.quota?.error_code && (
          <p className="muted" role="status">
            {accountError(account.quota.error_code, t)}
          </p>
        )}
        {account.quota?.windows?.length ? (
          account.quota.windows.map((window, index) => {
            const remaining = remainingPercent(window.remaining_percent);
            const name = quotaWindow(window, t);
            return (
              <div key={`${name}-${index}`}>
                <span>{name}</span>
                <strong>
                  {remaining === null
                    ? t(...uiMessages.accounts_unknown_6c2018)
                    : `${Math.round(remaining)}% ${t(...uiMessages.accounts_remaining_aceeef)}`}
                </strong>
                {remaining !== null && (
                  <meter
                    min="0"
                    max="100"
                    value={remaining}
                    aria-label={`${name} ${t(...uiMessages.accounts_remaining_quota_9eb2e7)}`}
                  />
                )}
                {window.reset_at && (
                  <small>
                    <span title={new Date(window.reset_at).toLocaleString()}>
                      {resetCountdown(window.reset_at, now, t)}
                    </span>
                  </small>
                )}
              </div>
            );
          })
        ) : (
          <p className="muted">
            {t(...uiMessages.accounts_quota_not_available_yet_1f4190)}
          </p>
        )}
        {account.provider === "claude" && (
          <small className="muted">
            {quotaSource(account.quota?.source, account.quota?.fetched_at, t)}
          </small>
        )}
        {account.quota?.fetched_at && (
          <small className="muted">
            {t(...uiMessages.accounts_updated_a4e7c7)}{" "}
            {new Date(account.quota.fetched_at).toLocaleString()}
            {account.quota.status !== "ok" &&
            account.quota.status !== "ready" &&
            account.quota.status !== "available"
              ? ` · ${t(...uiMessages.accounts_last_known_data_9b6576)}`
              : ""}
          </small>
        )}
        {account.cooldown_until && (
          <p
            className="muted"
            title={new Date(account.cooldown_until).toLocaleString()}
          >
            {resetCountdown(account.cooldown_until, now, t)}
          </p>
        )}
      </div>
      {account.usage && (
        <div
          className="account-usage"
          aria-label={t(...uiMessages.accounts_agentdock_usage_a4c1d9)}
        >
          <strong>{t(...uiMessages.accounts_agentdock_usage_a4c1d9)}</strong>
          <dl>
            <div>
              <dt>{t(...uiMessages.accounts_total_tokens_b23005)}</dt>
              <dd>{exactTokens(account.usage.total_tokens)}</dd>
            </div>
            <div>
              <dt>{t(...uiMessages.accounts_input_58d1c4)}</dt>
              <dd>{exactTokens(account.usage.input_tokens)}</dd>
            </div>
            <div>
              <dt>{t(...uiMessages.accounts_output_6424f4)}</dt>
              <dd>{exactTokens(account.usage.output_tokens)}</dd>
            </div>
          </dl>
        </div>
      )}
      <div className="button-row account-actions">
        <button
          type="button"
          className="secondary"
          disabled={busy || active}
          aria-expanded={login}
          onClick={() =>
            login
              ? setLogin(false)
              : loginStarted
                ? setLogin(true)
                : void startLogin(
                    account.environment_id === "local" ||
                      account.provider === "claude"
                      ? "browser"
                      : "device",
                  )
          }
        >
          {remoteCodex
            ? t(...uiMessages.accounts_sign_in_with_device_code_18309f)
            : account.status === "pending" || account.status === "expired"
              ? t(...uiMessages.accounts_sign_in_fb4d13)
              : t(...uiMessages.accounts_sign_in_again_f7557d)}
        </button>
        {account.provider === "codex" && !remoteCodex && !login && (
          <button
            type="button"
            className="text-button"
            disabled={busy || active}
            onClick={() => void startLogin("device")}
          >
            {t(...uiMessages.accounts_use_device_code_2af244)}
          </button>
        )}
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={() => void mutate(`${path}/check`, {})}
        >
          {t(...uiMessages.accounts_check_sign_in_43ef4c)}
        </button>
        {account.provider === "codex" && (
          <button
            type="button"
            className="text-button"
            disabled={busy || disabled}
            onClick={() => void mutate(`${path}/refresh`, {})}
          >
            {t(...uiMessages.accounts_refresh_quota_a4ee28)}
          </button>
        )}
        <button
          type="button"
          className="text-button"
          aria-expanded={editing}
          onClick={() => {
            if (!editing) {
              setLabel(account.label);
              setPriority(account.priority ?? 0);
            }
            setEditing(!editing);
          }}
        >
          {t(...uiMessages.accounts_settings_40e3fb)}
        </button>
        {account.environment_id === "local" && account.provider === "codex" && (
          <button
            type="button"
            className="text-button"
            disabled={busy || disabled || active || !nativeEnabled}
            aria-expanded={native}
            onClick={() => setNative(!native)}
          >
            {t(...uiMessages.accounts_native_clients_f4a7c5)}
          </button>
        )}
        <button
          type="button"
          className="text-button danger-text"
          disabled={busy || active}
          aria-expanded={deleting}
          onClick={() => setDeleting(!deleting)}
        >
          {t(...uiMessages.accounts_delete_account_72c2b6)}
        </button>
      </div>
      {native && (
        <NativeAccounts
          account={account}
          token={token}
          close={() => setNative(false)}
          t={t}
        />
      )}
      {deleting && (
        <section
          className="account-delete"
          aria-label={t(...uiMessages.accounts_confirm_account_removal_7d5bc0)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setDeleting(false);
          }}
        >
          <div className="panel-heading">
            <strong>
              {t(`删除「${account.label}」？`, `Delete “${account.label}”?`)}
            </strong>
            <button
              type="button"
              className="icon-button"
              aria-label={t(
                ...uiMessages.accounts_close_delete_confirmation_a9887c,
              )}
              onClick={() => setDeleting(false)}
            >
              <Icon name="close" />
            </button>
          </div>
          <p>
            {t(
              ...uiMessages.accounts_delete_this_saved_sign_in_existing_conversati_62492b,
            )}
          </p>
          <div className="button-row">
            <button
              type="button"
              className="secondary danger"
              disabled={busy || active}
              onClick={() => void mutate(`${path}/delete`, {})}
            >
              {t(...uiMessages.accounts_confirm_account_deletion_8aea97)}
            </button>
            <button
              type="button"
              className="text-button"
              onClick={() => setDeleting(false)}
            >
              {t(...uiMessages.accounts_cancel_68f563)}
            </button>
          </div>
        </section>
      )}
      {login && (
        <AccountLogin
          key={loginVersion}
          account={account}
          token={token}
          busy={busy}
          mutate={mutate}
          onChanged={onChanged}
          onSettled={() => setLoginStarted(false)}
          close={() => setLogin(false)}
          t={t}
        />
      )}
      {editing && (
        <form
          className="account-edit"
          onSubmit={async (event) => {
            event.preventDefault();
            if (await mutate(path, { label: label.trim(), priority }))
              setEditing(false);
          }}
        >
          <div className="panel-heading">
            <strong>{t(...uiMessages.accounts_account_settings_533cc3)}</strong>
            <button
              type="button"
              className="icon-button"
              aria-label={t(
                ...uiMessages.accounts_close_account_settings_e031b9,
              )}
              onClick={() => setEditing(false)}
            >
              <Icon name="close" />
            </button>
          </div>
          <div className="form-grid">
            <label>
              {t(...uiMessages.accounts_name_66f61d)}
              <input
                required
                maxLength={100}
                value={label}
                onChange={(event) => setLabel(event.target.value)}
              />
            </label>
            <label>
              {t(...uiMessages.accounts_selection_priority_e32641)}
              <input
                type="number"
                min="-100"
                max="100"
                value={priority}
                onChange={(event) => setPriority(Number(event.target.value))}
              />
            </label>
          </div>
          <div className="button-row">
            <button className="primary" disabled={busy || !label.trim()}>
              {t(...uiMessages.accounts_save_80b89d)}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => void mutate(path, { enabled: disabled })}
            >
              {disabled
                ? t(...uiMessages.accounts_enable_account_d8461d)
                : t(...uiMessages.accounts_disable_account_610ed6)}
            </button>
          </div>
        </form>
      )}
    </article>
  );
}

export default function Accounts({
  state,
  token,
  busy,
  mutate,
  onChanged,
  t,
}: {
  state: DockState;
  token: string;
  busy: boolean;
  mutate: Mutate;
  onChanged: () => void;
  t: Translate;
}) {
  const [creating, setCreating] = useState(false);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const [environment, setEnvironment] = useState("local");
  const [provider, setProvider] = useState<"codex" | "claude">("codex");
  const [label, setLabel] = useState("");
  const [filter, setFilter] = useState("");
  const [providerFilter, setProviderFilter] = useState("");
  const environments = [
    { id: "local", name: t(...uiMessages.accounts_this_mac_e21573) },
    ...(state.environments ?? []).filter((env) => env.id !== "local"),
  ];
  const accounts = (state.accounts ?? []).filter(
    (account) =>
      account.status !== "removed" &&
      (!filter || account.environment_id === filter) &&
      (!providerFilter || account.provider === providerFilter),
  );
  return (
    <div className="accounts-page">
      <div className="page-heading">
        <div>
          <h1>{t(...uiMessages.accounts_accounts_cdc79f)}</h1>
          <p>
            {t(
              ...uiMessages.accounts_manage_codex_and_claude_code_subscriptions_th_7e4379,
            )}
          </p>
        </div>
        <button
          className="primary"
          disabled={busy}
          aria-expanded={creating}
          onClick={() => setCreating(!creating)}
        >
          <Icon name="plus" />
          {t(...uiMessages.accounts_add_account_8fe0cf)}
        </button>
      </div>
      {creating && (
        <section className="panel inset-form">
          <div className="panel-heading">
            <h2>{t(...uiMessages.accounts_add_subscription_account_4f2283)}</h2>
            <button
              className="icon-button"
              aria-label={t(
                ...uiMessages.accounts_cancel_adding_account_23dfad,
              )}
              onClick={() => setCreating(false)}
            >
              <Icon name="close" />
            </button>
          </div>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              if (
                await mutate("/api/accounts", {
                  label: label.trim(),
                  provider,
                  environment_id: environment,
                  priority: 0,
                })
              ) {
                setCreating(false);
                setLabel("");
              }
            }}
          >
            <label>
              {t(...uiMessages.accounts_account_name_0ebf59)}
              <input
                required
                value={label}
                maxLength={100}
                onChange={(event) => setLabel(event.target.value)}
                placeholder={t(
                  ...uiMessages.accounts_for_example_personal_work_9f07fb,
                )}
              />
            </label>
            <div className="form-grid">
              <label>
                {t(...uiMessages.accounts_service_fe2e55)}
                <select
                  value={provider}
                  onChange={(event) =>
                    setProvider(event.target.value as "codex" | "claude")
                  }
                >
                  <option value="codex">Codex</option>
                  <option value="claude">Claude Code</option>
                </select>
              </label>
              <label>
                {t(...uiMessages.accounts_device_744986)}
                <select
                  value={environment}
                  onChange={(event) => setEnvironment(event.target.value)}
                >
                  {environments.map((env) => (
                    <option key={env.id} value={env.id}>
                      {env.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <button className="primary" disabled={busy || !label.trim()}>
              {t(...uiMessages.accounts_add_aaf69f)}
            </button>
          </form>
        </section>
      )}
      <div className="account-filters">
        <label>
          {t(...uiMessages.accounts_device_744986)}
          <select
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          >
            <option value="">
              {t(...uiMessages.accounts_all_devices_9362af)}
            </option>
            {environments.map((env) => (
              <option key={env.id} value={env.id}>
                {env.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t(...uiMessages.accounts_service_fe2e55)}
          <select
            value={providerFilter}
            onChange={(event) => setProviderFilter(event.target.value)}
          >
            <option value="">
              {t(...uiMessages.accounts_all_services_336e49)}
            </option>
            <option value="codex">Codex</option>
            <option value="claude">Claude Code</option>
          </select>
        </label>
      </div>
      <div className="accounts-grid">
        {accounts.map((account) => (
          <AccountCard
            key={account.id}
            account={account}
            now={now}
            state={state}
            token={token}
            busy={busy}
            mutate={mutate}
            onChanged={onChanged}
            t={t}
          />
        ))}
      </div>
      {!accounts.length && (
        <Empty
          icon="shield"
          title={t(...uiMessages.accounts_no_subscription_accounts_c1fe69)}
        >
          {t(
            ...uiMessages.accounts_add_an_account_and_sign_in_to_use_it_in_your_03c988,
          )}
        </Empty>
      )}
      <ExperimentalFeatures
        features={state.runtime.features ?? {}}
        mutate={mutate}
        busy={!!busy}
        t={t}
      />
    </div>
  );
}
