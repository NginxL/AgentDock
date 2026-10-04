import { useEffect, useState } from "react";
import type { Account, DockState, Mutate, Translate } from "../types";
import { request, remainingPercent } from "../api";
import { accountStatus } from "../AccountSelection";
import ProviderIcon from "../ProviderIcon";
import { Empty, Icon } from "../ui";
import { accountError, resetCountdown } from "../accountDisplay";
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
        <strong>{t("账号授权", "Authorize account")}</strong>
        <button
          type="button"
          className="icon-button"
          aria-label={t("关闭登录面板", "Close sign-in panel")}
          onClick={close}
        >
          <Icon name="close" />
        </button>
      </div>
      {failed ? (
        <p className="inline-error" role="status">
          {t(
            "暂时无法读取登录状态，正在重试。",
            "Cannot read sign-in status. Retrying.",
          )}
        </p>
      ) : (
        <p role="status">
          {job?.status === "completed"
            ? t("登录成功，账号已可使用。", "Signed in. This account is ready.")
            : job?.status === "failed"
              ? accountError(job.error_code ?? "native_login_failed", t)
              : job?.status === "cancelled"
                ? t("已取消登录。", "Sign-in cancelled.")
                : t(
                    "请在浏览器中完成账号授权。",
                    "Complete authorization in your browser.",
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
              {t("打开登录页面", "Open sign-in page")} ↗
            </a>
          )}
          {(job.code || job.device_code) && (
            <p>
              {t("验证码", "Verification code")}：
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
                  "授权码（仅登录页面提供时填写）",
                  "Authorization code (only if provided by the sign-in page)",
                )}
                <input
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  autoComplete="off"
                />
              </label>
              <button className="secondary" disabled={busy || !code.trim()}>
                {t("提交验证码", "Submit code")}
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
            {t("取消登录", "Cancel sign-in")}
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
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(account.label);
  const [priority, setPriority] = useState(account.priority ?? 0);
  const [login, setLogin] = useState(false);
  const [loginVersion, setLoginVersion] = useState(0);
  const [loginStarted, setLoginStarted] = useState(false);
  const [deleting, setDeleting] = useState(false);
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
              ? t("本机", "This Mac")
              : (env?.name ?? t("远端设备", "Remote device"))}
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
      {account.usage && (
        <div
          className="account-usage"
          aria-label={t("AgentDock 用量", "AgentDock usage")}
        >
          <strong>{t("AgentDock 用量", "AgentDock usage")}</strong>
          <dl>
            <div>
              <dt>{t("总 Token", "Total tokens")}</dt>
              <dd>{exactTokens(account.usage.total_tokens)}</dd>
            </div>
            <div>
              <dt>{t("输入", "Input")}</dt>
              <dd>{exactTokens(account.usage.input_tokens)}</dd>
            </div>
            <div>
              <dt>{t("输出", "Output")}</dt>
              <dd>{exactTokens(account.usage.output_tokens)}</dd>
            </div>
          </dl>
        </div>
      )}
      <div className="account-quota">
        {account.quota?.windows?.length ? (
          account.quota.windows.map((window, index) => {
            const remaining = remainingPercent(window.remaining_percent);
            const name =
              window.label ??
              {
                primary: t("当前周期", "Current window"),
                secondary: t("额外周期", "Additional window"),
                session: t("会话额度", "Session limit"),
                weekly: t("每周额度", "Weekly limit"),
              }[window.name ?? ""] ??
              window.name ??
              t("额度", "Quota");
            return (
              <div key={`${name}-${index}`}>
                <span>{name}</span>
                <strong>
                  {remaining === null
                    ? t("未知", "Unknown")
                    : `${Math.round(remaining)}% ${t("剩余", "remaining")}`}
                </strong>
                {remaining !== null && (
                  <meter
                    min="0"
                    max="100"
                    value={remaining}
                    aria-label={`${name} ${t("剩余额度", "remaining quota")}`}
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
            {t("额度暂未读取", "Quota not available yet")}
          </p>
        )}
        {account.quota?.fetched_at && (
          <small className="muted">
            {t("更新于", "Updated")}{" "}
            {new Date(account.quota.fetched_at).toLocaleString()}
            {account.quota.status !== "ok" &&
            account.quota.status !== "ready" &&
            account.quota.status !== "available"
              ? ` · ${t("上次数据", "Last known data")}`
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
            ? t("设备码登录", "Sign in with device code")
            : account.status === "pending" || account.status === "expired"
              ? t("登录账号", "Sign in")
              : t("重新登录", "Sign in again")}
        </button>
        {account.provider === "codex" && !remoteCodex && !login && (
          <button
            type="button"
            className="text-button"
            disabled={busy || active}
            onClick={() => void startLogin("device")}
          >
            {t("使用设备码", "Use device code")}
          </button>
        )}
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={() => void mutate(`${path}/check`, {})}
        >
          {t("检查登录", "Check sign-in")}
        </button>
        <button
          type="button"
          className="text-button"
          disabled={busy || disabled}
          onClick={() => void mutate(`${path}/refresh`, {})}
        >
          {t("刷新额度", "Refresh quota")}
        </button>
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
          {t("设置", "Settings")}
        </button>
      </div>
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
            <strong>{t("账号设置", "Account settings")}</strong>
            <button
              type="button"
              className="icon-button"
              aria-label={t("关闭账号设置", "Close account settings")}
              onClick={() => setEditing(false)}
            >
              <Icon name="close" />
            </button>
          </div>
          <div className="form-grid">
            <label>
              {t("名称", "Name")}
              <input
                required
                maxLength={100}
                value={label}
                onChange={(event) => setLabel(event.target.value)}
              />
            </label>
            <label>
              {t("选择优先级", "Selection priority")}
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
              {t("保存", "Save")}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => void mutate(path, { enabled: disabled })}
            >
              {disabled
                ? t("启用账号", "Enable account")
                : t("停用账号", "Disable account")}
            </button>
            <button
              type="button"
              className="text-button danger"
              disabled={busy || active}
              aria-expanded={deleting}
              onClick={() => setDeleting(!deleting)}
            >
              {t("删除账号", "Delete account")}
            </button>
          </div>
          {deleting && (
            <div className="account-delete">
              <p>
                {t(
                  "删除此账号保存的登录凭据。已有会话和回复保留；使用此账号的会话需要重新选择账号。",
                  "Delete this saved sign-in. Existing conversations and replies remain; conversations using it will need another account.",
                )}
              </p>
              <div className="button-row">
                <button
                  type="button"
                  className="secondary danger"
                  disabled={busy || active}
                  onClick={() => void mutate(`${path}/delete`, {})}
                >
                  {t("确认删除账号", "Confirm account deletion")}
                </button>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setDeleting(false)}
                >
                  {t("取消", "Cancel")}
                </button>
              </div>
            </div>
          )}
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
    { id: "local", name: t("本机", "This Mac") },
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
          <h1>{t("账号", "Accounts")}</h1>
          <p>
            {t(
              "管理 Codex 和 Claude Code 订阅，在 Agent 或会话中选择使用。",
              "Manage Codex and Claude Code subscriptions, then choose one for an agent or conversation.",
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
          {t("添加账号", "Add account")}
        </button>
      </div>
      {creating && (
        <section className="panel inset-form">
          <div className="panel-heading">
            <h2>{t("添加订阅账号", "Add subscription account")}</h2>
            <button
              className="icon-button"
              aria-label={t("取消添加账号", "Cancel adding account")}
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
              {t("账号名称", "Account name")}
              <input
                required
                value={label}
                maxLength={100}
                onChange={(event) => setLabel(event.target.value)}
                placeholder={t(
                  "例如：个人、工作",
                  "For example: Personal, Work",
                )}
              />
            </label>
            <div className="form-grid">
              <label>
                {t("服务", "Service")}
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
                {t("设备", "Device")}
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
              {t("添加", "Add")}
            </button>
          </form>
        </section>
      )}
      <div className="account-filters">
        <label>
          {t("设备", "Device")}
          <select
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          >
            <option value="">{t("全部设备", "All devices")}</option>
            {environments.map((env) => (
              <option key={env.id} value={env.id}>
                {env.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("服务", "Service")}
          <select
            value={providerFilter}
            onChange={(event) => setProviderFilter(event.target.value)}
          >
            <option value="">{t("全部服务", "All services")}</option>
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
          title={t("暂无订阅账号", "No subscription accounts")}
        >
          {t(
            "添加账号后登录，即可在不同会话中分别使用。",
            "Add an account and sign in to use it in your conversations.",
          )}
        </Empty>
      )}
    </div>
  );
}
