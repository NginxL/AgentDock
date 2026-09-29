import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import Workspace from "./views/Workspace";
import Conversations from "./views/Conversations";
import type { DockState, Language, Mutate } from "./types";

afterEach(cleanup);
const agent = {
  id: "agent",
  name: "My agent",
  provider: "codex" as const,
  project_id: null,
  role: "",
};
function fixture(): DockState {
  return {
    runtime: { enabled: true, version: "0.3.0" },
    projects: [],
    agents: [agent],
    sessions: ["First", "Second"].map((title) => ({
      id: title.toLowerCase(),
      agent_id: agent.id,
      project_id: null,
      title,
      status: "completed",
      created_at: "",
      updated_at: "",
    })),
    runs: [],
    events: [],
    approvals: [],
    memories: [],
    messages: [],
    proposals: [],
    quotas: [],
    subscriptions: [],
  };
}
function setup(
  surface: "agent" | "hub",
  lang: Language = "zh",
  initial = fixture(),
) {
  const gate = vi.fn(async () => true);
  const writes = vi.fn();
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
  function Harness() {
    const [state, setState] = useState(initial);
    const [selected, setSelected] = useState("first");
    const mutate: Mutate = async (path, data, success) => {
      writes(path, data);
      if (!(await gate())) return false;
      const id = path.split("/")[3];
      setState((old) => ({
        ...old,
        sessions: old.sessions.filter((s) => s.id !== id),
      }));
      success?.({ ok: true });
      return true;
    };
    const props = {
      state,
      token: "fixture",
      demo: true,
      busy: false,
      mutate,
      lang,
      t,
    };
    return surface === "hub" ? (
      <Conversations
        {...props}
        sessionID={selected}
        onSelect={setSelected}
        onAgent={vi.fn()}
      />
    ) : (
      <Workspace
        {...props}
        agents={state.agents}
        sessions={state.sessions}
        approvals={state.approvals}
        runtimeEnabled
        agentPageID={agent.id}
      />
    );
  }
  render(<Harness />);
  const remove = (title: string) =>
    screen.getByRole("button", {
      name: t(`删除会话「${title}」`, `Delete session “${title}”`),
    });
  const confirm = () =>
    screen.getByRole("button", { name: t("确认删除", "Delete permanently") });
  const draft = () =>
    screen.getByLabelText(
      t("给 Agent 的任务", "Task for this agent"),
    ) as HTMLTextAreaElement;
  return { gate, writes, t, remove, confirm, draft };
}

for (const surface of ["agent", "hub"] as const) {
  it.each<Language>(["zh", "en"])(
    `deletes the hovered row without selecting it or losing the current draft (${surface}, %s)`,
    async (lang) => {
      const { writes, t, remove, confirm, draft } = setup(surface, lang);
      fireEvent.change(draft(), {
        target: { value: "Keep my unfinished question" },
      });
      const button = remove("Second");
      expect(button.closest(".session-list-row")?.textContent).toContain(
        "Second",
      );
      fireEvent.click(button);
      expect(
        screen.getByRole("alertdialog").getAttribute("aria-label"),
      ).toContain("Second");
      expect(writes).not.toHaveBeenCalled();
      expect(
        screen
          .getByRole("button", { name: /^First/ })
          .getAttribute("aria-current"),
      ).toBe("true");
      fireEvent.click(button);
      expect(screen.queryByRole("alertdialog")).toBeNull();
      fireEvent.click(button);
      fireEvent.click(screen.getByRole("button", { name: t("关闭", "Close") }));
      expect(screen.queryByRole("alertdialog")).toBeNull();
      expect(document.activeElement).toBe(button);
      fireEvent.click(button);
      fireEvent.keyDown(document, { key: "Escape" });
      expect(screen.queryByRole("alertdialog")).toBeNull();
      fireEvent.click(button);
      fireEvent.click(confirm());
      await waitFor(() =>
        expect(screen.queryByRole("button", { name: /^Second/ })).toBeNull(),
      );
      expect(writes).toHaveBeenCalledExactlyOnceWith(
        "/api/sessions/second/delete",
        {},
      );
      expect(draft().value).toBe("Keep my unfinished question");
      expect(
        screen
          .getByRole("button", { name: /^First/ })
          .getAttribute("aria-current"),
      ).toBe("true");
    },
  );

  it(`keeps a failed deletion available for retry and prevents duplicate submission (${surface})`, async () => {
    const { gate, writes, remove, confirm } = setup(surface);
    gate.mockResolvedValueOnce(false);
    fireEvent.click(remove("Second"));
    fireEvent.click(confirm());
    await waitFor(() =>
      expect((confirm() as HTMLButtonElement).disabled).toBe(false),
    );
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(remove("Second")).toBeTruthy();
    let finish!: (value: boolean) => void;
    gate.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    fireEvent.click(confirm());
    fireEvent.click(screen.getByRole("button", { name: "删除中…" }));
    expect(writes).toHaveBeenCalledTimes(2);
    await act(async () => finish(true));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Second/ })).toBeNull();
  });

  it(`retains a newly selected conversation when another deletion completes (${surface})`, async () => {
    const { gate, remove, confirm, draft } = setup(surface);
    let finish!: (value: boolean) => void;
    gate.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    fireEvent.click(remove("First"));
    fireEvent.click(confirm());
    fireEvent.click(screen.getByRole("button", { name: /^Second/ }));
    fireEvent.change(draft(), { target: { value: "Second draft" } });
    await act(async () => finish(true));
    expect(
      screen
        .getByRole("button", { name: /^Second/ })
        .getAttribute("aria-current"),
    ).toBe("true");
    expect(draft().value).toBe("Second draft");
    expect(screen.queryByRole("button", { name: /^First/ })).toBeNull();
  });

  it(`clears the detail after deleting the last conversation (${surface})`, async () => {
    const initial = fixture();
    initial.sessions = initial.sessions.slice(0, 1);
    const { remove, confirm } = setup(surface, "zh", initial);
    fireEvent.click(remove("First"));
    fireEvent.click(confirm());
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /^First/ })).toBeNull(),
    );
    expect(screen.queryByLabelText("给 Agent 的任务")).toBeNull();
  });

  it.each(["running", "queued", "waiting", "delivery"])(
    `blocks unfinished work on its own row (${surface}, %s)`,
    (status) => {
      const initial = fixture();
      if (status === "delivery")
        initial.messages = [
          {
            id: "message",
            project_id: "project",
            sender_id: "other",
            recipient_id: "agent",
            body: "",
            created_at: "",
            status: "queued",
            recipient_session_id: "second",
          },
        ];
      else initial.sessions[1].status = status;
      const { remove, writes } = setup(surface, "zh", initial);
      expect((remove("Second") as HTMLButtonElement).disabled).toBe(true);
      expect((remove("First") as HTMLButtonElement).disabled).toBe(false);
      fireEvent.click(remove("Second"));
      expect(writes).not.toHaveBeenCalled();
      expect(screen.queryByRole("alertdialog")).toBeNull();
    },
  );
}
