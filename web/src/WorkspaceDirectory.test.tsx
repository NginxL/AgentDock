import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import WorkspaceDirectory from "./WorkspaceDirectory";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it.each(["local", "remote"])(
  "reads only the selected %s device after opening and returns its actual path",
  async (environment) => {
    const fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        path: "/device/home",
        parent: "/device",
        directories: [{ name: "project", path: "/device/home/project" }],
        truncated: false,
      }),
    }));
    vi.stubGlobal("fetch", fetch);
    const onChange = vi.fn();
    render(
      <WorkspaceDirectory
        value=""
        environment={environment}
        token="fixture"
        disabled={false}
        browseEnabled
        t={(zh) => zh}
        onChange={onChange}
      />,
    );
    const button = screen.getByRole("button", {
      name: environment === "local" ? "选择本机目录" : "选择远端目录",
    });
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(button);
    await screen.findByRole("button", { name: "project" });
    expect(fetch).toHaveBeenCalledWith(
      `/api/directories?environment_id=${environment}&path=~`,
      expect.any(Object),
    );
    fireEvent.click(screen.getByRole("button", { name: "使用此目录" }));
    expect(onChange).toHaveBeenCalledWith("/device/home");
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(button);
    fireEvent.click(button);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: "关闭目录选择" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(button);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  },
);

it("blocks selection on a failed read and supports retrying the same path", async () => {
  const fetch = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue({
      ok: true,
      json: async () => ({
        path: "/remote",
        parent: "/",
        directories: [],
        truncated: false,
      }),
    });
  vi.stubGlobal("fetch", fetch);
  render(
    <WorkspaceDirectory
      value="/remote"
      environment="remote"
      token="fixture"
      disabled={false}
      browseEnabled
      t={(zh) => zh}
      onChange={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "选择远端目录" }));
  await screen.findByRole("alert");
  expect(
    (screen.getByRole("button", { name: "使用此目录" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "前往" }));
  await screen.findByText("此目录没有子目录");
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
});
