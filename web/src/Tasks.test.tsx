import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import Tasks, { TaskForm } from "./views/Tasks";
import type { DockState, ProjectTask, TaskDetail, Mutate, Run } from "./types";

const t = (zh: string) => zh;
const task: ProjectTask = {
  id: "t",
  project_id: "p",
  title: "Ship feature",
  goal: "Clear project goal",
  criteria: "Success path\nFailure path",
  owner_id: "a",
  session_id: "s",
  status: "review",
  intent: "develop",
  acceptance_policy: "human",
  review_required: true,
  workspace_mode: "shared",
  revision: 2,
  delivery_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};
const state: DockState = {
  runtime: { enabled: true, version: "fixture" },
  projects: [
    { id: "p", name: "Project", path: "/fixture" },
    { id: "q", name: "Other", path: "/other" },
  ],
  agents: [
    { id: "a", project_id: "p", name: "Owner", provider: "codex", role: "" },
    {
      id: "b",
      project_id: "p",
      name: "Reviewer",
      provider: "claude",
      role: "",
    },
    {
      id: "c",
      project_id: "q",
      name: "Unrelated",
      provider: "codex",
      role: "",
    },
  ],
  sessions: [],
  runs: [],
  tasks: [task],
  task_questions: [],
  memories: [],
  proposals: [],
  messages: [],
  events: [],
  approvals: [],
  quotas: [],
  subscriptions: [],
};
const detail: TaskDetail = {
  ...task,
  inputs: [],
  questions: [],
  deliveries: [],
  sessions: [],
  runs: [],
  journal: [],
  workspaces: [],
};
const run: Run = {
  id: "r",
  session_id: "s",
  agent_id: "a",
  project_id: "p",
  work_task_id: "t",
  task_role: "owner",
  task_intent: "develop",
  prompt: "Question",
  status: "completed",
  result: "Verified reply",
  origin: "human",
  depth: 0,
  created_at: task.created_at,
  updated_at: task.updated_at,
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount(
  value: TaskDetail = detail,
  mutate: Mutate = vi.fn(async () => true),
) {
  const fetchMock = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path === "/api/tasks/t" ? value : { events: [], models: [] },
  }));
  vi.stubGlobal("fetch", fetchMock);
  const props = {
    state: { ...state, tasks: [value] },
    t,
    busy: false,
    mutate,
    projectID: "p",
    taskID: "t",
    onSelect: vi.fn(),
    token: "test",
    demo: false,
    lang: "zh" as const,
  };
  return { ...render(<Tasks {...props} />), fetchMock, props };
}

it("creates a task before starting execution and limits owners to the project", async () => {
  let active = false;
  const mutate = vi.fn<Mutate>(async (path, _body, done) => {
    expect(active).toBe(false);
    active = true;
    done?.(task);
    await Promise.resolve();
    active = false;
    return true;
  });
  const onCreated = vi.fn();
  render(
    <TaskForm
      state={state}
      t={t}
      busy={false}
      mutate={mutate}
      projectID="p"
      close={vi.fn()}
      onCreated={onCreated}
    />,
  );
  expect(screen.queryByRole("option", { name: "Unrelated" })).toBeNull();
  fireEvent.change(screen.getByLabelText("任务名称"), {
    target: { value: "Ship feature" },
  });
  fireEvent.change(screen.getByLabelText("目标"), {
    target: { value: "Build it" },
  });
  fireEvent.change(screen.getByLabelText("验收要求（每行一项）"), {
    target: { value: "Verified" },
  });
  fireEvent.click(screen.getByRole("button", { name: "创建并执行" }));
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(task));
  expect(mutate.mock.calls.map((c) => c[0])).toEqual([
    "/api/tasks",
    "/api/tasks/t/inputs",
  ]);
  expect(mutate.mock.calls[1][1]).toMatchObject({
    intent: "develop",
    body: "Build it",
    request_id: expect.any(String),
  });
});

