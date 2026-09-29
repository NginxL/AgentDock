import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import Workspace from "./views/Workspace";
import type { DockState, Language } from "./types";

afterEach(cleanup);
it.each<Language>(["zh", "en"])(
  "deletes only the configured agent after confirmation (%s)",
  async (lang) => {
    const agent = {
      id: "agent-a",
      name: "My agent",
      provider: "codex" as const,
      project_id: null,
      role: "",
    };
    const session = {
      id: "session-a",
      agent_id: agent.id,
      project_id: null,
      title: "S",
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
    const mutate = vi.fn(
      async (
        _path: string,
        _body: unknown,
        done?: (result: unknown) => void,
      ) => {
        done?.({ ok: true });
        return true;
      },
    );
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
    const settings = screen.getByRole("button", {
      name: t("设置 My agent", "Configure My agent"),
    });
    fireEvent.click(settings);
    const remove = screen.getByRole("button", {
      name: t("删除 Agent", "Delete agent"),
    });
    fireEvent.click(remove);
    expect(screen.getByRole("alertdialog").textContent).toContain("1");
    expect(mutate).not.toHaveBeenCalled();
    fireEvent.click(remove);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    fireEvent.click(remove);
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: t("关闭", "Close"),
      }),
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();
    fireEvent.click(remove);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    view.rerender(
      <Workspace {...props} sessions={[{ ...session, status: "running" }]} />,
    );
    expect(
      (
        screen.getByRole("button", {
          name: t("删除 Agent", "Delete agent"),
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    view.rerender(<Workspace {...props} />);
    fireEvent.click(remove);
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: t("确认删除", "Delete permanently"),
      }),
    );
    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith(
        "/api/agents/agent-a/delete",
        {},
        expect.any(Function),
      ),
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();
  },
);
