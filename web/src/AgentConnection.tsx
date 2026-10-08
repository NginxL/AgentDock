import * as uiMessages from "./messages";
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
    connected: t(...uiMessages.agentconnection_connected_ca3dba),
    connecting: t(...uiMessages.agentconnection_connecting_da44c1),
    reconnecting: t(...uiMessages.agentconnection_reconnecting_161fd2),
    disconnected: t(...uiMessages.agentconnection_disconnected_c401a7),
    error: t(...uiMessages.agentconnection_connection_failed_e3b0ae),
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
            {t(...uiMessages.agentconnection_device_744986)}
            <select
              value={value}
              disabled={locked || disabled}
              onChange={(e) => {
                if (value !== NEW_SSH_CONNECTION)
                  onDraftChange({ ...draft, previous: value });
                onChange(e.target.value);
              }}
            >
              <option value="local">
                {t(...uiMessages.agentconnection_local_cli_75f187)}
              </option>
              {!locked && (
                <option value={NEW_SSH_CONNECTION}>
                  {t(
                    ...uiMessages.agentconnection_new_ssh_devbox_connection_ce8406,
                  )}
                </option>
              )}
              {!!environments.some((e) => e.kind === "ssh") && (
                <optgroup
                  label={t(
                    ...uiMessages.agentconnection_saved_connections_bceafc,
                  )}
                >
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
                ? t(...uiMessages.agentconnection_connecting_da44c1)
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
              {t(
                ...uiMessages.agentconnection_ssh_destination_or_host_alias_b424ad,
              )}
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
                ? t(...uiMessages.agentconnection_connecting_1dc33b)
                : newConnection
                  ? t(...uiMessages.agentconnection_connect_and_use_ccc76d)
                  : t(...uiMessages.agentconnection_connect_check_f711c5)}
            </button>
            {newConnection && (
              <button
                type="button"
                className="icon-button"
                disabled={disabled}
                aria-label={t(
                  ...uiMessages.agentconnection_close_ssh_setup_947af0,
                )}
                onClick={() => onChange(draft.previous)}
              >
                <Icon name="close" />
              </button>
            )}
          </div>
          <details className="connection-advanced">
            <summary>
              {t(
                ...uiMessages.agentconnection_advanced_connection_settings_113985,
              )}
            </summary>
            <label>
              {t(...uiMessages.agentconnection_remote_python_4e7a09)}
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
                ...uiMessages.agentconnection_uses_your_ssh_configuration_and_remote_cli_lo_922b6e,
              )}
            </p>
          </details>
        </div>
      )}
    </div>
  );
}
