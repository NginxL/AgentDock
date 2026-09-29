import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import Workspace from "./views/Workspace";
import type { DockState, Language } from "./types";
afterEach(cleanup);
it.each<Language>(["zh", "en"])(
  "requires a deliberate delete and keeps controls reversible (%s)",
  async (lang) => {
    const agent = {
      id: "agent",
      name: "My agent",
      provider: "codex" as const,
      project_id: null,
      role: "",
      workspace: "/private/hidden-workspace",
    };
    const session = {
      id: "session-one",
      agent_id: "agent",
      project_id: null,
      title: "My session",
      status: "completed",
      created_at: "",
      updated_at: "",
    };
    const state: DockState = {
      runtime: { enabled: true, version: "0.3.0" },
      projects: [],
      agents: [agent],
      sessions: [session],
      runs: [],
      events: [],
      approvals: [],
      memories: [],
      messages: [],
      proposals: [],
      quotas: [],
      subscriptions: [],
    };
    const mutate = vi.fn(async () => true);
    const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
    const props = {
      t,
      lang,
      state,
      agents: [agent],
      sessions: [session],
      approvals: [],
      token: "fixture",
      demo: true,
      runtimeEnabled: true,
      busy: false,
      mutate,
    };
    const view = render(<Workspace {...props} />);
    expect(screen.queryByText(agent.workspace)).toBeNull();
    const button = await screen.findByRole("button", {
      name: t("删除会话", "Delete session"),
    });
    fireEvent.click(button);
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(mutate).not.toHaveBeenCalled();
    fireEvent.click(button);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: t("关闭", "Close") }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    fireEvent.click(button);
    fireEvent.click(
      screen.getByRole("button", { name: t("确认删除", "Delete permanently") }),
    );
    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith(
        "/api/sessions/session-one/delete",
        {},
        expect.any(Function),
      ),
    );
    view.rerender(
      <Workspace {...props} sessions={[{ ...session, status: "running" }]} />,
    );
    expect(
      (
        screen.getByRole("button", {
          name: t("删除会话", "Delete session"),
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  },
);
