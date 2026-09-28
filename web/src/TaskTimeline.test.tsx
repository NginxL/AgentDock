import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import TaskTimeline, { executionSteps } from "./TaskTimeline";
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
  expect(disclosure.open).toBe(false);
  fireEvent.click(summary);
  expect(disclosure.open).toBe(true);
  events.push(
    event(3, "reasoning_chunk", {
      item_id: "thought",
      part: 0,
      text: "the workspace.",
    }),
    event(4, "tool_output", { item_id: "cmd", text: "/workspace\n" }),
  );
  view.rerender(<TaskTimeline {...props} runs={[run]} events={events} />);
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
  render(<TaskTimeline {...props} runs={[{ ...run, status: "completed" }]}
    events={[event(1, "tool_call", { item: { id: "cmd", command: "pwd" } })]} />);
  fireEvent.click(screen.getByText("任务已完成"));
  expect(screen.getByText("已中断")).toBeTruthy();
});
