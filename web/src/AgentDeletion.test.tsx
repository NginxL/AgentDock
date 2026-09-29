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
  "exposes deletion directly and confirms only the selected agent (%s)",
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
      agents: [agent, { ...agent, id: "agent-b", name: "Other agent" }],
      sessions: [session],
      approvals: [],
      token: "fixture",
      demo: true,
      runtimeEnabled: true,
      busy: false,
      mutate,
    };
    const view = render(<Workspace {...props} />);
    fireEvent.click(screen.getByRole("button", { name: /^My agent/ }));
    let remove = screen.getByRole("button", {
      name: t("删除 Agent", "Delete agent"),
    });
    expect(screen.queryByLabelText(t("名称", "Name"))).toBeNull();
    fireEvent.click(remove);
    expect(screen.getByRole("alertdialog").textContent).toContain("My agent");
    expect(screen.getByRole("alertdialog").textContent).toContain(
      t("1 个会话", "1 conversations"),
    );
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
    expect(document.activeElement).toBe(remove);
    fireEvent.click(remove);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    fireEvent.click(remove);
    fireEvent.click(
      screen.getByRole("button", {
        name: t("返回 Agent 列表", "Back to agents"),
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Other agent/ }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    remove = screen.getByRole("button", {
      name: t("删除 Agent", "Delete agent"),
    });
    fireEvent.click(remove);
    expect(screen.getByRole("alertdialog").textContent).toContain(
      "Other agent",
    );
    expect(screen.getByRole("alertdialog").textContent).toContain(
      t("0 个会话", "0 conversations"),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: t("返回 Agent 列表", "Back to agents"),
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /^My agent/ }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    remove = screen.getByRole("button", {
      name: t("删除 Agent", "Delete agent"),
    });
    expect(mutate).not.toHaveBeenCalled();
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
    mutate.mockResolvedValueOnce(false);
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: t("确认删除", "Delete permanently"),
      }),
    );
    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("alertdialog")).toBeTruthy();
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
    view.rerender(<Workspace {...props} agents={[]} sessions={[]} />);
    expect(
      screen.queryByRole("button", {
        name: t("删除 Agent", "Delete agent"),
      }),
    ).toBeNull();
  },
);
