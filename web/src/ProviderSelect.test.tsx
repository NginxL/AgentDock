import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import ProviderSelect from "./ProviderSelect";
import type { Provider } from "./types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

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

it("places the menu outside clipping ancestors and uses the available space above or below", () => {
  vi.stubGlobal("innerHeight", 600);
  vi.stubGlobal("innerWidth", 800);
  const { trigger } = setup();
  let bounds = new DOMRect(100, 500, 300, 40);
  vi.spyOn(trigger, "getBoundingClientRect").mockImplementation(() => bounds);
  fireEvent.click(trigger);
  const menu = screen.getByRole("listbox").parentElement!;
  expect(menu.parentElement).toBe(document.body);
  expect(menu.style.bottom).toBe("106px");
  expect(menu.style.maxHeight).toBe("486px");
  expect(menu.style.width).toBe("300px");
  bounds = new DOMRect(600, 30, 300, 40);
  fireEvent.scroll(window);
  expect(menu.style.bottom).toBe("");
  expect(menu.style.top).toBe("76px");
  expect(menu.style.left).toBe("492px");
  expect(menu.style.maxHeight).toBe("516px");
  bounds = new DOMRect(100, -100, 300, 40);
  fireEvent.scroll(document);
  expect(screen.queryByRole("listbox")).toBeNull();
});

it("fits the visual viewport when zoom or the on-screen keyboard reduces space", () => {
  vi.stubGlobal("innerHeight", 700);
  const viewport = Object.assign(new EventTarget(), {
    offsetLeft: 40,
    offsetTop: 100,
    width: 300,
    height: 320,
  });
  vi.stubGlobal("visualViewport", viewport);
  const { trigger } = setup();
  vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue(
    new DOMRect(20, 350, 400, 40),
  );
  fireEvent.click(trigger);
  const menu = screen.getByRole("listbox").parentElement!;
  expect(menu.style.width).toBe("284px");
  expect(menu.style.left).toBe("48px");
  expect(menu.style.bottom).toBe("356px");
  expect(menu.style.maxHeight).toBe("236px");
  viewport.height = 600;
  act(() => viewport.dispatchEvent(new Event("resize")));
  expect(menu.style.top).toBe("396px");
  expect(menu.style.maxHeight).toBe("296px");
});

it("does not fight pointer scrolling and reveals keyboard choices only inside the list", () => {
  const { trigger, submit } = setup();
  fireEvent.click(trigger);
  const list = screen.getByRole("listbox");
  const claude = screen.getByRole("option", { name: "Claude Code" });
  const codex = screen.getByRole("option", { name: "Codex" });
  vi.spyOn(list, "getBoundingClientRect").mockReturnValue(
    new DOMRect(0, 100, 300, 100),
  );
  vi.spyOn(claude, "getBoundingClientRect").mockReturnValue(
    new DOMRect(0, 300, 300, 50),
  );
  list.scrollTop = 120;
  fireEvent.pointerMove(claude);
  expect(list.scrollTop).toBe(120);
  // End must still reveal the final enabled item even if it was already hovered.
  fireEvent.keyDown(trigger, { key: "End" });
  expect(list.scrollTop).toBe(270);
  vi.spyOn(codex, "getBoundingClientRect").mockReturnValue(
    new DOMRect(0, 20, 300, 50),
  );
  fireEvent.keyDown(trigger, { key: "Home" });
  expect(list.scrollTop).toBe(190);
  expect(submit).not.toHaveBeenCalled();
});

it("keeps portal controls open when receiving focus and closes them on Escape or external focus", () => {
  const { trigger } = setup();
  trigger.focus();
  fireEvent.click(trigger);
  const close = screen.getByRole("button", { name: "关闭服务选择" });
  act(() => close.focus());
  expect(screen.getByRole("listbox")).toBeTruthy();
  fireEvent.pointerDown(close);
  expect(screen.getByRole("listbox")).toBeTruthy();
  fireEvent.keyDown(close, { key: "Escape" });
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  fireEvent.click(trigger);
  act(() => screen.getByLabelText("名称").focus());
  expect(screen.queryByRole("listbox")).toBeNull();
});
