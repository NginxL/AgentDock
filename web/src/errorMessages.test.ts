import { afterEach, expect, it, vi } from "vitest";
import { ApiError, request } from "./api";
import { errorMessage } from "./ui";

afterEach(() => vi.unstubAllGlobals());
it("translates stable error codes even when the server changes its English wording", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue({
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
