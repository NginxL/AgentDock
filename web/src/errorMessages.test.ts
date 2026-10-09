import { afterEach, expect, it, vi } from "vitest";
import { ApiError, request } from "./api";
import { errorMessage } from "./ui";

afterEach(() => vi.unstubAllGlobals());
it.each([
  [
    "native_credentials_desktop_required",
    "请打开 AgentDock 桌面版，以访问受保护的原生账号凭据。",
  ],
  ["account_login_active", "请先取消正在进行的登录，再删除账号。"],
  [
    "keychain_unavailable",
    "无法访问 macOS 登录钥匙串，请检查 AgentDock 桌面版的授权。",
  ],
  ["network_unavailable", "连接失败，请检查原生 CLI 的网络和代理配置。"],
  [
    "native_credentials_busy",
    "此设备的 Agent 正在使用登录信息，请稍后刷新模型列表。",
  ],
])(
  "translates account error code %s independently of server wording",
  async (code, expected) => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({
          ok: false,
          status: 400,
          json: async () => ({ code, error: "Changed English wording" }),
        }),
    );
    const error = await request("fixture", "/api/accounts/id/native").catch(
      (error: ApiError) => error,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(errorMessage((error as Error).message, (zh) => zh)).toBe(expected);
  },
);

it("translates stable error codes even when the server changes its English wording", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({
        code: "execution_disabled",
        error: "Different explanatory wording",
      }),
    }),
  );
  try {
    await request("fixture", "/api/state");
    throw new Error("Expected rejection");
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("execution_disabled");
    expect(errorMessage((error as Error).message, (zh) => zh)).toBe(
      "当前仅可查看，请先启用任务执行。",
    );
  }
});
