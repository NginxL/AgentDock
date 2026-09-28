import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import AgentConnection, {
  NEW_SSH_CONNECTION,
  type SSHConnectionDraft,
} from "./AgentConnection";
import type { Environment, Mutate } from "./types";

afterEach(cleanup);
function Harness({
  mutate,
  environments = [],
}: {
  mutate: Mutate;
  environments?: Environment[];
}) {
  const [value, setValue] = useState("local");
  const [draft, setDraft] = useState<SSHConnectionDraft>({
    host: "",
    python: "python3",
    previous: "local",
  });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        throw new Error("Connection setup submitted the agent");
      }}
    >
      <AgentConnection
        value={value}
        onChange={setValue}
        draft={draft}
        onDraftChange={setDraft}
        environments={environments}
        t={(zh) => zh}
        busy={false}
        runtimeEnabled
        locked={false}
        mutate={mutate}
      />
    </form>
  );
}
function enterHost(value = "builder@devbox") {
  fireEvent.change(screen.getByLabelText("运行位置"), {
    target: { value: NEW_SSH_CONNECTION },
  });
  fireEvent.change(screen.getByLabelText("SSH 地址或 Host 别名"), {
    target: { value },
  });
}

it("registers and connects an SSH host only after an explicit click, without creating an agent or changing its name", async () => {
  const mutate = vi.fn<Mutate>(async (path, _data, success) => {
    success?.(
      path === "/api/environments"
        ? { id: "new-host" }
        : { status: "connected" },
    );
    return true;
  });
  render(<Harness mutate={mutate} />);
  enterHost();
  expect(mutate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "连接并使用" }));
  await waitFor(() => expect(mutate).toHaveBeenCalledTimes(2));
  expect(mutate.mock.calls[0]).toEqual([
    "/api/environments",
    {
      name: "builder@devbox",
      ssh_host: "builder@devbox",
      python: "python3",
    },
    expect.any(Function),
  ]);
  expect(mutate.mock.calls[1]).toEqual([
    "/api/environments/new-host/connect",
    {},
  ]);
});

it("reuses an existing SSH connection and keeps retries on the same saved host", async () => {
  const env: Environment = {
    id: "saved",
    name: "Existing",
    kind: "ssh",
    ssh_host: "builder@devbox",
    status: "error",
  };
  const mutate = vi.fn<Mutate>(async () => false);
  render(<Harness mutate={mutate} environments={[env]} />);
  enterHost();
  fireEvent.click(screen.getByRole("button", { name: "连接并使用" }));
  const retry = await screen.findByRole("button", { name: "连接 / 检查" });
  await waitFor(() =>
    expect((retry as HTMLButtonElement).disabled).toBe(false),
  );
  expect((screen.getByLabelText("运行位置") as HTMLSelectElement).value).toBe(
    "saved",
  );
  fireEvent.click(retry);
  await waitFor(() => expect(mutate).toHaveBeenCalledTimes(2));
  expect(
    mutate.mock.calls.every(
      ([path]) => path === "/api/environments/saved/connect",
    ),
  ).toBe(true);
});

it("does not connect when registration fails or its refreshed result is unavailable", async () => {
  const mutate = vi.fn<Mutate>(async () => true);
  render(<Harness mutate={mutate} />);
  enterHost();
  fireEvent.click(screen.getByRole("button", { name: "连接并使用" }));
  await waitFor(() =>
    expect(
      (screen.getByRole("button", { name: "连接并使用" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false),
  );
  expect(mutate).toHaveBeenCalledTimes(1);
  expect(screen.getByDisplayValue("builder@devbox")).toBeTruthy();
});

it("prevents duplicate submissions while connecting and lets advanced settings collapse", async () => {
  let finish!: () => void;
  const mutate = vi.fn<Mutate>(
    () =>
      new Promise((resolve) => {
        finish = () => resolve(false);
      }),
  );
  render(<Harness mutate={mutate} />);
  enterHost();
  const advanced = screen.getByText("高级连接设置");
  fireEvent.click(advanced);
  expect(advanced.closest("details")!.open).toBe(true);
  fireEvent.click(advanced);
  expect(advanced.closest("details")!.open).toBe(false);
  const connect = screen.getByRole("button", { name: "连接并使用" });
  fireEvent.click(connect);
  fireEvent.click(connect);
  expect(mutate).toHaveBeenCalledTimes(1);
  finish();
  await waitFor(() =>
    expect((connect as HTMLButtonElement).disabled).toBe(false),
  );
});
