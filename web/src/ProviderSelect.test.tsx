import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import ProviderSelect from "./ProviderSelect";
import type { Provider } from "./types";

afterEach(cleanup);

function setup(disabled = false) {
  const change = vi.fn();
  const submit = vi.fn((event) => event.preventDefault());
  function Harness() {
    const [provider, setProvider] = useState<Provider>("codex");
    return (
      <form onSubmit={submit}>
        <ProviderSelect
          value={provider}
          onChange={(value) => {
            setProvider(value);
            change(value);
          }}
          disabled={disabled}
          availability={{
            codex: { available: true },
            claude: { available: true },
          }}
          t={(zh) => zh}
        />
        <input aria-label="名称" />
      </form>
    );
  }
  render(<Harness />);
  return {
    change,
    submit,
    trigger: screen.getByRole("combobox", { name: "服务" }),
  };
}

it("selects a provider without submitting, and lets repeat clicks and the close button dismiss", () => {
  const { trigger, change, submit } = setup();
  fireEvent.click(trigger);
  expect(
    screen.getByRole("option", { name: "Codex" }).getAttribute("aria-selected"),
  ).toBe("true");
  fireEvent.click(screen.getByRole("option", { name: "Claude Code" }));
  expect(change).toHaveBeenCalledWith("claude");
  expect(trigger.textContent).toContain("Claude Code");
  expect(screen.queryByRole("listbox")).toBeNull();
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("option", { name: "Claude Code" }));
  expect(change).toHaveBeenCalledTimes(1);
  fireEvent.click(trigger);
  fireEvent.click(trigger);
  expect(screen.queryByRole("listbox")).toBeNull();
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("button", { name: "关闭服务选择" }));
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(submit).not.toHaveBeenCalled();
});

it("supports keyboard selection and cancels uncommitted choices on Escape, Tab and outside clicks", () => {
  const { trigger, change, submit } = setup();
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.keyDown(trigger, { key: "End" });
  expect(trigger.getAttribute("aria-activedescendant")).toBe(
    screen.getByRole("option", { name: "Claude Code" }).id,
  );
  expect(change).not.toHaveBeenCalled();
  fireEvent.keyDown(trigger, { key: "Escape" });
  expect(screen.queryByRole("listbox")).toBeNull();
  fireEvent.keyDown(trigger, { key: "Enter" });
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.keyDown(trigger, { key: "Enter" });
  expect(change).toHaveBeenCalledWith("claude");
  fireEvent.keyDown(trigger, { key: " " });
  fireEvent.keyDown(trigger, { key: "Home" });
  fireEvent.keyDown(trigger, { key: "Tab" });
  expect(screen.queryByRole("listbox")).toBeNull();
  fireEvent.click(trigger);
  fireEvent.pointerDown(screen.getByLabelText("名称"));
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(change).toHaveBeenCalledTimes(1);
  expect(submit).not.toHaveBeenCalled();
});

it("keeps the provider fixed when editing an existing agent", () => {
  const { trigger, change } = setup(true);
  expect((trigger as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(trigger);
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(change).not.toHaveBeenCalled();
});

it("lists ten services, prevents missing CLI selection and skips them by keyboard", () => {
  const change = vi.fn();
  const refresh = vi.fn();
  render(
    <ProviderSelect
      value="codex"
      onChange={change}
      disabled={false}
      availability={{
        codex: { available: true },
        gemini: { available: true },
        qwen: { available: true },
      }}
      onRefresh={refresh}
      t={(zh) => zh}
    />,
  );
  const trigger = screen.getByRole("combobox");
  fireEvent.click(trigger);
  expect(screen.getAllByRole("option")).toHaveLength(10);
  const pi = screen.getByRole("option", { name: /Pi/ });
  expect(pi.getAttribute("aria-disabled")).toBe("true");
  expect(pi.textContent).toContain("pi-acp");
  fireEvent.click(pi);
  expect(change).not.toHaveBeenCalled();
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  expect(trigger.getAttribute("aria-activedescendant")).toBe(
    screen.getByRole("option", { name: "Gemini CLI" }).id,
  );
  fireEvent.keyDown(trigger, { key: "Enter" });
  expect(change).toHaveBeenCalledWith("gemini");
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("button", { name: "重新检测服务" }));
  expect(refresh).toHaveBeenCalledOnce();
  expect(screen.getByRole("listbox")).toBeTruthy();
  expect(screen.queryByText(/Coco|PiCode/)).toBeNull();
});
