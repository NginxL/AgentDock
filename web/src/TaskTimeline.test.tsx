import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import TaskTimeline, { executionSteps, turnContent } from "./TaskTimeline";
import type { AgentEvent, Run } from "./types";
const run: Run = {
  id: "r",
  session_id: "s",
  agent_id: "a",
  project_id: null,
  prompt: "Check the current directory",
  status: "running",
  origin: "human",
  depth: 0,
  created_at: "2026-09-28T10:00:00Z",
  updated_at: "2026-09-28T10:00:00Z",
};
const event = (
  seq: number,
  kind: string,
  extra: Record<string, unknown>,
): AgentEvent => ({
  id: String(seq),
  seq,
  kind,
  session_id: "s",
  project_id: null,
  created_at: run.created_at,
  payload: { run_id: "r", ...extra },
});
const mutate = vi.fn(async () => true);
const props = {
  agentName: "My helper",
  t: (zh: string) => zh,
  lang: "zh" as const,
  busy: false,
  mutate,
};
afterEach(() => {
  cleanup();
  mutate.mockClear();
});
it("shows running work, live thinking and command output, then a separate final reply without duplicates", () => {
  const events = [
    event(1, "reasoning_chunk", {
      item_id: "thought",
      part: 0,
      text: "I will inspect ",
    }),
    event(2, "tool_call", {
      item: { type: "commandExecution", id: "cmd", command: "pwd" },
    }),
  ];
  const view = render(<TaskTimeline {...props} runs={[run]} events={events} />);
  const summary = screen.getByText("任务执行中");
  const disclosure = summary.closest("details")!;
  expect(disclosure.open).toBe(true);
  fireEvent.click(summary);
  expect(disclosure.open).toBe(false);
  events.push(
    event(3, "reasoning_chunk", {
      item_id: "thought",
      part: 0,
      text: "the workspace.",
    }),
    event(4, "tool_output", { item_id: "cmd", text: "/workspace\n" }),
  );
  view.rerender(<TaskTimeline {...props} runs={[run]} events={events} />);
  expect(disclosure.open).toBe(false);
  fireEvent.click(summary);
  expect(disclosure.open).toBe(true);
  expect(
    within(disclosure).getByText("I will inspect the workspace."),
  ).toBeTruthy();
  expect(within(disclosure).getByText("/workspace")).toBeTruthy();
  expect(screen.queryByText("任务已完成")).toBeNull();
  events.push(
    event(5, "tool_result", {
      item: {
        id: "cmd",
        type: "commandExecution",
        command: "pwd",
        status: "completed",
        aggregatedOutput: "/workspace\n",
        exitCode: 0,
      },
    }),
    event(6, "assistant_message", { text: "The directory is /workspace." }),
    event(7, "run_finished", { status: "completed" }),
  );
  view.rerender(
    <TaskTimeline
      {...props}
      runs={[
        { ...run, status: "completed", result: "The directory is /workspace." },
      ]}
      events={events}
    />,
  );
  expect(screen.getByText("任务已完成")).toBeTruthy();
  expect(disclosure.open).toBe(false);
  fireEvent.click(screen.getByText("任务已完成"));
  expect(disclosure.open).toBe(true);
  expect(screen.queryByText("任务执行中")).toBeNull();
  expect(screen.getAllByText("The directory is /workspace.")).toHaveLength(1);
  expect(
    screen.getByText("The directory is /workspace.").closest("details"),
  ).toBeNull();
  expect(within(disclosure).getAllByText("/workspace")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "取消" })).toBeNull();
  view.rerender(
    <TaskTimeline
      {...props}
      runs={[{ ...run, status: "completed", result: "Saved answer" }]}
      events={[]}
    />,
  );
  expect(screen.getByText("Saved answer")).toBeTruthy();
  expect(disclosure.open).toBe(true);
  fireEvent.click(screen.getByText("任务已完成"));
  expect(disclosure.open).toBe(false);
});
it("replaces streamed reasoning with its final summary and merges Claude tool-start/result identity", () => {
  const steps = executionSteps([
    event(1, "reasoning_chunk", { item_id: "thought", text: "partial" }),
    event(2, "reasoning_message", {
      item_id: "thought",
      text: "Final summary",
    }),
    event(3, "tool_call", {
      item: {
        id: "read",
        type: "tool_use",
        name: "Read",
        input: { file_path: "example.txt" },
      },
    }),
    event(4, "tool_result", {
      item: {
        tool_use_id: "read",
        type: "tool_result",
        content: [{ type: "text", text: "File contents" }],
        is_error: false,
      },
    }),
  ]);
  expect(steps).toHaveLength(2);
  expect(steps[0].text).toBe("Final summary");
  expect(steps[1]).toMatchObject({
    text: "File contents",
    name: "Read",
    status: "completed",
  });
});
it("keeps queued, failed, approval and cancellation states distinct", () => {
  const view = render(
    <TaskTimeline
      {...props}
      runs={[{ ...run, status: "queued" }]}
      events={[]}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(mutate).toHaveBeenCalledWith("/api/runs/r/cancel", {});
  view.rerender(
    <TaskTimeline
      {...props}
      runs={[run]}
      events={[event(1, "approval_required", { approval_id: "approval" })]}
    />,
  );
  expect(screen.getByText("等待授权")).toBeTruthy();
  view.rerender(
    <TaskTimeline
      {...props}
      runs={[run]}
      events={[
        event(2, "run_finished", { status: "failed", error: "CLI failed" }),
      ]}
    />,
  );
  expect(screen.getByText("任务失败")).toBeTruthy();
  expect(screen.getByText("CLI failed")).toBeTruthy();
  expect(screen.queryByText("任务已完成")).toBeNull();
});
it("isolates concurrent run progress and renders CLI output as text", () => {
  const evil = '<img src=x onerror="alert(1)">';
  const view = render(
    <TaskTimeline
      {...props}
      runs={[
        run,
        {
          ...run,
          id: "other",
          prompt: "Second task",
          status: "completed",
          result: "Second answer",
        },
      ]}
      events={[event(1, "reasoning_chunk", { item_id: "x", text: evil })]}
    />,
  );
  expect(view.container.querySelector("img")).toBeNull();
  expect(screen.getByText(evil).closest(".task-turn")?.textContent).toContain(
    "Check the current directory",
  );
  expect(
    screen.getByText("Second answer").closest(".task-turn")?.textContent,
  ).not.toContain(evil);
});

it("does not report a declined command as completed", () => {
  const steps = executionSteps([
    event(1, "tool_result", {
      item: {
        id: "cmd",
        type: "commandExecution",
        command: "pwd",
        status: "declined",
        exitCode: null,
      },
    }),
  ]);
  expect(steps[0].status).toBe("declined");
});

it("does not infer a tool success from a completed task when its result is missing", () => {
  render(
    <TaskTimeline
      {...props}
      runs={[{ ...run, status: "completed" }]}
      events={[event(1, "tool_call", { item: { id: "cmd", command: "pwd" } })]}
    />,
  );
  fireEvent.click(screen.getByText("任务已完成"));
  expect(screen.getByText("已中断")).toBeTruthy();
});

it("can stay collapsed while remote progress continues and shows the final reply outside the disclosure", () => {
  const view = render(
    <TaskTimeline
      {...props}
      runs={[run]}
      events={[event(1, "transport_status", { status: "reconnecting" })]}
    />,
  );
  const details = screen.getByText("连接中断 · 正在重连").closest("details")!;
  expect(details.open).toBe(true);
  fireEvent.click(screen.getByText("连接中断 · 正在重连"));
  expect(details.open).toBe(false);
  view.rerender(
    <TaskTimeline
      {...props}
      runs={[run]}
      events={[
        event(2, "transport_status", { status: "connected" }),
        event(3, "reasoning_chunk", {
          item_id: "a",
          text: "Progress after reconnect",
        }),
      ]}
    />,
  );
  expect(screen.getByText("任务执行中")).toBeTruthy();
  expect(details.open).toBe(false);
  view.rerender(
    <TaskTimeline
      {...props}
      runs={[{ ...run, status: "completed", result: "Remote final result" }]}
      events={[]}
    />,
  );
  expect(screen.getByText("任务已完成")).toBeTruthy();
  expect(screen.getByText("Remote final result").closest("details")).toBeNull();
});

it("uses native model metadata instead of guessing from the assistant answer", () => {
  render(
    <TaskTimeline
      {...props}
      runs={[{ ...run, status: "completed", result: "I am GPT-6" }]}
      events={[
        event(1, "model_info", {
          model: "custom/route-model",
          effort: "xhigh",
        }),
      ]}
    />,
  );
  expect(screen.getByText("custom/route-model · xhigh")).toBeTruthy();
  expect(screen.getByText("I am GPT-6")).toBeTruthy();
});

it("keeps commentary in the live process and collapses as soon as the final reply arrives", () => {
  const events = [
    event(1, "agent_message_chunk", {
      item_id: "progress",
      content: { text: "I will check." },
    }),
    event(2, "agent_message", {
      item_id: "progress",
      phase: "commentary",
      content: { text: "I will check the directory." },
    }),
    event(3, "tool_result", {
      item: { id: "pwd", command: "pwd", output: "/workspace" },
    }),
    event(4, "agent_message_chunk", {
      item_id: "answer",
      content: { text: "The directory" },
    }),
  ];
  const view = render(<TaskTimeline {...props} runs={[run]} events={events} />);
  const process = screen.getByText("任务执行中").closest("details")!;
  expect(process.open).toBe(true);
  expect(view.container.querySelector(".task-answer")).toBeNull();
  expect(screen.queryByText("I will check.")).toBeNull();
  expect(
    screen.getByText("I will check the directory.").closest("details"),
  ).toBe(process);
  expect(screen.getByText(run.prompt).closest(".from-user")).toBeTruthy();
  events.push(
    event(5, "agent_message", {
      item_id: "answer",
      phase: "final_answer",
      content: { text: "The directory is /workspace." },
    }),
    event(6, "assistant_message", { text: "The directory is /workspace." }),
  );
  view.rerender(<TaskTimeline {...props} runs={[run]} events={events} />);
  expect(process.open).toBe(false);
  expect(screen.getAllByText("The directory is /workspace.")).toHaveLength(1);
  expect(
    screen.getByText("The directory is /workspace.").closest(".task-answer"),
  ).toBeTruthy();
  fireEvent.click(screen.getByText("任务执行中"));
  expect(process.open).toBe(true);
  events.push(event(7, "run_finished", { status: "completed" }));
  view.rerender(<TaskTimeline {...props} runs={[run]} events={events} />);
  expect(process.open).toBe(true);
  expect(
    within(process).queryByText("The directory is /workspace."),
  ).toBeNull();
  const next = {
    ...run,
    id: "next",
    prompt: "Next question",
    created_at: "2026-09-28T10:01:00Z",
  };
  view.rerender(<TaskTimeline {...props} runs={[run, next]} events={events} />);
  expect(screen.getByText("任务执行中").closest("details")!.open).toBe(true);
});

it("separates legacy joined results only when the complete event groups match exactly", () => {
  const events = [
    event(1, "agent_message_chunk", { content: { text: "Let me check." } }),
    event(2, "tool_result", {
      item: { id: "tool", command: "pwd", output: "/workspace" },
    }),
    event(3, "agent_message_chunk", { content: { text: "The answer." } }),
  ];
  const content = turnContent(events, "Let me check.\nThe answer.");
  expect(content.answer).toBe("The answer.");
  expect(content.steps.map((step) => step.text)).toEqual([
    "Let me check.",
    "/workspace",
  ]);
  // Truncated history or independently authored text must never be trimmed.
  expect(
    turnContent(events.slice(1), "Let me check.\nThe answer.").answer,
  ).toBe("Let me check.\nThe answer.");
  expect(turnContent(events, "A different full answer.").answer).toBe(
    "A different full answer.",
  );
});

it("keeps native message boundaries and multiple Claude text blocks without duplicate finals", () => {
  const events = [
    event(1, "agent_message_chunk", {
      item_id: "comment",
      content: { text: "Progress" },
    }),
    event(2, "agent_message_chunk", {
      item_id: "answer",
      part: 0,
      content: { text: "First" },
    }),
    event(3, "agent_message", {
      item_id: "answer",
      part: 0,
      content: { text: "First paragraph" },
    }),
    event(4, "agent_message_chunk", {
      item_id: "answer",
      part: 1,
      content: { text: "Second paragraph" },
    }),
  ];
  expect(executionSteps(events).map((step) => step.text)).toEqual([
    "Progress",
    "First paragraph",
    "Second paragraph",
  ]);
  const result = turnContent(events, "First paragraph\nSecond paragraph");
  expect(result.steps.map((step) => step.text)).toEqual(["Progress"]);
  expect(result.answer).toBe("First paragraph\nSecond paragraph");
});

it("keeps failure diagnostics visible when no final reply is returned", () => {
  const view = render(<TaskTimeline {...props} runs={[run]} events={[]} />);
  const process = screen.getByText("任务执行中").closest("details")!;
  view.rerender(
    <TaskTimeline
      {...props}
      runs={[{ ...run, status: "failed", error: "CLI stopped" }]}
      events={[
        event(1, "agent_message_chunk", {
          content: { text: "Checking files" },
        }),
      ]}
    />,
  );
  expect(process.open).toBe(true);
  expect(screen.getByText("CLI stopped")).toBeTruthy();
  expect(view.container.querySelector(".task-answer")).toBeNull();
});

it("offers account recovery for the current failure and removes the prompt after an explicit switch", () => {
  const configure = vi.fn();
  const failed = { ...run, status: "failed" };
  const events = [
    event(1, "account_action_required", {
      account_id: "expired",
      reason: "progress_recorded",
    }),
  ];
  const view = render(
    <TaskTimeline
      {...props}
      runs={[failed]}
      events={events}
      onConfigureAccount={configure}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "选择账号后继续" }));
  expect(configure).toHaveBeenCalledOnce();
  events.push(
    event(2, "account_changed", {
      run_id: undefined,
      account_id: "new",
      previous_account_id: "expired",
    }),
  );
  view.rerender(
    <TaskTimeline
      {...props}
      runs={[failed]}
      events={events}
      onConfigureAccount={configure}
    />,
  );
  expect(screen.queryByRole("button", { name: "选择账号后继续" })).toBeNull();
  expect(screen.getByText("已切换账号")).toBeTruthy();
  expect(screen.getByText("等待选择账号")).toBeTruthy();
});
