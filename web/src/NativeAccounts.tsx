import * as uiMessages from "./messages";
import { useEffect, useState } from "react";
import { request } from "./api";
import type { Account, Translate } from "./types";
import { Icon } from "./ui";

type Client = "codex" | "claude_code" | "claude_desktop";
type Status = {
  available: boolean;
  recovery_needed: boolean;
  recovery_client?: Client;
  clients: {
    id: Client;
    saved: boolean;
    saved_at?: string;
    identity?: { email: string };
  }[];
};
const labels = {
  codex: "Codex CLI / macOS",
  claude_code: "Claude Code CLI",
  claude_desktop: "Claude macOS",
};

export default function NativeAccounts({
  account,
  token,
  close,
  t,
}: {
  account: Account;
  token: string;
  close: () => void;
  t: Translate;
}) {
  const [status, setStatus] = useState<Status>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const path = `/api/accounts/${encodeURIComponent(account.id)}/native`;
  useEffect(() => {
    const controller = new AbortController();
    void request<Status>(token, path, undefined, controller.signal)
      .then(setStatus)
      .catch(() => {
        if (!controller.signal.aborted)
          setError(
            t(
              ...uiMessages.nativeaccounts_could_not_read_native_clients_try_again_70a4b4,
            ),
          );
      });
    return () => controller.abort();
  }, [path, token]);
  async function act(
    client: Client,
    operation: "capture" | "switch" | "recover",
  ) {
    if (busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setStatus(await request<Status>(token, path, { client, operation }));
      setMessage(
        operation === "capture"
          ? t(
              ...uiMessages.nativeaccounts_native_sign_in_saved_you_can_now_switch_back_21d494,
            )
          : t(
              ...uiMessages.nativeaccounts_saved_sign_in_restored_confirm_the_account_in_829577,
            ),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t(
              ...uiMessages.nativeaccounts_the_operation_did_not_complete_2e40a2,
            ),
      );
      try {
        setStatus(await request<Status>(token, path));
      } catch {
        /* Keep the original error. */
      }
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className="account-native"
      aria-label={t(...uiMessages.nativeaccounts_native_client_accounts_01b0df)}
    >
      <div className="panel-heading">
        <strong>
          {t(...uiMessages.nativeaccounts_native_client_accounts_01b0df)}
        </strong>
        <button
          type="button"
          className="icon-button"
          onClick={close}
          disabled={busy}
          aria-label={t(
            ...uiMessages.nativeaccounts_close_native_account_panel_ac68c7,
          )}
        >
          <Icon name="close" />
        </button>
      </div>
      <p>
        {t(
          ...uiMessages.nativeaccounts_first_sign_in_to_this_account_in_each_client_a54862,
        )}
      </p>
      <p>
        {t(
          ...uiMessages.nativeaccounts_saving_and_switching_quit_and_reopen_the_rela_955ed5,
        )}
      </p>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {!status && !error && (
        <p role="status">{t(...uiMessages.nativeaccounts_loading_e20f83)}</p>
      )}
      {status && !status.available && (
        <p>
          {t(
            ...uiMessages.nativeaccounts_this_feature_requires_local_macos_clients_565e91,
          )}
        </p>
      )}
      {status?.available &&
        status.clients.map((client) => (
          <div className="native-client" key={client.id}>
            <div>
              <strong>{labels[client.id]}</strong>
              <small>
                {client.saved
                  ? `${t(...uiMessages.nativeaccounts_saved_82b5db)} · ${client.identity?.email ?? ""}`
                  : t(
                      ...uiMessages.nativeaccounts_no_native_sign_in_saved_yet_41e511,
                    )}
              </small>
            </div>
            <div className="button-row">
              <button
                type="button"
                className="secondary"
                disabled={busy || !client.saved || status.recovery_needed}
                onClick={() => void act(client.id, "switch")}
              >
                {t(...uiMessages.nativeaccounts_switch_to_this_account_a90bd1)}
              </button>
              <button
                type="button"
                className="text-button"
                disabled={busy || status.recovery_needed}
                onClick={() => void act(client.id, "capture")}
              >
                {t(...uiMessages.nativeaccounts_save_current_sign_in_de562c)}
              </button>
              {status.recovery_client === client.id && (
                <button
                  type="button"
                  className="text-button"
                  disabled={busy}
                  onClick={() => void act(client.id, "recover")}
                >
                  {t(
                    ...uiMessages.nativeaccounts_recover_previous_sign_in_ce66d6,
                  )}
                </button>
              )}
            </div>
          </div>
        ))}
      {busy && (
        <p role="status">
          {t(...uiMessages.nativeaccounts_working_please_wait_bf7eef)}
        </p>
      )}
    </section>
  );
}
