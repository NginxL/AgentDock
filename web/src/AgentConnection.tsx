import { useRef, useState, type ReactNode } from "react";
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
  children,
}: {
  children?: ReactNode;
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
  const [connecting, setConnecting] = useState(false);
  const inFlight = useRef(false);
  const selected = environments.find((e) => e.id === value);
  const newConnection = value === NEW_SSH_CONNECTION;
  const remote = value !== "local";
  const host = newConnection ? draft.host : (selected?.ssh_host ?? draft.host);
  const python = newConnection ? draft.python : (selected?.python ?? "python3");
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
      <div className="form-grid device-directory-row">
        <div className="device-field">
          <label>
            {t("设备", "Device")}
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
              {!locked && (
                <option value={NEW_SSH_CONNECTION}>
                  {t("新建 SSH / Devbox 连接…", "New SSH / Devbox connection…")}
                </option>
              )}
              {!!environments.some((e) => e.kind === "ssh") && (
                <optgroup label={t("已保存的连接", "Saved connections")}>
                  {environments
                    .filter((e) => e.kind === "ssh")
                    .map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.name}
                      </option>
                    ))}
                </optgroup>
              )}
            </select>
          </label>
          {remote && !newConnection && selected && (
            <span
              className={`pill device-status ${selected.status === "connected" ? "good" : ""}`}
            >
              {connecting
                ? t("连接中", "Connecting")
                : (labels[selected.status] ?? selected.status)}
            </span>
          )}
        </div>
        {children}
      </div>
      {remote && (
        <div className="connection-setup">
          <div className="ssh-address-row">
            <label>
              {t("SSH 地址或 Host 别名", "SSH destination or Host alias")}
              <input
                value={host}
                onChange={(e) => {
                  onDraftChange({
                    host: e.target.value,
                    python,
                    previous: newConnection ? draft.previous : value,
                  });
                  if (!newConnection) onChange(NEW_SSH_CONNECTION);
                }}
                disabled={disabled || locked}
                maxLength={255}
                placeholder="user@hostname / ssh-host-alias"
                autoComplete="off"
                spellCheck={false}
              />
            </label>
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
                : newConnection
                  ? t("连接并使用", "Connect and use")
                  : t("连接 / 检查", "Connect / check")}
            </button>
            {newConnection && (
              <button
                type="button"
                className="icon-button"
                disabled={disabled}
                aria-label={t("关闭 SSH 连接配置", "Close SSH setup")}
                onClick={() => onChange(draft.previous)}
              >
                <Icon name="close" />
              </button>
            )}
          </div>
          <details className="connection-advanced">
            <summary>
              {t("高级连接设置", "Advanced connection settings")}
            </summary>
            <label>
              {t("远端 Python", "Remote Python")}
              <input
                value={python}
                onChange={(e) => {
                  onDraftChange({
                    host,
                    python: e.target.value,
                    previous: newConnection ? draft.previous : value,
                  });
                  if (!newConnection) onChange(NEW_SSH_CONNECTION);
                }}
                disabled={disabled || locked}
                placeholder="python3"
              />
            </label>
            <p className="form-hint">
              {t(
                "沿用你的 SSH 配置与远端 CLI 登录。",
                "Uses your SSH configuration and remote CLI login.",
              )}
            </p>
          </details>
        </div>
      )}
    </div>
  );
}
