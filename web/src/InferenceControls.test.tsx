import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";
import InferenceControls from "./InferenceControls";
import type { Agent, Session, Language } from "./types";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const agent: Agent = {
  id: "agent",
  name: "A",
  provider: "codex",
  environment_id: "devbox",
  project_id: null,
  role: "",
  model: "model-a",
  effort: "high",
};
const original: Session = {
  id: "first",
  agent_id: "agent",
  project_id: null,
  title: "One",
  status: "idle",
  created_at: "",
  updated_at: "",
};
const models = [
  { id: "model-a", name: "Model A", efforts: ["low", "high"] },
  { id: "model-b", name: "Model B", efforts: ["low", "medium"] },
];
function setup(lang: Language = "zh", failure = false) {
  const fetch = vi.fn(async (_path: string, _init?: RequestInit) => {
    if (failure) throw new Error("offline");
    return { ok: true, json: async () => ({ models }) };
  });
  vi.stubGlobal("fetch", fetch);
  const mutation = vi.fn();
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
  function Harness() {
    const [session, setSession] = useState(original);
    return (
      <InferenceControls
        key={session.id}
        agent={agent}
        session={session}
        token="fixture"
        demo={false}
        runtimeEnabled
        busy={false}
        t={t}
        mutate={async (path, data) => {
          mutation(path, data);
          setSession({ ...session, ...(data as object), model_override: 1 });
          return true;
        }}
      />
    );
  }
  const view = render(<Harness />);
  return { ...view, fetch, mutation, t };
}
it.each<Language>(["zh", "en"])(
  "selects environment models and resets incompatible effort (%s)",
  async (lang) => {
    const { fetch, mutation, t } = setup(lang);
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", {
        name: new RegExp("^" + t("模型", "Model") + ":"),
      }),
    );
    fireEvent.click(
      await screen.findByRole("menuitemradio", { name: "Model B" }),
    );
    await waitFor(() =>
      expect(mutation).toHaveBeenCalledWith("/api/sessions/first/settings", {
        model: "model-b",
        effort: null,
      }),
    );
    expect(fetch.mock.calls[0][0]).toBe(
      "/api/models/codex?environment_id=devbox",
    );
    await screen.findByRole("button", {
      name: t("推理等级: 自动", "Reasoning effort: Auto"),
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: t("推理等级: 自动", "Reasoning effort: Auto"),
      }),
    );
    fireEvent.click(
      await screen.findByRole("menuitemradio", { name: t("中", "Medium") }),
    );
    await waitFor(() =>
      expect(mutation).toHaveBeenLastCalledWith(
        "/api/sessions/first/settings",
        { model: "model-b", effort: "medium" },
      ),
    );
    expect(agent.model).toBe("model-a");
    expect(agent.effort).toBe("high");
  },
);
it("supports second-click, close, outside-click and Escape without changing settings", async () => {
  const { mutation } = setup();
  const button = screen.getByRole("button", { name: "模型: model-a" });
  fireEvent.click(button);
  await screen.findByRole("menuitemradio", { name: "Model A" });
  fireEvent.click(button);
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(button);
  fireEvent.click(screen.getByRole("button", { name: "关闭" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(button);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(button);
  fireEvent.click(button);
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(mutation).not.toHaveBeenCalled();
});
it("retains the selected model when discovery fails and never silently selects another", async () => {
  const { mutation } = setup("zh", true);
  fireEvent.click(screen.getByRole("button", { name: "模型: model-a" }));
  await screen.findByText("模型列表暂不可用，当前设置已保留。");
  expect(
    screen
      .getByRole("menuitemradio", { name: "model-a" })
      .getAttribute("aria-checked"),
  ).toBe("true");
  expect(mutation).not.toHaveBeenCalled();
});
it("clears a stale model catalog when switching conversations and hosts", async () => {
  const { rerender } = setup();
  fireEvent.click(screen.getByRole("button", { name: "模型: model-a" }));
  await screen.findByRole("menuitemradio", { name: "Model B" });
  rerender(
    <InferenceControls
      key="second"
      agent={{ ...agent, provider: "claude", environment_id: "local" }}
      session={{ ...original, id: "second" }}
      token="fixture"
      runtimeEnabled
      demo={false}
      busy={false}
      mutate={vi.fn()}
      t={(zh) => zh}
    />,
  );
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "模型: model-a" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/models/claude?environment_id=local",
      expect.any(Object),
    ),
  );
});