it("saving a draft does not start any execution", async () => {
  const mutate = vi.fn<Mutate>(async (_p, _d, done) => {
    done?.(task);
    return true;
  });
  render(
    <TaskForm
      state={{ ...state, runtime: { enabled: false, version: "fixture" } }}
      t={t}
      busy={false}
      mutate={mutate}
      projectID="p"
      close={vi.fn()}
      onCreated={vi.fn()}
    />,
  );
  fireEvent.change(screen.getByLabelText("任务名称"), {
    target: { value: "Draft" },
  });
  fireEvent.change(screen.getByLabelText("目标"), {
    target: { value: "Goal" },
  });
  fireEvent.change(screen.getByLabelText("验收要求（每行一项）"), {
    target: { value: "Criteria" },
  });
  fireEvent.change(screen.getByLabelText("处理方式"), {
    target: { value: "record" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存任务" }));
  await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
});

it("offers cross-project conversion for daily chats without modifying their history", async () => {
  const mutate = vi.fn<Mutate>(async (_p, _d, done) => {
    done?.(task);
    return true;
  });
  const source = {
    id: "daily",
    agent_id: "c",
    project_id: null,
    title: "Daily idea",
    status: "completed",
    created_at: "",
    updated_at: "",
  };
  render(
    <TaskForm
      state={state}
      t={t}
      busy={false}
      mutate={mutate}
      source={source}
      close={vi.fn()}
      onCreated={vi.fn()}
    />,
  );
  fireEvent.change(screen.getByLabelText("项目"), { target: { value: "p" } });
  fireEvent.change(screen.getByLabelText("目标"), {
    target: { value: "Convert" },
  });
  fireEvent.change(screen.getByLabelText("验收要求（每行一项）"), {
    target: { value: "Check" },
  });
  fireEvent.change(screen.getByLabelText("处理方式"), {
    target: { value: "record" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存任务" }));
  await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
  expect(mutate.mock.calls[0][1]).toMatchObject({
    project_id: "p",
    source_session_id: "daily",
  });
});

it("shows the final reply with the process collapsed and toggles open and closed", async () => {
  const session = {
    id: "s",
    agent_id: "a",
    project_id: "p",
    title: "Execution",
    status: "completed",
    created_at: "",
    updated_at: "",
    task_role: "owner",
  };
  mount({ ...detail, runs: [run], sessions: [session] });
  await screen.findByText("Verified reply");
  expect(screen.queryByLabelText("会话")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "查看过程" }));
  expect(screen.getByLabelText("会话")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "收起过程" }));
  expect(screen.queryByLabelText("会话")).toBeNull();
});

it("persists a decision via the task question endpoint", async () => {
  const mutate = vi.fn<Mutate>(async () => true);
  mount(
    {
      ...detail,
      status: "waiting_input",
      questions: [
        {
          id: "question",
          task_id: "t",
          run_id: "r",
          question: "Choose output",
          options: ["JSON", "CSV"],
          status: "open",
          created_at: "",
        },
      ],
    },
    mutate,
  );
  await screen.findByText("Choose output");
  fireEvent.click(screen.getByRole("button", { name: "JSON" }));
  fireEvent.click(screen.getByRole("button", { name: "确认并继续" }));
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith(
      "/api/tasks/t/questions/question/answer",
      { answer: "JSON" },
      expect.any(Function),
    ),
  );
});

it("does not enable acceptance for unverified criteria", async () => {
  mount({
    ...detail,
    delivery_id: "d",
    deliveries: [
      {
        id: "d",
        run_id: "r",
        revision: 2,
        summary: "Candidate",
        status: "candidate",
        checks: [
          {
            criterion: "Success path",
            status: "unverified",
            evidence: "Still pending",
          },
        ],
        artifacts: [],
        risks: "",
        created_at: "",
      },
    ],
  });
  await screen.findByText("Candidate");
  expect(
    (screen.getByRole("button", { name: "确认验收" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});

it("Enter submits once, Shift+Enter and IME confirmation preserve the draft and retries use one identity", async () => {
  const mutate = vi.fn<Mutate>(async () => false);
  mount(detail, mutate);
  await screen.findByLabelText("补充需求或继续任务");
  const input = screen.getByLabelText("补充需求或继续任务");
  fireEvent.change(input, { target: { value: "Next requirement" } });
  fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
  fireEvent.compositionStart(input);
  fireEvent.keyDown(input, { key: "Enter" });
  fireEvent.compositionEnd(input);
  expect(mutate).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
  await act(async () => {
    await Promise.resolve();
  });
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(mutate).toHaveBeenCalledTimes(2));
  expect(mutate.mock.calls[0][1]).toEqual(mutate.mock.calls[1][1]);
});

it("exposes queue for all live runs and disables unsupported steering", async () => {
  mount({ ...detail, status: "active", runs: [{ ...run, status: "running" }] });
  await screen.findByLabelText("发送时机");
  expect(
    (screen.getByRole("option", { name: "立即调整" }) as HTMLOptionElement)
      .disabled,
  ).toBe(true);
});

it("requires an explicit choice when the steer target ends", async () => {
  const current = {
    ...detail,
    status: "active",
    runs: [{ ...run, status: "running" }],
    can_steer_run_id: "r",
  };
  const { rerender, props } = mount(current);
  await screen.findByLabelText("发送时机");
  fireEvent.change(screen.getByLabelText("发送时机"), {
    target: { value: "steer" },
  });
  fireEvent.change(screen.getByLabelText("补充需求或继续任务"), {
    target: { value: "Change now" },
  });
  current.can_steer_run_id = "";
  current.status = "review";
  current.runs = [];
  rerender(<Tasks {...props} state={{ ...props.state, runs: [] }} />);
  await screen.findByText("本轮已结束或暂不支持调整，请选择排队处理");
  expect(
    (screen.getByRole("button", { name: "发送" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});

it("keeps paused tasks out of the composer and supports explicit reassign/recovery", async () => {
  const mutate = vi.fn<Mutate>(async () => true);
  mount({ ...detail, status: "paused" }, mutate);
  await screen.findByText("已暂停");
  expect(screen.queryByLabelText("补充需求或继续任务")).toBeNull();
  fireEvent.change(screen.getByLabelText("负责人"), { target: { value: "b" } });
  fireEvent.click(screen.getByRole("button", { name: "更换负责人并继续" }));
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith(
      "/api/tasks/t/resume",
      { owner_id: "b", intent: "develop", request_id: expect.any(String) },
      expect.any(Function),
    ),
  );
});

it("lists task questions separately from daily conversations and opens the chosen task", () => {
  const onSelect = vi.fn();
  render(
    <Tasks
      state={{
        ...state,
        task_questions: [
          {
            id: "q",
            task_id: "t",
            run_id: "r",
            question: "A decision",
            options: [],
            status: "open",
            created_at: "",
          },
        ],
      }}
      t={t}
      busy={false}
      mutate={vi.fn()}
      projectID="p"
      taskID=""
      onSelect={onSelect}
      token="t"
      demo={false}
      lang="zh"
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: /Ship feature A decision/ }),
  );
  expect(onSelect).toHaveBeenCalledWith("t");
  fireEvent.click(screen.getByRole("button", { name: "新建任务" }));
  expect(screen.getByLabelText("目标")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "新建任务" }));
  expect(screen.queryByLabelText("目标")).toBeNull();
});
