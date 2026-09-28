import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { TPS, type Meter } from "./metrics";
const meter: Meter = {
  input_tokens: 20,
  output_tokens: 10,
  cache_read_tokens: 5,
  cache_write_tokens: 0,
  total_tokens: 30,
  sessions: 1,
  active_sessions: 1,
  current_tps: null,
  average_tps: 0,
  points: [],
  updated_at: null,
};
afterEach(cleanup);
it("distinguishes unknown sampling from an idle zero", () => {
  const r = render(<TPS meter={meter} t={(zh) => zh} />);
  expect(screen.getByText("— TPS")).toBeTruthy();
  r.rerender(<TPS meter={{ ...meter, current_tps: 0 }} t={(zh) => zh} />);
  expect(screen.queryByText("— TPS")).toBeNull();
  expect(screen.getAllByText("0.0 TPS").length).toBe(2);
});
it("does not display old rates as current when disconnected", () => {
  render(<TPS meter={{ ...meter, current_tps: 50 }} stale t={(_, en) => en} />);
  expect(screen.queryByText("50.0 TPS")).toBeNull();
  expect(screen.getByText(/Connection lost/)).toBeTruthy();
});
