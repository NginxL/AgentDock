import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import ExperimentalFeatures, { FeatureContext } from "./ExperimentalFeatures";
import AccountSelection from "./AccountSelection";

afterEach(cleanup);
const t = (_zh: string, en: string) => en;

test("enabling requires acknowledging the selected feature, not just opening settings", () => {
  const mutate = vi.fn().mockResolvedValue(true);
  render(
    <ExperimentalFeatures features={{}} mutate={mutate} busy={false} t={t} />,
  );
  const enable = screen.getAllByRole("button", {
    name: "Enable",
    hidden: true,
  })[0];
  expect((enable as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getAllByRole("checkbox", { hidden: true })[0]);
  fireEvent.click(enable);
  expect(mutate).toHaveBeenCalledWith("/api/features", {
    name: "automatic_failover",
    enabled: true,
    acknowledged: true,
  });
});

test("automatic failover is unavailable when the server disables it", () => {
  render(
    <FeatureContext.Provider value={{ automatic_failover: false }}>
      <AccountSelection
        provider="codex"
        environment="local"
        accounts={[]}
        value={{ account_policy: "manual" }}
        onChange={() => {}}
        t={t}
      />
    </FeatureContext.Provider>,
  );
  expect(
    (
      screen.getByRole("option", {
        name: "Switch on quota or sign-in failure",
      }) as HTMLOptionElement
    ).disabled,
  ).toBe(true);
  expect(
    (screen.getByRole("option", { name: "Fixed account" }) as HTMLOptionElement)
      .disabled,
  ).toBe(false);
});
