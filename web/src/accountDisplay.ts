import type { Translate } from "./types";

export function accountError(code: string | null | undefined, t: Translate) {
  if (!code) return "";
  const labels: Record<string, [string, string]> = {
    login_required: ["请重新登录此账号。", "Sign in to this account again."],
    auth_expired: [
      "登录已失效，请重新登录。",
      "Sign-in expired. Sign in again.",
    ],
    rate_limited: [
      "请求已达限额，请等待额度恢复或选择其他账号。",
      "The request limit was reached. Wait for it to reset or choose another account.",
    ],
    quota_exhausted: [
      "当前额度已用完，请等待恢复或选择其他账号。",
      "Quota is exhausted. Wait for it to reset or choose another account.",
    ],
    account_unavailable: [
      "此账号暂不可用，请检查登录或选择其他账号。",
      "This account is unavailable. Check its sign-in or choose another account.",
    ],
    login_start_failed: [
      "无法启动登录，请检查所选设备的连接和 CLI 安装。",
      "Could not start sign-in. Check the device connection and CLI installation.",
    ],
    login_worker_stopped: [
      "登录进程已结束，请重新发起登录。",
      "The sign-in process stopped. Start sign-in again.",
    ],
    login_timeout: [
      "登录等待已超时，请重新发起登录。",
      "Sign-in timed out. Start sign-in again.",
    ],
    login_not_confirmed: [
      "未确认登录成功，请完成浏览器授权后重试。",
      "Sign-in was not confirmed. Complete browser authorization and retry.",
    ],
    native_login_failed: [
      "CLI 登录未成功，请重新登录。",
      "CLI sign-in failed. Sign in again.",
    ],
    quota_unavailable: [
      "当前无法读取订阅额度。",
      "Subscription quota is currently unavailable.",
    ],
  };
  const label = labels[code];
  return label
    ? t(label[0], label[1])
    : t(
        "账号操作暂未成功，请检查设备连接和登录状态后重试。",
        "The account action did not complete. Check the device connection and sign-in, then retry.",
      );
}

export function resetCountdown(value: string, now: number, t: Translate) {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp))
    return t("恢复时间未知", "Reset time unknown");
  const minutes = Math.ceil((timestamp - now) / 60_000);
  if (minutes <= 0)
    return t(
      "已到恢复时间，可刷新确认",
      "Reset time reached; refresh to check",
    );
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const rest = minutes % 60;
  const duration = [
    days ? t(`${days} 天`, `${days}d`) : "",
    hours ? t(`${hours} 小时`, `${hours}h`) : "",
    rest ? t(`${rest} 分钟`, `${rest}m`) : "",
  ]
    .filter(Boolean)
    .join(" ");
  return t(`${duration}后恢复`, `Resets in ${duration}`);
}
