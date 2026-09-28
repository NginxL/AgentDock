import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import DailyActivity from "./DailyActivity";
import type { Activity } from "./metrics";

const activity: Activity = {
  today: "2026-09-28",
  days: [
    { date: "2025-12-01", tokens: 100 },
    { date: "2026-07-01", tokens: 2000 },
    { date: "2026-09-28", tokens: 1234567 },
    { date: "2026-09-29", tokens: 100 },
  ],
  updated_at: 1,
  status: "ready",
};
afterEach(cleanup);

it("shows calendar days, ignores future activity and narrows the active-day count with the range", () => {
  render(
    <DailyActivity
      activity={activity}
      failed={false}
      t={(zh) => zh}
      lang="zh"
    />,
  );
  expect(screen.getByText("3 个活跃日", { exact: false })).toBeTruthy();
  const grid = screen.getByRole("group", { name: "每日 Token 用量" });
  expect(within(grid).getAllByRole("button")).toHaveLength(365);
  fireEvent.change(screen.getByLabelText("活跃图时间范围"), {
    target: { value: "90" },
  });
  expect(within(grid).getAllByRole("button")).toHaveLength(90);
  expect(screen.getByText("2 个活跃日", { exact: false })).toBeTruthy();
});

it("offers a compact tooltip and full accessible count with keyboard navigation", () => {
  render(
    <DailyActivity
      activity={activity}
      failed={false}
      t={(_, en) => en}
      lang="en"
    />,
  );
  const today = screen.getByRole("button", {
    name: "Sep 28, 2026: 1,234,567 Tokens",
  });
  expect(today.tabIndex).toBe(0);
  fireEvent.mouseEnter(today);
  expect(screen.getByRole("tooltip").textContent).toBe(
    "Sep 28, 2026 · 1.23M Tokens",
  );
  fireEvent.mouseLeave(today);
  fireEvent.keyDown(today, { key: "ArrowUp" });
  expect(document.activeElement?.getAttribute("aria-label")).toBe(
    "Sep 27, 2026: 0 Tokens",
  );
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).toBeNull();
});

it("marks incomplete or disconnected data without showing implementation notes", () => {
  const view = render(
    <DailyActivity
      activity={{ ...activity, status: "scanning" }}
      failed={false}
      t={(zh) => zh}
      lang="zh"
    />,
  );
  expect(screen.getByRole("status").textContent).toContain("更新中");
  view.rerender(
    <DailyActivity activity={activity} failed t={(_, en) => en} lang="en" />,
  );
  expect(screen.getByRole("status").textContent).toContain("Disconnected");
});
