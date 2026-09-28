import { useRef, useState } from "react";
import type { Environment, Mutate, Translate } from "./types";
import { Icon } from "./ui";

export const NEW_SSH_CONNECTION = "new-ssh-connection";
export type SSHConnectionDraft = {
  host: string;
  python: string;
  previous: string;
};

/** Connection setup lives inside the agent form; it never submits the agent. */
export default function AgentConnection({
  value,
  onChange,
  draft,
  onDraftChange,
  environments,
  t,
  busy,
  runtimeEnabled,
  locked,
  mutate,
}: {
  value: string;
  onChange: (id: string) => void;
  draft: SSHConnectionDraft;
  onDraftChange: (draft: SSHConnectionDraft) => void;
  environments: Environment[];
  t: Translate;
  busy: boolean;
  runtimeEnabled: boolean;
  locked: boolean;
  mutate: Mutate;
}) {
  const { host, python } = draft;
  const [connecting, setConnecting] = useState(false);
  const inFlight = useRef(false);
  const selected = environments.find((e) => e.id === value);
  const newConnection = value === NEW_SSH_CONNECTION;
  const disabled = busy || connecting;
  const labels: Record<string, string> = {
    connected: t("已连接", "Connected"),
    connecting: t("连接中", "Connecting"),
    reconnecting: t("重连中", "Reconnecting"),
    disconnected: t("未连接", "Disconnected"),
    error: t("连接失败", "Connection failed"),
  };

  async function connect() {
    if (disabled || inFlight.current || !runtimeEnabled) return;
    inFlight.current = true;
    setConnecting(true);
    try {
      let id: string | undefined = newConnection ? undefined : value;
      if (newConnection) {
        // Reuse an existing connection on retry or when the same host is entered.
        id = environments.find(
          (e) =>
            e.kind === "ssh" &&
            e.ssh_host === host.trim() &&
            (e.python ?? "python3") === python.trim(),
        )?.id;
        if (!id) {
          await mutate(
            "/api/environments",
            {
              name: host.trim().slice(0, 100),
              ssh_host: host.trim(),
              python: python.trim(),
            },
            (result) => {
              id = result.id;
            },
          );
        }
        if (!id) return;
        onChange(id);
      }
      await mutate(`/api/environments/${encodeURIComponent(id!)}/connect`, {});
    } finally {
      inFlight.current = false;
      setConnecting(false);
    }
  }

  return (
    <div className="agent-connection">
      <label>
        {t("运行位置", "Run on")}
        <select
          value={value}
          disabled={locked || disabled}
          onChange={(e) => {
            if (value !== NEW_SSH_CONNECTION)
              onDraftChange({ ...draft, previous: value });
            onChange(e.target.value);
          }}
        >
          <option value="local">{t("本机 CLI", "Local CLI")}</option>
          {environments
            .filter((e) => e.kind === "ssh")
            .map((e) => (
              <option key={e.id} value={e.id}>
                {e.name} · SSH
              </option>
            ))}
          {!locked && (
            <option value={NEW_SSH_CONNECTION}>
              {t("新的 SSH 连接…", "New SSH connection…")}
            </option>
          )}
        </select>
      </label>
      {newConnection ? (
        <div className="connection-setup">
          <div className="panel-heading">
            <h3>{t("连接远端 CLI", "Connect remote CLI")}</h3>
            <button
              type="button"
              className="icon-button"
              disabled={disabled}
              aria-label={t("关闭 SSH 连接配置", "Close SSH setup")}
              onClick={() => onChange(draft.previous)}
            >
              <Icon name="close" />
            </button>
          </div>
          <label>
            {t("SSH 地址或 Host 别名", "SSH destination or Host alias")}
            <input
              value={host}
              onChange={(e) =>
                onDraftChange({ ...draft, host: e.target.value })
              }
              disabled={disabled}
              maxLength={255}
              placeholder="user@devbox / devbox"
              autoComplete="off"
            />
          </label>
          <details className="connection-advanced">
            <summary>
              {t("高级连接设置", "Advanced connection settings")}
            </summary>
            <label>
              {t("远端 Python", "Remote Python")}
              <input
                value={python}
                onChange={(e) =>
                  onDraftChange({ ...draft, python: e.target.value })
                }
                disabled={disabled}
                placeholder="python3"
              />
            </label>
          </details>
          <p className="form-hint">
            {t(
              "沿用 SSH 配置与远端 CLI 登录。连接时会在远端用户目录安装执行组件。",
              "Uses your SSH settings and remote CLI login. Connecting installs a runner in the remote user's home directory.",
            )}
          </p>
          <button
            type="button"
            className="secondary"
            disabled={
              disabled || !runtimeEnabled || !host.trim() || !python.trim()
            }
            onClick={() => void connect()}
          >
            {connecting
              ? t("连接中…", "Connecting…")
              : t("连接并使用", "Connect and use")}
          </button>
        </div>
      ) : selected?.kind === "ssh" ? (
        <div className="connection-status">
          <span
            className={`pill ${selected.status === "connected" ? "good" : ""}`}
          >
            {connecting
              ? t("连接中", "Connecting")
              : (labels[selected.status] ?? selected.status)}
          </span>
          <span className="path-line">{selected.ssh_host}</span>
          <button
            type="button"
            className="text-button"
            disabled={disabled || !runtimeEnabled}
            onClick={() => void connect()}
          >
            {t("连接 / 检查", "Connect / check")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
