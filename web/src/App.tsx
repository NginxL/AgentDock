import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ApiError, listOf, request } from "./api";
import type {
  DockState,
  Environment,
  Language,
  Mutate,
  Quota,
  Translate,
} from "./types";
import { Brand, Empty, Icon, errorMessage } from "./ui";
import { demoState } from "./demo";
import Workspace from "./views/Workspace";
import Messages from "./views/Messages";
import Memories from "./views/Memories";
import Usage from "./views/Usage";
import Tokens from "./views/Tokens";
import { useMetrics } from "./metrics";

type Tab = "workspace" | "messages" | "memory" | "usage" | "tokens";

declare global {
  interface Window {
    __AGENTDOCK_DESKTOP_TOKEN__?: string;
    __AGENTDOCK_DESKTOP_LANGUAGE__?: Language;
    webkit?: {
      messageHandlers?: {
        agentdockLanguage?: { postMessage(language: Language): void };
      };
    };
  }
}

export default function App() {
  const [demo, setDemo] = useState(
    () => new URLSearchParams(window.location.search).get("demo") === "1",
  );
  const [lang, setLang] = useState<Language>(() =>
    window.__AGENTDOCK_DESKTOP_LANGUAGE__ === "en" ? "en" : "zh",
  );
  const t: Translate = (zh, en) => (lang === "zh" ? zh : en);
  const [token, setToken] = useState("");
  const tokenRef = useRef("");
  const mutationInFlight = useRef(false);
  const stateEpoch = useRef(0);
  const quotaEpoch = useRef(0);
  const [entryToken, setEntryToken] = useState("");
  const [state, setState] = useState<DockState | null>(() =>
    demo ? demoState("zh") : null,
  );
  const { metrics, failed: metricsFailed } = useMetrics(
    token,
    demo,
    state?.agents.map((a) => a.id) ?? [],
  );
  const [connecting, setConnecting] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [tab, setTab] = useState<Tab>("workspace");
  const [usageVisit, setUsageVisit] = useState(0);
  const [quotaRefreshing, setQuotaRefreshing] = useState(false);
  const [quotaRefreshFailed, setQuotaRefreshFailed] = useState(false);
  const quotaRequest = useRef<AbortController | null>(null);
  const [projectID, setProjectID] = useState("");
  const [projectForm, setProjectForm] = useState(false);
  const [agentEnvironment, setAgentEnvironment] = useState<string | null>(null);
  const desktopToken = useRef(window.__AGENTDOCK_DESKTOP_TOKEN__ ?? "");

  useEffect(() => {
    const credential = desktopToken.current;
    delete window.__AGENTDOCK_DESKTOP_TOKEN__;
    if (!credential || demo) return;
    let cancelled = false;
    setConnecting(true);
    void request<DockState>(credential, "/api/state")
      .then((next) => {
        if (cancelled) return;
        tokenRef.current = credential;
        setToken(credential);
        setState(next);
      })
      .catch(() => {
        if (!cancelled)
          setError(
            "无法连接本地服务，请重新打开 AgentDock。 / Reopen AgentDock to reconnect.",
          );
      })
      .finally(() => {
        if (!cancelled) setConnecting(false);
      });
    return () => {
      cancelled = true;
    };
  }, [demo]);

  useEffect(() => {
    if (demo) setState(demoState(lang));
  }, [demo, lang]);

  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    if (!demo)
      window.webkit?.messageHandlers?.agentdockLanguage?.postMessage(lang);
  }, [lang, demo]);

  const disconnect = useCallback(() => {
    setDemo(false);
    tokenRef.current = "";
    stateEpoch.current += 1;
    setToken("");
    setEntryToken("");
    setState(null);
    setProjectID("");
    setNotice("");
    setError("");
  }, []);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const currentToken = tokenRef.current;
    const currentEpoch = stateEpoch.current;
    const currentQuotaEpoch = quotaEpoch.current;
    if (!currentToken) return false;
    const next = await request<DockState>(
      currentToken,
      "/api/state",
      undefined,
      signal,
    );
    if (
      currentToken !== tokenRef.current ||
      currentEpoch !== stateEpoch.current
    )
      return false;
    setState((current) =>
      currentQuotaEpoch === quotaEpoch.current
        ? next
        : { ...next, quotas: current?.quotas ?? next.quotas },
    );
    return true;
  }, []);

  const canRefreshQuota = !demo && !!token && !!state?.runtime.enabled;

  useEffect(() => {
    setQuotaRefreshing(false);
    setQuotaRefreshFailed(false);
    return () => {
      quotaRequest.current?.abort();
      quotaRequest.current = null;
    };
  }, [token, canRefreshQuota]);

  const quotaProviders = [
    ...new Set(
      state?.agents.map(
        (a) => `${a.environment_id ?? "local"}:${a.provider}`,
      ) ?? [],
    ),
  ]
    .sort()
    .reverse()
    .join(",");
  const refreshQuotas = useCallback(async () => {
    if (!canRefreshQuota || !quotaProviders || quotaRequest.current) return;
    const credential = tokenRef.current;
    const controller = new AbortController();
    quotaRequest.current = controller;
    setQuotaRefreshing(true);
    setQuotaRefreshFailed(false);
    quotaEpoch.current += 1;
    try {
      const results = await Promise.allSettled(
        quotaProviders.split(",").map(async (connection) => {
          const [environment_id, provider] = connection.split(":");
          const snapshot = await request<Quota>(
            credential,
            "/api/quotas/refresh",
            environment_id === "local"
              ? { provider }
              : { provider, environment_id },
            controller.signal,
          );
          if (
            snapshot.provider !== provider ||
            (snapshot.environment_id ?? "local") !== environment_id ||
            !Array.isArray(snapshot.windows)
          )
            throw new Error("Invalid quota snapshot");
          if (controller.signal.aborted || tokenRef.current !== credential)
            return;
          // Preserve newer quota values without discarding unrelated workspace edits.
          quotaEpoch.current += 1;
          setState(
            (current) =>
              current && {
                ...current,
                quotas: [
                  ...listOf(current.quotas).filter(
                    (q) =>
                      q.provider !== provider ||
                      (q.environment_id ?? "local") !== environment_id,
                  ),
                  snapshot,
                ],
              },
          );
        }),
      );
      if (!controller.signal.aborted && tokenRef.current === credential)
        setQuotaRefreshFailed(
          results.some((result) => result.status === "rejected"),
        );
    } finally {
      if (quotaRequest.current === controller) {
        quotaRequest.current = null;
        setQuotaRefreshing(false);
      }
    }
  }, [canRefreshQuota, token, quotaProviders]);

  useEffect(() => {
    if (tab === "usage") void refreshQuotas();
  }, [tab, usageVisit, refreshQuotas]);

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    let inFlight = false;
    const interval = window.setInterval(async () => {
      if (
        inFlight ||
        mutationInFlight.current ||
        document.visibilityState === "hidden"
      )
        return;
      inFlight = true;
      try {
        await refresh(controller.signal);
      } catch (e) {
        if (controller.signal.aborted) return;
        if (e instanceof ApiError && e.status === 401) {
          disconnect();
          setError(
            lang === "zh"
              ? "连接凭据已失效，请重新连接。"
              : "Connection credentials expired. Please reconnect.",
          );
        } else
          setError(
            lang === "zh"
              ? "暂时无法刷新。显示的是上次读取的数据。"
              : "Refresh failed. Showing the last available data.",
          );
      } finally {
        inFlight = false;
      }
    }, 8000);
    return () => {
      window.clearInterval(interval);
      controller.abort();
    };
  }, [token, refresh, disconnect, lang]);

  useEffect(() => {
    if (
      projectID &&
      state &&
      !state.projects.some((project) => project.id === projectID)
    )
      setProjectID("");
  }, [state, projectID]);

  async function connect(event: FormEvent) {
    event.preventDefault();
    setConnecting(true);
    setError("");
    try {
      const nextToken = entryToken.trim();
      const next = await request<DockState>(nextToken, "/api/state");
      tokenRef.current = nextToken;
      setToken(nextToken);
      setState(next);
      setEntryToken("");
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401
          ? t(
              "访问令牌无效，请使用本地服务提供的管理员令牌。",
              "Invalid token. Use the admin token supplied by your local service.",
            )
          : t(
              "无法连接本地服务。请检查服务地址和访问令牌。",
              "Cannot connect to the local service. Check its address and access token.",
            ),
      );
    } finally {
      setConnecting(false);
    }
  }

  const mutate: Mutate = async (path, data, success) => {
    if (demo || busy || mutationInFlight.current || !tokenRef.current)
      return false;
    const currentToken = tokenRef.current;
    mutationInFlight.current = true;
    // Ignore any polling response captured before this mutation began.
    stateEpoch.current += 1;
    setBusy(path);
    setError("");
    setNotice("");
    try {
      const result = await request<unknown>(currentToken, path, data);
      if (currentToken !== tokenRef.current) return false;
      try {
        const refreshed = await refresh();
        // Newly selected IDs must already exist in state, otherwise selection
        // reconciliation would move the user back to a previous project/session.
        if (refreshed) success?.(result);
      } catch {
        setError(
          t(
            "操作已提交，但最新状态读取失败；请刷新确认结果，勿重复提交。",
            "The action was submitted, but state refresh failed. Refresh before retrying.",
          ),
        );
      }
      return true;
    } catch (e) {
      if (
        e instanceof ApiError &&
        e.status === 409 &&
        errorMessage(e.message, t) === e.message
      )
        setError(
          t(
            "版本或状态发生冲突，操作未应用。已保留草稿；请刷新并核对最新记录。",
            "A version or state conflict prevented the action. Your draft is preserved; refresh and review the latest record.",
          ),
        );
      else
        setError(
          e instanceof Error
            ? errorMessage(e.message, t)
            : t("操作失败，请重试。", "The action failed. Please retry."),
        );
      return false;
    } finally {
      mutationInFlight.current = false;
      setBusy(null);
    }
  };

  async function manualRefresh() {
    if (busy) return;
    setBusy("refresh");
    setError("");
    try {
      await refresh();
      setNotice(
        t(
          "工作台状态已刷新。进入「额度与订阅」时会自动更新额度。",
          "Workspace refreshed. Opening Usage & billing updates quotas automatically.",
        ),
      );
    } catch {
      setError(
        t(
          "刷新失败，请检查本地服务。",
          "Refresh failed. Check the local service.",
        ),
      );
    } finally {
      setBusy(null);
    }
  }

  const languageButton = (
    <button
      className="language"
      onClick={() => setLang(lang === "zh" ? "en" : "zh")}
      aria-label={t("Switch to English", "切换为中文")}
    >
      {lang === "zh" ? "EN" : "中文"}
    </button>
  );
  if (!state || (!token && !demo))
    return (
      <div className="welcome-page">
        <header>
          <Brand />
          {languageButton}
        </header>
        <main className="welcome-main">
          <section className="welcome-copy">
            <span className="eyebrow">
              {t("本地 Agent 工作台", "LOCAL AGENT WORKSPACE")}
            </span>
            <h1>
              {t("一个工作台，", "One workspace.")}
              <br />
              <em>{t("连续的协作。", "Connected work.")}</em>
            </h1>
            <p>
              {t(
                "连接已安装的 Agent CLI，例如 Codex、Claude Code，管理会话、任务协作、共享记忆与可用额度。",
                "Connect installed agent CLIs such as Codex and Claude Code to manage conversations, collaboration, shared memory and usage.",
              )}
            </p>
            <div className="welcome-features">
              <span>
                <Icon name="message" />
                {t("连续的原生会话", "Persistent native sessions")}
              </span>
              <span>
                <Icon name="memory" />
                {t("可审阅的共享记忆", "Reviewed shared memory")}
              </span>
              <span>
                <Icon name="usage" />
                {t("额度与订阅", "Usage and billing")}
              </span>
            </div>
            <div className="preview-note">
              <Icon name="shield" />
              <p>
                {t(
                  "默认关闭执行。连接工作台不会启动任何 Agent，也不会读取远端额度。",
                  "Execution is disabled by default. Connecting does not start agents or fetch remote quotas.",
                )}
              </p>
            </div>
          </section>
          <section className="connection-card">
            <span className="step-label">{t("连接工作台", "CONNECT")}</span>
            <h2>{t("连接本地工作台", "Connect your local workspace")}</h2>
            <p>
              {t(
                "输入服务终端显示的管理员访问令牌。令牌只保存在此页面的内存中，刷新页面后需重新输入。",
                "Enter the admin access token shown by the local service. It stays in this page’s memory and is cleared when the page reloads.",
              )}
            </p>
            <form onSubmit={connect}>
              <label htmlFor="access-token">
                {t("访问令牌", "Access token")}
              </label>
              <input
                id="access-token"
                type="password"
                value={entryToken}
                onChange={(e) => setEntryToken(e.target.value)}
                autoComplete="off"
                spellCheck={false}
                required
                placeholder="••••••••••••••••••••••••"
              />
              <button
                className="primary full"
                disabled={connecting || !entryToken.trim()}
              >
                {connecting
                  ? t("正在连接…", "Connecting…")
                  : t("进入工作台", "Open workspace")}
                <Icon name="arrow" />
              </button>
            </form>
            {error && (
              <p className="inline-error" role="alert">
                {error}
              </p>
            )}
            <div className="connection-footer">
              <span className="status-dot" />
              {t("同源连接 · 本机服务", "Same-origin · Local service")}
            </div>
          </section>
        </main>
        <footer className="welcome-footer">
          AgentDock ·{" "}
          {t(
            "独立管理本机或 SSH 主机上的 Agent CLI 会话。",
            "Manage independent agent CLI sessions locally or over SSH.",
          )}
        </footer>
      </div>
    );

  const project = state.projects.find((p) => p.id === projectID);
  const agents = state.agents.filter(
    (a) => !projectID || a.project_id === projectID,
  );
  const sessions = state.sessions.filter(
    (s) => !projectID || s.project_id === projectID,
  );
  const proposals = state.proposals.filter(
    (p) => p.project_id === projectID && p.status === "pending",
  );
  const approvals = state.approvals.filter(
    (a) => (!projectID || a.project_id === projectID) && a.status === "pending",
  );
  const nav: {
    key: Tab;
    icon: string;
    zh: string;
    en: string;
    badge?: number;
  }[] = [
    {
      key: "workspace",
      icon: "work",
      zh: "协作工作台",
      en: "Workspace",
      badge: approvals.length,
    },
    { key: "messages", icon: "message", zh: "任务派工", en: "Dispatch" },
    {
      key: "memory",
      icon: "memory",
      zh: "共享记忆",
      en: "Shared memory",
      badge: proposals.length,
    },
    { key: "tokens", icon: "usage", zh: "Token 统计", en: "Token statistics" },
    { key: "usage", icon: "usage", zh: "额度与订阅", en: "Usage & billing" },
  ];

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">
        {t("跳至主要内容", "Skip to content")}
      </a>
      <aside className="sidebar">
        <Brand small />
        <div className="project-switch">
          <label htmlFor="project-select">{t("当前项目", "PROJECT")}</label>
          <select
            id="project-select"
            value={projectID}
            onChange={(e) => setProjectID(e.target.value)}
          >
            <option value="">{t("全部 Agent", "All agents")}</option>
            {state.projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <button
            className="sidebar-add"
            aria-expanded={projectForm}
            aria-controls="project-form"
            onClick={() => setProjectForm(!projectForm)}
          >
            <Icon name="plus" size={16} />
            {t("新建项目", "New project")}
          </button>
        </div>
        <nav aria-label={t("主导航", "Main navigation")}>
          {nav.map((item) => (
            <button
              key={item.key}
              className={tab === item.key ? "nav-item selected" : "nav-item"}
              onClick={() => {
                setTab(item.key);
                if (item.key === "usage") setUsageVisit((visit) => visit + 1);
              }}
              aria-label={t(item.zh, item.en)}
              aria-current={tab === item.key ? "page" : undefined}
            >
              <Icon name={item.icon} />
              <span>{t(item.zh, item.en)}</span>
              {!!item.badge && <span className="nav-badge">{item.badge}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-status">
            <span className="status-dot" />
            <div>
              {demo
                ? t("离线演示", "Offline demo")
                : t("本地服务已连接", "Local service connected")}
              <small>
                v{state.runtime.version} ·{" "}
                {demo
                  ? t("虚构数据 · 只读", "Fictional data · Read-only")
                  : t("数据存于本机", "Stored on this device")}
              </small>
            </div>
          </div>
          <button className="disconnect" onClick={disconnect}>
            {demo ? t("退出演示", "Exit demo") : t("断开连接", "Disconnect")}
          </button>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            {project?.name ?? "AgentDock"}
            <span>/</span>
            <strong>
              {t(
                nav.find((n) => n.key === tab)!.zh,
                nav.find((n) => n.key === tab)!.en,
              )}
            </strong>
          </div>
          <div className="top-actions">
            {languageButton}
            {tab !== "usage" && (
              <button
                className="icon-button"
                title={t("刷新工作台状态", "Refresh workspace state")}
                aria-label={t("刷新工作台状态", "Refresh workspace state")}
                onClick={manualRefresh}
                disabled={!!busy || demo}
              >
                <Icon name="refresh" />
              </button>
            )}
          </div>
        </header>
        <main id="main-content" className="main-content">
          <div
            className={`runtime-banner ${state.runtime.enabled ? "enabled" : ""}`}
          >
            <Icon name="shield" size={18} />
            <span>
              {demo
                ? t(
                    "演示模式 · 所有内容均为虚构示例，不连接本地服务、不运行 Agent、不读取额度。",
                    "Demo mode · Fictional examples only. No service connection, agent execution or quota fetching.",
                  )
                : state.runtime.enabled
                  ? t(
                      "执行已启用 · 任务会提交到原生会话，协作派工会自动执行并回传结果。",
                      "Execution enabled · Tasks use native sessions. Delegated work runs automatically and returns its result.",
                    )
                  : t(
                      "执行已关闭 · 可以查看记录、管理项目和共享记忆。运行、派工和额度读取暂不可用。",
                      "Execution disabled · Review records, manage projects and shared memory. Runs, dispatch and quota fetching are unavailable.",
                    )}
            </span>
          </div>
          {error && (
            <div className="alert error" role="alert">
              <span>{error}</span>
              <button
                className="icon-button"
                onClick={() => setError("")}
                aria-label={t("关闭错误提示", "Dismiss error")}
              >
                <Icon name="close" size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert success" role="status">
              {notice}
              <button
                className="icon-button"
                onClick={() => setNotice("")}
                aria-label={t("关闭提示", "Dismiss notice")}
              >
                <Icon name="close" size={16} />
              </button>
            </div>
          )}
          {projectForm && (
            <ProjectForm
              environments={state.environments ?? []}
              t={t}
              busy={!!busy || demo}
              mutate={mutate}
              close={() => setProjectForm(false)}
              onCreated={(id) => setProjectID(id)}
            />
          )}
          {!project && (tab === "memory" || tab === "messages") ? (
            <section className="panel">
              <Empty
                icon="work"
                title={t("选择项目以协作", "Choose a project to collaborate")}
              >
                {t(
                  "项目用于共享记忆和多 Agent 派工。独立对话无需项目，可直接在工作台创建 Agent。",
                  "Projects group shared memory and agent dispatch. Create an agent directly in Workspace to chat without a project.",
                )}
              </Empty>
              <button
                className="primary empty-action"
                aria-expanded={projectForm}
                aria-controls="project-form"
                onClick={() => setProjectForm(!projectForm)}
              >
                <Icon name="plus" size={18} />
                {t("创建第一个项目", "Create your first project")}
              </button>
            </section>
          ) : (
            <>
              {tab === "workspace" && (
                <Workspace
                  key={projectID}
                  t={t}
                  lang={lang}
                  metrics={metrics}
                  metricsFailed={metricsFailed}
                  project={project}
                  agents={agents}
                  sessions={sessions}
                  approvals={approvals}
                  state={state}
                  token={token}
                  demo={demo}
                  runtimeEnabled={state.runtime.enabled}
                  busy={!!busy || demo}
                  mutate={mutate}
                  initialEnvironment={agentEnvironment ?? undefined}
                  onInitialEnvironmentUsed={() => setAgentEnvironment(null)}
                />
              )}
              {tab === "messages" && project && (
                <Messages
                  key={projectID}
                  t={t}
                  lang={lang}
                  state={state}
                  projectID={projectID}
                  agents={agents}
                  busy={!!busy || demo}
                  mutate={mutate}
                />
              )}
              {tab === "memory" && project && (
                <Memories
                  key={projectID}
                  t={t}
                  lang={lang}
                  state={state}
                  projectID={projectID}
                  agents={agents}
                  proposals={proposals}
                  busy={!!busy || demo}
                  mutate={mutate}
                />
              )}
              {tab === "tokens" && (
                <Tokens
                  metrics={metrics}
                  failed={metricsFailed}
                  agents={state.agents}
                  t={t}
                  lang={lang}
                />
              )}
              {tab === "usage" && (
                <Usage
                  t={t}
                  lang={lang}
                  quotas={listOf(state.quotas)}
                  subscriptions={listOf(state.subscriptions)}
                  agents={state.agents}
                  onAddAgent={() => {
                    setProjectID("");
                    setProjectForm(false);
                    setAgentEnvironment("local");
                    setTab("workspace");
                  }}
                  refreshing={quotaRefreshing}
                  refreshFailed={quotaRefreshFailed}
                  busy={!!busy || demo}
                  mutate={mutate}
                />
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function ProjectForm({
  environments,
  t,
  busy,
  mutate,
  close,
  onCreated,
}: {
  t: Translate;
  busy: boolean;
  mutate: Mutate;
  close: () => void;
  onCreated: (id: string) => void;
  environments: Environment[];
}) {
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [environment, setEnvironment] = useState("local");
  return (
    <section className="panel inset-form" id="project-form">
      <div className="panel-heading">
        <h2>{t("新建项目", "New project")}</h2>
        <button
          className="icon-button"
          onClick={close}
          aria-label={t("取消新建项目", "Cancel new project")}
        >
          <Icon name="close" />
        </button>
      </div>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          await mutate(
            "/api/projects",
            {
              name: name.trim(),
              path: path.trim(),
              environment_id: environment,
            },
            (result) => {
              onCreated(result.id);
              close();
            },
          );
        }}
      >
        <label>
          {t("项目所在设备", "Project device")}
          <select
            value={environment}
            onChange={(e) => setEnvironment(e.target.value)}
          >
            <option value="local">{t("本机", "This Mac")}</option>
            {environments
              .filter((e) => e.kind === "ssh")
              .map((e) => (
                <option value={e.id} key={e.id}>
                  {e.name}
                </option>
              ))}
          </select>
        </label>
        <div className="form-grid">
          <label>
            {t("项目名称", "Project name")}
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={100}
              placeholder={t("例如：我的应用", "For example: My app")}
            />
          </label>
          <label>
            {t("工作目录（绝对路径）", "Workspace directory (absolute path)")}
            <input
              value={path}
              onChange={(e) => setPath(e.target.value)}
              required
              placeholder="/absolute/path/to/project"
              autoComplete="off"
            />
          </label>
        </div>
        <p className="form-hint">
          {t(
            "此目录将作为 Agent 的工作目录。请选择你信任的现有目录。",
            "Agents will use this working directory. Choose an existing directory you trust.",
          )}
        </p>
        <button
          className="primary"
          disabled={busy || !name.trim() || !path.trim()}
        >
          {t("创建项目", "Create project")}
        </button>
      </form>
    </section>
  );
}
