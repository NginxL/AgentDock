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
              "无法读取本机客户端，请稍后重试。",
              "Could not read native clients. Try again.",
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
              "已保存此客户端的登录。以后可一键切回。",
              "Native sign-in saved. You can now switch back to it.",
            )
          : t(
              "已恢复保存的登录，请在客户端确认账号；新开的 CLI 会使用此登录。",
              "Saved sign-in restored. Confirm the account in the client; new CLI instances will use it.",
            ),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("操作未完成。", "The operation did not complete."),
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
      aria-label={t("本机客户端账号", "Native client accounts")}
    >
      <div className="panel-heading">
        <strong>{t("本机客户端账号", "Native client accounts")}</strong>
        <button
          type="button"
          className="icon-button"
          onClick={close}
          disabled={busy}
          aria-label={t("关闭本机账号面板", "Close native account panel")}
        >
          <Icon name="close" />
        </button>
      </div>
      <p>
        {t(
          "首次在对应客户端登录此账号后，点击「保存当前登录」。以后点击「切换到此账号」即可切回。",
          "First sign in to this account in each client, then save its current sign-in. Afterwards, switch back with one click.",
        )}
      </p>
      <p>
        {t(
          "保存和切换会退出并重开相关桌面应用，请先结束 CLI 和桌面任务。Codex CLI 与桌面版共用本机登录；Claude 两端分别保存。",
          "Saving and switching quit and reopen the related desktop app. Finish CLI and desktop tasks first. Codex CLI and desktop share a native login; Claude logins are saved separately.",
        )}
      </p>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {!status && !error && <p role="status">{t("正在读取…", "Loading…")}</p>}
      {status && !status.available && (
        <p>
          {t(
            "此功能适用于本机 macOS 客户端。",
            "This feature requires local macOS clients.",
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
                  ? `${t("已保存", "Saved")} · ${client.identity?.email ?? ""}`
                  : t("尚未保存此客户端的登录", "No native sign-in saved yet")}
              </small>
            </div>
            <div className="button-row">
              <button
                type="button"
                className="secondary"
                disabled={busy || !client.saved || status.recovery_needed}
                onClick={() => void act(client.id, "switch")}
              >
                {t("切换到此账号", "Switch to this account")}
              </button>
              <button
                type="button"
                className="text-button"
                disabled={busy || status.recovery_needed}
                onClick={() => void act(client.id, "capture")}
              >
                {t("保存当前登录", "Save current sign-in")}
              </button>
              {status.recovery_client === client.id && (
                <button
                  type="button"
                  className="text-button"
                  disabled={busy}
                  onClick={() => void act(client.id, "recover")}
                >
                  {t("恢复切换前登录", "Recover previous sign-in")}
                </button>
              )}
            </div>
          </div>
        ))}
      {busy && (
        <p role="status">
          {t("正在处理，请等待完成…", "Working. Please wait…")}
        </p>
      )}
    </section>
  );
}
