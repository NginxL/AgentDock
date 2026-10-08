import * as uiMessages from "./messages";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ApiError, listOf, request } from "./api";
import { FeatureContext } from "./ExperimentalFeatures";
import DiagnosticExport from "./DiagnosticExport";
import { watchState } from "./stateStream";
import { useConnectionQueries } from "./queryClient";
import type {
  DockState,
  Account,
  Environment,
  Language,
  Mutate,
  Quota,
  Translate,
} from "./types";
import { Brand, Icon, errorMessage } from "./ui";
import { demoState } from "./demo";
import Workspace from "./views/Workspace";
import Conversations from "./views/Conversations";
import Tasks from "./views/Tasks";
import Memories from "./views/Memories";
import { ProjectHeader, ProjectList } from "./views/Projects";
const Usage = lazy(() => import("./views/Usage"));
const Tokens = lazy(() => import("./views/Tokens"));
const Accounts = lazy(() => import("./views/Accounts"));
import { useMetrics } from "./metrics";
import { clearModelCatalog, prewarmModels } from "./modelCatalog";
import { quotaRefreshTargets, usageTargets } from "./usageTargets";

import { useNavigation, type Tab } from "./navigation";

function newerAccount(candidate: Account, current: Account) {
  if (!candidate.updated_at || !current.updated_at) return false;
  const next = Date.parse(candidate.updated_at),
    previous = Date.parse(current.updated_at);
  if (!Number.isFinite(next) || !Number.isFinite(previous)) return false;
  if (next !== previous) return next > previous;
  // Account metadata uses microseconds; Date.parse alone would lose ordering
  // between a quota write and a disable operation in the same millisecond.
  const fraction = (value: string) =>
    (value.match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/)?.[1] ?? "")
      .padEnd(9, "0")
      .slice(3, 9);
  return fraction(candidate.updated_at) > fraction(current.updated_at);
}

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
  const queries = useConnectionQueries(token);
  const mutationInFlight = useRef(false);
  const stateEpoch = useRef(0);
  const quotaEpoch = useRef(0);
  const accountQuotaEpochs = useRef(new Map<string, number>());
  const [entryToken, setEntryToken] = useState("");
  const [state, setState] = useState<DockState | null>(() =>
    demo ? demoState("zh") : null,
  );
  const stateRef = useRef(state);
  stateRef.current = state;
  const { metrics, failed: metricsFailed } = useMetrics(
    token,
    demo,
    state?.agents.map((a) => a.id) ?? [],
  );
  const [connecting, setConnecting] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const {
    tab,
    projectID,
    projectView,
    agentID: agentPageID,
    sessionID: conversationID,
    taskID,
    navigate,
  } = useNavigation();
  const setTab = (tab: Tab) => {
    setProjectForm(false);
    navigate({
      tab,
      projectID: "",
      projectView: "tasks",
      agentID: "",
      taskID: "",
    });
  };
  const setProjectID = (nextProjectID: string) =>
    navigate({
      tab: "projects",
      projectID: nextProjectID,
      projectView: projectID ? projectView : "tasks",
      agentID: "",
      taskID: "",
    });
  const [usageVisit, setUsageVisit] = useState(0);
  const [quotaRefreshing, setQuotaRefreshing] = useState(false);
  const [quotaRefreshFailed, setQuotaRefreshFailed] = useState(false);
  const quotaRequest = useRef<AbortController | null>(null);
  const [projectForm, setProjectForm] = useState(false);
  const [agentEnvironment, setAgentEnvironment] = useState<string | null>(null);
  const desktopToken = useRef(window.__AGENTDOCK_DESKTOP_TOKEN__ ?? "");
  const modelConnections = JSON.stringify(
    (state?.agents ?? [])
      .filter((agent) => {
        if (
          agent.account_policy &&
          agent.account_policy !== "manual" &&
          !agent.account_id
        )
          return false;
        const environment = agent.environment_id ?? "local";
        return (
          environment === "local" ||
          state?.environments?.some(
            (e) => e.id === environment && e.status === "connected",
          )
        );
      })
      .map((agent) => ({
        provider: agent.provider,
        environment: agent.environment_id ?? "local",
        account: agent.account_id,
        generation: state?.accounts?.find((a) => a.id === agent.account_id)
          ?.generation,
      })),
  );
  const discoveryEnabled = !!token && !demo && !!state?.runtime?.enabled;
  useEffect(() => {
    if (!discoveryEnabled) return;
    const warm = () => {
      void prewarmModels(token, JSON.parse(modelConnections));
    };
    warm();
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "hidden") warm();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [token, discoveryEnabled, modelConnections]);

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
    clearModelCatalog();
    setDemo(false);
    tokenRef.current = "";
    stateEpoch.current += 1;
    setToken("");
    setEntryToken("");
    setState(null);
    navigate({ tab: "workspace", projectID: "", agentID: "" }, true);
    setNotice("");
    setError("");
  }, [navigate]);

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const currentToken = tokenRef.current;
      const currentEpoch = stateEpoch.current;
      const currentQuotaEpoch = quotaEpoch.current;
      if (!currentToken) return false;
      const since = stateRef.current?.version;
      if (signal?.aborted) return false;
      const snapshot = await queries.fetchQuery({
        queryKey: ["state", currentEpoch, since ?? null],
        gcTime: 0,
        queryFn: ({ signal: querySignal }) =>
          request<DockState>(
            currentToken,
            since
              ? `/api/state?since=${encodeURIComponent(since)}`
              : "/api/state",
            undefined,
            querySignal,
          ),
      });
      if (signal?.aborted) return false;
      if (
        currentToken !== tokenRef.current ||
        currentEpoch !== stateEpoch.current
      )
        return false;
      setState((current) => {
        if (current?.version && snapshot.version) {
          const [currentEpoch, currentRevision] = current.version.split(":");
          const [nextEpoch, nextRevision] = snapshot.version.split(":");
          if (
            currentEpoch === nextEpoch &&
            Number(nextRevision) <= Number(currentRevision)
          )
            return current;
        }
        const next =
          snapshot.partial && current ? { ...current, ...snapshot } : snapshot;
        return currentQuotaEpoch === quotaEpoch.current
          ? next
          : {
              ...next,
              quotas: current?.quotas ?? next.quotas,
              accounts: next.accounts?.map((account) => {
                const latest = current?.accounts?.find(
                  (a) => a.id === account.id,
                );
                if (
                  !latest ||
                  latest.generation !== account.generation ||
                  !newerAccount(latest, account) ||
                  (accountQuotaEpochs.current.get(account.id) ?? 0) <=
                    currentQuotaEpoch
                )
                  return account;
                return {
                  ...account,
                  updated_at: latest.updated_at,
                  quota: latest.quota,
                  identity: latest.identity,
                  status: latest.status,
                  cooldown_until: latest.cooldown_until,
                  error: latest.error,
                };
              }),
            };
      });
      return true;
    },
    [queries],
  );

  const canRefreshQuota = !demo && !!token && !!state?.runtime.enabled;

  const versionedState = !!state?.version;
  useEffect(() => {
    if (!token || demo || !versionedState) return;
    const controller = new AbortController();
    let inFlight = false;
    let pending = false;
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const update = async () => {
      if (controller.signal.aborted || document.visibilityState === "hidden")
        return;
      if (inFlight) {
        pending = true;
        return;
      }
      if (mutationInFlight.current) {
        clearTimeout(retry);
        retry = setTimeout(() => void update(), 250);
        return;
      }
      inFlight = true;
      try {
        await refresh(controller.signal);
      } catch {
        /* The bounded fallback poll reports connection errors. */
      } finally {
        inFlight = false;
        if (pending && !controller.signal.aborted) {
          pending = false;
          retry = setTimeout(() => void update(), 250);
        }
      }
    };
    const connect = () => {
      void watchState(token, controller.signal, (version) => {
        if (version !== stateRef.current?.version) void update();
      })
        .catch(() => {})
        .finally(() => {
          if (!controller.signal.aborted) reconnect = setTimeout(connect, 3000);
        });
    };
    connect();
    const visible = () => {
      if (document.visibilityState === "visible") void update();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      controller.abort();
      clearTimeout(reconnect);
      clearTimeout(retry);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [token, demo, versionedState, refresh]);

  useEffect(() => {
    setQuotaRefreshing(false);
    setQuotaRefreshFailed(false);
    return () => {
      quotaRequest.current?.abort();
      quotaRequest.current = null;
    };
  }, [token, canRefreshQuota]);

  const quotaTargets = JSON.stringify(
    quotaRefreshTargets(
      usageTargets(
        state?.agents ?? [],
        state?.sessions ?? [],
        state?.accounts ?? [],
      ),
    ).sort((a, b) => b.key.localeCompare(a.key)),
  );
  const refreshQuotas = useCallback(async () => {
    const targets: ReturnType<typeof quotaRefreshTargets> =
      JSON.parse(quotaTargets);
    if (!canRefreshQuota || !targets.length || quotaRequest.current) return;
    const credential = tokenRef.current;
    const controller = new AbortController();
    quotaRequest.current = controller;
    setQuotaRefreshing(true);
    setQuotaRefreshFailed(false);
    quotaEpoch.current += 1;
    try {
      const results = await Promise.allSettled(
        targets.map(
          async ({
            environment: environment_id,
            provider,
            accountID,
            generation,
          }) => {
            if (accountID) {
              const epoch = stateEpoch.current;
              const snapshot = await request<Account>(
                credential,
                `/api/accounts/${encodeURIComponent(accountID)}/refresh`,
                {},
                controller.signal,
              );
              if (
                snapshot.id !== accountID ||
                snapshot.provider !== provider ||
                snapshot.environment_id !== environment_id
              )
                throw new Error("Invalid account quota snapshot");
              if (
                controller.signal.aborted ||
                tokenRef.current !== credential ||
                epoch !== stateEpoch.current
              )
                return;
              quotaEpoch.current += 1;
              accountQuotaEpochs.current.set(accountID, quotaEpoch.current);
              setState(
                (current) =>
                  current && {
                    ...current,
                    accounts: current.accounts?.map((account) =>
                      account.id === accountID &&
                      account.generation === generation &&
                      account.status !== "removed" &&
                      !newerAccount(account, snapshot) &&
                      (account.status === snapshot.status ||
                        newerAccount(snapshot, account))
                        ? { ...account, ...snapshot }
                        : account,
                    ),
                  },
              );
              return;
            }
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
          },
        ),
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
  }, [canRefreshQuota, token, quotaTargets]);

  useEffect(() => {
    if (tab === "usage") void refreshQuotas();
  }, [tab, usageVisit, refreshQuotas]);

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    let inFlight = false;
    const interval = window.setInterval(
      async () => {
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
      },
      versionedState ? 60000 : 8000,
    );
    return () => {
      window.clearInterval(interval);
      controller.abort();
    };
  }, [token, refresh, disconnect, lang, versionedState]);

  useEffect(() => {
    if (
      projectID &&
      state &&
      !state.projects.some((project) => project.id === projectID)
    )
      navigate({ projectID: "", agentID: "" }, true);
  }, [state, projectID, navigate]);

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
              ...uiMessages.app_invalid_token_use_the_admin_token_supplied_by_46e52e,
            )
          : t(
              ...uiMessages.app_cannot_connect_to_the_local_service_check_its_af0391,
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
    await queries.cancelQueries({ queryKey: ["state"] });
    setBusy(path);
    setError("");
    setNotice("");
    try {
      const result = await request<unknown>(currentToken, path, data);
      if (currentToken !== tokenRef.current) return false;
      if (
        /^\/api\/environments\/[^/]+\/(connect|remove)$/.test(path) ||
        path.startsWith("/api/accounts")
      )
        clearModelCatalog();
      try {
        const refreshed = await refresh();
        // Newly selected IDs must already exist in state, otherwise selection
        // reconciliation would move the user back to a previous project/session.
        if (refreshed) success?.(result);
      } catch {
        setError(
          t(
            ...uiMessages.app_the_action_was_submitted_but_state_refresh_fa_4c37af,
          ),
        );
      }
      return true;
    } catch (e) {
      if (
        e instanceof ApiError &&
        e.status === 409 &&
        errorMessage(e.message, (zh) => zh) === e.message
      )
        setError(
          t(
            ...uiMessages.app_a_version_or_state_conflict_prevented_the_act_666e0a,
          ),
        );
      else
        setError(
          e instanceof Error
            ? errorMessage(e.message, t)
            : t(...uiMessages.app_the_action_failed_please_retry_6b599a),
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
          ...uiMessages.app_workspace_refreshed_opening_usage_billing_upd_4358c2,
        ),
      );
    } catch {
      setError(
        t(...uiMessages.app_refresh_failed_check_the_local_service_17422f),
      );
    } finally {
      setBusy(null);
    }
  }

  const languageButton = (
    <button
      className="language"
      onClick={() => setLang(lang === "zh" ? "en" : "zh")}
      aria-label={t(...uiMessages.app__d4d090)}
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
              {t(...uiMessages.app_local_agent_workspace_fd3b8b)}
            </span>
            <h1>
              {t(...uiMessages.app_one_workspace_659bb3)}
              <br />
              <em>{t(...uiMessages.app_connected_work_d41bc1)}</em>
            </h1>
            <p>
              {t(
                ...uiMessages.app_connect_installed_agent_clis_such_as_codex_an_002bed,
              )}
            </p>
            <div className="welcome-features">
              <span>
                <Icon name="message" />
                {t(...uiMessages.app_persistent_native_sessions_6960ed)}
              </span>
              <span>
                <Icon name="memory" />
                {t(...uiMessages.app_reviewed_shared_memory_5e2961)}
              </span>
              <span>
                <Icon name="usage" />
                {t(...uiMessages.app_usage_and_billing_cafc3c)}
              </span>
            </div>
            <div className="preview-note">
              <Icon name="shield" />
              <p>
                {t(
                  ...uiMessages.app_execution_is_disabled_by_default_connecting_d_29ea4f,
                )}
              </p>
            </div>
          </section>
          <section className="connection-card">
            <span className="step-label">
              {t(...uiMessages.app_connect_9ce0cd)}
            </span>
            <h2>{t(...uiMessages.app_connect_your_local_workspace_08a55a)}</h2>
            <p>
              {t(
                ...uiMessages.app_enter_the_admin_access_token_shown_by_the_loc_dd0d03,
              )}
            </p>
            <form onSubmit={connect}>
              <label htmlFor="access-token">
                {t(...uiMessages.app_access_token_96121b)}
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
                  ? t(...uiMessages.app_connecting_df2b48)
                  : t(...uiMessages.app_open_workspace_de5364)}
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
              {t(...uiMessages.app_same_origin_local_service_8eef00)}
            </div>
          </section>
        </main>
        <footer className="welcome-footer">
          AgentDock ·{" "}
          {t(
            ...uiMessages.app_manage_independent_agent_cli_sessions_locally_c2551e,
          )}
        </footer>
      </div>
    );

  const project = state.projects.find((p) => p.id === projectID);
  const pageAgent =
    tab === "workspace" || tab === "projects"
      ? state.agents.find((a) => a.id === agentPageID)
      : undefined;
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
    {
      key: "conversations",
      icon: "message",
      zh: "对话",
      en: "Conversations",
    },
    {
      key: "projects",
      icon: "folder",
      zh: "项目",
      en: "Projects",
      badge: state.proposals.filter((p) => p.status === "pending").length,
    },
    { key: "accounts", icon: "shield", zh: "账号", en: "Accounts" },
    { key: "tokens", icon: "usage", zh: "Token 统计", en: "Token statistics" },
    { key: "usage", icon: "usage", zh: "额度与订阅", en: "Usage & billing" },
  ];

  return (
    <FeatureContext.Provider value={state.runtime.features ?? {}}>
      <div className="shell">
        <a className="skip-link" href="#main-content">
          {t(...uiMessages.app_skip_to_content_d07c14)}
        </a>
        <aside className="sidebar">
          <Brand small />
          <nav aria-label={t(...uiMessages.app_main_navigation_790887)}>
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
                {!!item.badge && (
                  <span className="nav-badge">{item.badge}</span>
                )}
              </button>
            ))}
          </nav>
          <div className="sidebar-bottom">
            {!demo && (
              <DiagnosticExport token={token} t={t} onError={setError} />
            )}
            <div className="local-status">
              <span className="status-dot" />
              <div>
                {demo
                  ? t(...uiMessages.app_offline_demo_5b3dba)
                  : t(...uiMessages.app_ready_c06cf9)}
                <small>v{state.runtime.version}</small>
              </div>
            </div>
            {(demo || !desktopToken.current) && (
              <button className="disconnect" onClick={disconnect}>
                {demo
                  ? t(...uiMessages.app_exit_demo_59244d)
                  : t(...uiMessages.app_sign_out_39ac2d)}
              </button>
            )}
          </div>
        </aside>
        <div className="main-shell">
          <header className="topbar">
            <div className="breadcrumb">
              <span className="breadcrumb-brand">AgentDock</span>
              <span>/</span>
              {tab === "projects" && project ? (
                <>
                  <button
                    className="breadcrumb-page"
                    onClick={() => setTab("projects")}
                  >
                    {t(...uiMessages.app_projects_23574c)}
                  </button>
                  <span>/</span>
                  {pageAgent ? (
                    <button
                      className="breadcrumb-page"
                      onClick={() =>
                        navigate({ agentID: "", projectView: "agents" })
                      }
                    >
                      {project.name}
                    </button>
                  ) : (
                    <strong>{project.name}</strong>
                  )}
                </>
              ) : pageAgent ? (
                <button
                  className="breadcrumb-page"
                  aria-label={t(...uiMessages.app_back_to_workspace_0993b7)}
                  onClick={() => setTab("workspace")}
                >
                  {t(...uiMessages.app_workspace_e6f3d2)}
                </button>
              ) : (
                <strong>
                  {t(
                    nav.find((n) => n.key === tab)!.zh,
                    nav.find((n) => n.key === tab)!.en,
                  )}
                </strong>
              )}
              {pageAgent && (
                <>
                  <span>/</span>
                  <strong>{pageAgent.name}</strong>
                </>
              )}
            </div>
            <div className="top-actions">
              {languageButton}
              {tab !== "usage" && (
                <button
                  className="icon-button"
                  title={t(...uiMessages.app_refresh_workspace_state_1044ae)}
                  aria-label={t(
                    ...uiMessages.app_refresh_workspace_state_1044ae,
                  )}
                  onClick={manualRefresh}
                  disabled={!!busy || demo}
                >
                  <Icon name="refresh" />
                </button>
              )}
            </div>
          </header>
          <Suspense
            fallback={
              <p role="status">{t(...uiMessages.app_opening_166491)}</p>
            }
          >
            <main
              id="main-content"
              className={`main-content ${pageAgent || tab === "conversations" ? "agent-content" : ""}`}
            >
              {(demo || !state.runtime.enabled) && (
                <div
                  className={`runtime-banner ${state.runtime.enabled ? "enabled" : ""}`}
                >
                  <Icon name="shield" size={18} />
                  <span>
                    {demo
                      ? t(
                          ...uiMessages.app_demo_mode_fictional_examples_only_no_service_04fd71,
                        )
                      : t(
                          ...uiMessages.app_view_only_task_execution_is_not_enabled_49f09d,
                        )}
                  </span>
                </div>
              )}
              {error && (
                <div className="alert error" role="alert">
                  <span>{error}</span>
                  <button
                    className="icon-button"
                    onClick={() => setError("")}
                    aria-label={t(...uiMessages.app_dismiss_error_099758)}
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
                    aria-label={t(...uiMessages.app_dismiss_notice_d905ab)}
                  >
                    <Icon name="close" size={16} />
                  </button>
                </div>
              )}
              {tab === "conversations" && (
                <Conversations
                  state={state}
                  sessionID={conversationID}
                  token={token}
                  demo={demo}
                  busy={!!busy || demo}
                  mutate={mutate}
                  lang={lang}
                  t={t}
                  onSelect={(id) => navigate({ sessionID: id })}
                  onTask={(task) =>
                    navigate({
                      tab: "projects",
                      projectID: task.project_id,
                      projectView: "tasks",
                      taskID: task.id,
                      agentID: "",
                    })
                  }
                  onAgent={(id, projectID) =>
                    navigate({
                      tab: projectID ? "projects" : "workspace",
                      projectID: projectID ?? "",
                      projectView: "agents",
                      agentID: id,
                    })
                  }
                />
              )}
              {tab === "projects" && !pageAgent && (
                <ProjectHeader
                  onPolicy={(project) =>
                    void mutate(`/api/projects/${project.id}/policy`, {
                      confirm_dispatch: !project.confirm_dispatch,
                    })
                  }
                  busy={!!busy || demo}
                  project={project}
                  projects={state.projects}
                  view={projectView}
                  pending={proposals.length}
                  creating={projectForm}
                  onCreate={() => setProjectForm(!projectForm)}
                  onSelect={setProjectID}
                  onView={(view) =>
                    navigate({ projectView: view, agentID: "", taskID: "" })
                  }
                  t={t}
                />
              )}
              {projectForm && tab === "projects" && !project && (
                <ProjectForm
                  environments={state.environments ?? []}
                  t={t}
                  busy={!!busy || demo}
                  mutate={mutate}
                  close={() => setProjectForm(false)}
                  onCreated={(id) =>
                    navigate({
                      tab: "projects",
                      projectID: id,
                      projectView: "tasks",
                      agentID: "",
                    })
                  }
                />
              )}
              {tab === "projects" && !project && (
                <ProjectList
                  state={state}
                  t={t}
                  onSelect={setProjectID}
                  creating={projectForm}
                  onCreate={() => setProjectForm(!projectForm)}
                />
              )}
              {(tab === "workspace" ||
                (tab === "projects" &&
                  project &&
                  projectView === "agents")) && (
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
                  agentPageID={agentPageID}
                  onNavigateAgent={(id, replace) =>
                    navigate({ agentID: id }, replace)
                  }
                  initialEnvironment={agentEnvironment ?? undefined}
                  onInitialEnvironmentUsed={() => setAgentEnvironment(null)}
                  onConfigureAgent={() => {
                    setAgentEnvironment(project?.environment_id ?? "local");
                    navigate({
                      tab: "workspace",
                      projectID: "",
                      projectView: "agents",
                      agentID: "",
                    });
                  }}
                />
              )}
              {tab === "projects" && project && projectView === "tasks" && (
                <Tasks
                  key={projectID}
                  t={t}
                  lang={lang}
                  state={state}
                  projectID={projectID}
                  taskID={taskID}
                  onSelect={(id) => navigate({ taskID: id })}
                  token={token}
                  demo={demo}
                  busy={!!busy || demo}
                  mutate={mutate}
                />
              )}
              {tab === "projects" && project && projectView === "memory" && (
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
              {tab === "accounts" && (
                <Accounts
                  state={state}
                  token={token}
                  busy={!!busy || demo}
                  mutate={mutate}
                  onChanged={() => {
                    void refresh().catch(() => {});
                  }}
                  t={t}
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
                  sessions={state.sessions}
                  accounts={state.accounts ?? []}
                  environments={state.environments ?? []}
                  onAddAgent={() => {
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
            </main>
          </Suspense>
        </div>
      </div>
    </FeatureContext.Provider>
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
        <h2>{t(...uiMessages.app_new_project_213635)}</h2>
        <button
          className="icon-button"
          onClick={close}
          aria-label={t(...uiMessages.app_cancel_new_project_4db663)}
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
          {t(...uiMessages.app_project_device_5437ee)}
          <select
            value={environment}
            onChange={(e) => setEnvironment(e.target.value)}
          >
            <option value="local">
              {t(...uiMessages.app_this_mac_e21573)}
            </option>
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
            {t(...uiMessages.app_project_name_035ea1)}
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={100}
              placeholder={t(...uiMessages.app_for_example_my_app_ea87ba)}
            />
          </label>
          <label>
            {t(...uiMessages.app_workspace_directory_absolute_path_2f9bd8)}
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
            ...uiMessages.app_agents_will_use_this_working_directory_choose_2bfa39,
          )}
        </p>
        <button
          className="primary"
          disabled={busy || !name.trim() || !path.trim()}
        >
          {t(...uiMessages.app_create_project_3075b5)}
        </button>
      </form>
    </section>
  );
}
