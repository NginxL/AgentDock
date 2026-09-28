import { useState } from "react";
import type { DockState, Mutate, Translate } from "../types";
import { Icon, PageTitle } from "../ui";

export default function Environments({
  state,
  t,
  busy,
  mutate,
}: {
  state: DockState;
  t: Translate;
  busy: boolean;
  mutate: Mutate;
}) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [python, setPython] = useState("python3");
  const environments = state.environments ?? [
    { id: "local", name: "This Mac", kind: "local", status: "connected" },
  ];
  const labels: Record<string, string> = {
    connected: t("已连接", "Connected"),
    connecting: t("连接中", "Connecting"),
    reconnecting: t("重连中", "Reconnecting"),
    disconnected: t("未连接", "Disconnected"),
    error: t("连接失败", "Connection failed"),
  };
  return (
    <>
      <PageTitle
        eyebrow={t("设备与连接", "DEVICES & CONNECTIONS")}
        title={t("运行环境", "Environments")}
      />
      <div className="button-row environment-actions">
        <button className="primary" onClick={() => setAdding(!adding)}>
          <Icon name="plus" size={18} />
          {t("添加 SSH 环境", "Add SSH environment")}
        </button>
      </div>
      {adding && (
        <section className="panel inset-form">
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              await mutate(
                "/api/environments",
                {
                  name: name.trim(),
                  ssh_host: host.trim(),
                  python: python.trim(),
                },
                () => {
                  setAdding(false);
                  setName("");
                  setHost("");
                },
              );
            }}
          >
            <div className="form-grid">
              <label>
                {t("环境名称", "Environment name")}
                <input
                  required
                  maxLength={100}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Devbox"
                />
              </label>
              <label>
                {t("SSH 地址或 Host 别名", "SSH destination or Host alias")}
                <input
                  required
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  placeholder="user@devbox / devbox"
                />
              </label>
              <label>
                {t("远端 Python", "Remote Python")}
                <input
                  required
                  value={python}
                  onChange={(e) => setPython(e.target.value)}
                  placeholder="python3"
                />
              </label>
            </div>
            <p className="form-hint">
              {t(
                "复用系统 SSH 配置与密钥。连接时会在远端用户目录安装 AgentDock 执行组件；原生 CLI 配置保持不变。",
                "Uses your system SSH configuration and keys. Connecting installs the AgentDock runner in the remote user's home directory and preserves native CLI settings.",
              )}
            </p>
            <button className="primary" disabled={busy}>
              {t("添加环境", "Add environment")}
            </button>
          </form>
        </section>
      )}
      <div className="environment-grid">
        {environments.map((env) => (
          <section className="panel environment-card" key={env.id}>
            <div className="record-heading">
              <div>
                <span className="eyebrow">
                  {env.kind === "local" ? t("本地设备", "LOCAL") : "SSH"}
                </span>
                <h2>
                  {env.kind === "local" ? t("本机", "This Mac") : env.name}
                </h2>
              </div>
              <span
                className={`pill ${env.status === "connected" ? "good" : ""}`}
              >
                {labels[env.status] ?? env.status}
              </span>
            </div>
            {env.ssh_host && <p className="path-line">{env.ssh_host}</p>}
            <p>
              {t("关联 Agent", "Linked agents")} ·{" "}
              {
                state.agents.filter(
                  (a) => (a.environment_id ?? "local") === env.id,
                ).length
              }
            </p>
            <div className="environment-providers">
              {Object.entries(env.payload?.providers ?? {}).map(
                ([provider, data]) => (
                  <span key={provider}>
                    {provider === "codex" ? "Codex" : "Claude Code"} ·{" "}
                    {data.available
                      ? data.version || t("可用", "Available")
                      : t("未检测到", "Not detected")}
                  </span>
                ),
              )}
            </div>
            {env.kind === "ssh" && (
              <div className="button-row">
                <button
                  className="secondary"
                  disabled={busy || !state.runtime.enabled}
                  onClick={() =>
                    void mutate(`/api/environments/${env.id}/connect`, {})
                  }
                >
                  {t("连接 / 检查", "Connect / check")}
                </button>
                {!state.agents.some((a) => a.environment_id === env.id) &&
                  !state.projects.some((p) => p.environment_id === env.id) && (
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() =>
                        void mutate(`/api/environments/${env.id}/remove`, {})
                      }
                    >
                      {t("移除", "Remove")}
                    </button>
                  )}
              </div>
            )}
          </section>
        ))}
      </div>
    </>
  );
}
