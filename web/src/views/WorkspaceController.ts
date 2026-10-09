import { useDraft } from "../useDraft";
import { useEffect, useRef, useState } from "react";
import { deviceAccount } from "../AccountSelection";
import {
  NEW_SSH_CONNECTION,
  type SSHConnectionDraft,
} from "../AgentConnection";
import { type Metrics } from "../metrics";
import { useModelCatalog } from "../modelCatalog";
import { useProviderAvailability } from "../providerAvailability";
import { followSession } from "../sessionEvents";
import type {
  AccountSettings,
  Agent,
  AgentEvent,
  Approval,
  DockState,
  Language,
  Mutate,
  PermissionMode,
  Project,
  Provider,
  Session,
  Translate,
} from "../types";
export function useWorkspaceController({
  t,
  lang,
  project,
  metrics,
  metricsFailed,
  agents,
  sessions,
  approvals,
  state,
  token,
  demo = false,
  runtimeEnabled,
  busy,
  mutate,
  agentPageID,
  onNavigateAgent,
  initialEnvironment,
  onInitialEnvironmentUsed,
  onConfigureAgent,
  conversationOnly = false,
  sessionPageID,
}: {
  t: Translate;
  lang: Language;
  project?: Project;
  metrics?: Metrics | null;
  metricsFailed?: boolean;
  agents: Agent[];
  sessions: Session[];
  approvals: Approval[];
  state: DockState;
  token: string;
  demo?: boolean;
  runtimeEnabled: boolean;
  busy: boolean;
  mutate: Mutate;
  agentPageID?: string;
  onNavigateAgent?: (id: string, replace?: boolean) => void;
  initialEnvironment?: string;
  onInitialEnvironmentUsed?: () => void;
  onConfigureAgent?: () => void;
  conversationOnly?: boolean;
  sessionPageID?: string;
}) {
  const [agentForm, setAgentForm] = useState(initialEnvironment !== undefined);
  const [projectAgentForm, setProjectAgentForm] = useState(false);
  const draftTarget = useRef<string | null>(
    initialEnvironment !== undefined ? "new" : null,
  );
  const draft = useDraft({
    editingAgentID: null as string | null,
    agentName: "",
    provider: "codex" as Provider,
    environment: initialEnvironment ?? project?.environment_id ?? "local",
    role: "",
    workspace: "",
    agentProject: project?.id ?? "",
    model: "",
    effort: "",
    runTimeout: "",
    accountDraft: deviceAccount as AccountSettings,
    permissionMode: "ask" as PermissionMode,
  });
  const {
    editingAgentID,
    agentName,
    provider,
    environment,
    role,
    workspace,
    agentProject,
    model,
    effort,
    runTimeout,
    accountDraft,
    permissionMode,
  } = draft.values;
  const setEditingAgentID = draft.set("editingAgentID");
  const setAgentName = draft.set("agentName");
  const setProvider = draft.set("provider");
  const setEnvironment = draft.set("environment");
  const setRole = draft.set("role");
  const setWorkspace = draft.set("workspace");
  const setAgentProject = draft.set("agentProject");
  const setModel = draft.set("model");
  const setEffort = draft.set("effort");
  const setRunTimeout = draft.set("runTimeout");
  const setAccountDraft = draft.set("accountDraft");
  const setPermissionMode = draft.set("permissionMode");

  const [connectionDraft, setConnectionDraft] = useState<SSHConnectionDraft>({
    host: "",
    python: "python3",
    previous: environment,
  });
  useEffect(() => {
    if (initialEnvironment !== undefined) onInitialEnvironmentUsed?.();
  }, [initialEnvironment, onInitialEnvironmentUsed]);
  const selectedConnection = state.environments?.find(
    (e) => e.id === environment,
  );
  const connectionReady =
    environment === "local" || selectedConnection?.status === "connected";
  const connectionVersion = selectedConnection?.updated_at;

  const discovery = useProviderAvailability(
    token,
    environment,
    agentForm && environment !== NEW_SSH_CONNECTION,
    demo,
    connectionVersion,
  );
  const selectedAvailable = discovery.providers?.[provider]?.available === true;
  const catalog = useModelCatalog(
    token,
    provider,
    environment,
    agentForm &&
      !demo &&
      (accountDraft.account_policy === "manual" || !!accountDraft.account_id) &&
      runtimeEnabled &&
      selectedAvailable &&
      connectionReady &&
      environment !== NEW_SSH_CONNECTION,
    connectionVersion,
    accountDraft.account_id,
    state.accounts?.find((account) => account.id === accountDraft.account_id)
      ?.generation,
  );
  const models = demo
    ? [
        {
          id: "demo-model",
          name: "Demo model",
          efforts: ["low", "medium", "high"],
        },
      ]
    : catalog.models;
  const catalogError = catalog.failed;
  const catalogLoading = catalog.loading;
  const [internalAgentID, setInternalAgentID] = useState("");
  const agentID = agentPageID ?? internalAgentID;
  function setAgentID(id: string, replace = false) {
    if (onNavigateAgent) onNavigateAgent(id, replace);
    else setInternalAgentID(id);
  }
  const [sessionSelections, setSessionSelections] = useState<
    Record<string, string>
  >({});
  const relevantSessions = sessions.filter((s) => s.agent_id === agentID);
  const sessionID =
    sessionPageID !== undefined
      ? relevantSessions.some((s) => s.id === sessionPageID)
        ? sessionPageID
        : ""
      : relevantSessions.some((s) => s.id === sessionSelections[agentID])
        ? sessionSelections[agentID]
        : (relevantSessions[0]?.id ?? "");
  function setSessionID(id: string) {
    setSessionSelections((current) => ({ ...current, [agentID]: id }));
  }
  const [sessionTitle, setSessionTitle] = useState("");
  const [accountSelectionRequest, setAccountSelectionRequest] = useState(0);
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const prompt = prompts[sessionID] ?? "";
  function setPrompt(value: string) {
    setPrompts((current) => ({ ...current, [sessionID]: value }));
  }
  const pageTitle = useRef<HTMLHeadingElement>(null);
  const previousAgent = useRef(agentID);
  const submittingPrompt = useRef(false);
  const composingPrompt = useRef(false);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [eventError, setEventError] = useState("");
  const [eventLoading, setEventLoading] = useState(false);
  const selectedSession = relevantSessions.find((s) => s.id === sessionID);
  const selectedAgent = agents.find((a) => a.id === agentID);
  const editingAgent = agents.find((a) => a.id === editingAgentID);
  const selectedProject = state.projects.find((p) => p.id === agentProject);
  const projectDirectory =
    selectedProject &&
    !workspace &&
    (selectedProject.environment_id ?? "local") === environment
      ? selectedProject.path
      : undefined;
  const changingEnvironment =
    !!editingAgent && environment !== (editingAgent.environment_id ?? "local");
  const running = selectedSession?.status === "running";
  const sessionRuns = (state.runs ?? []).filter(
    (run) => run.session_id === sessionID,
  );
  const activeRuns = sessionRuns.filter((run) =>
    ["queued", "running"].includes(run.status),
  );
  const pendingDeliveries = state.messages.filter((message) => {
    if (!sessionID) return false;
    const reply = (state.runs ?? []).find(
      (run) => run.id === message.reply_run_id,
    );
    return (
      (message.recipient_session_id === sessionID &&
        message.status === "waiting") ||
      (message.sender_session_id === sessionID &&
        (["queued", "running", "waiting"].includes(message.status ?? "") ||
          (reply && ["queued", "running"].includes(reply.status))))
    );
  });
  const hasSessionTasks =
    running ||
    selectedSession?.status === "waiting" ||
    activeRuns.length > 0 ||
    pendingDeliveries.length > 0;
  useEffect(() => {
    if (agentID && !agents.some((a) => a.id === agentID)) setAgentID("", true);
  }, [agents, agentID]);
  useEffect(() => {
    if (previousAgent.current === agentID) return;
    previousAgent.current = agentID;
    setAgentForm(false);
    setProjectAgentForm(false);
    setEditingAgentID(null);
    draftTarget.current = null;
    setSessionTitle("");
    composingPrompt.current = false;
    pageTitle.current?.focus({ preventScroll: true });
  }, [agentID]);
  useEffect(() => {
    setEvents([]);
    setEventError("");
    if (demo) {
      setEvents(
        (state.events ?? []).filter((event) => event.session_id === sessionID),
      );
      setEventLoading(false);
      return;
    }
    if (!sessionID) {
      setEventLoading(false);
      return;
    }
    const controller = new AbortController();
    setEventLoading(true);
    void followSession(
      token,
      sessionID,
      controller.signal,
      (incoming) => {
        setEvents((previous) => {
          const seen = new Set(previous.map((event) => event.id));
          return [
            ...previous,
            ...incoming.filter((event) => !seen.has(event.id)),
          ];
        });
      },
      (failed) => {
        if (controller.signal.aborted) return;
        setEventLoading(false);
        setEventError(
          failed
            ? lang === "zh"
              ? "事件连接中断，正在重连。"
              : "Event connection interrupted. Reconnecting."
            : "",
        );
      },
    );
    return () => controller.abort();
  }, [sessionID, token, lang, demo, demo ? state.events : null]);

  const Heading: "h1" | "h2" = project && !selectedAgent ? "h2" : "h1";

  return {
    t,
    lang,
    project,
    metrics,
    metricsFailed,
    agents,
    sessions,
    approvals,
    state,
    token,
    demo,
    runtimeEnabled,
    busy,
    mutate,
    agentPageID,
    onNavigateAgent,
    initialEnvironment,
    onInitialEnvironmentUsed,
    onConfigureAgent,
    conversationOnly,
    sessionPageID,
    agentForm,
    setAgentForm,
    projectAgentForm,
    setProjectAgentForm,
    draftTarget,
    editingAgentID,
    setEditingAgentID,
    agentName,
    setAgentName,
    provider,
    setProvider,
    environment,
    setEnvironment,
    connectionDraft,
    setConnectionDraft,
    selectedConnection,
    connectionReady,
    connectionVersion,
    role,
    setRole,
    workspace,
    setWorkspace,
    agentProject,
    setAgentProject,
    model,
    setModel,
    effort,
    setEffort,
    runTimeout,
    setRunTimeout,
    accountDraft,
    setAccountDraft,
    permissionMode,
    setPermissionMode,
    discovery,
    selectedAvailable,
    catalog,
    models,
    catalogError,
    catalogLoading,
    internalAgentID,
    setInternalAgentID,
    agentID,
    setAgentID,
    sessionSelections,
    setSessionSelections,
    relevantSessions,
    sessionID,
    setSessionID,
    sessionTitle,
    setSessionTitle,
    accountSelectionRequest,
    setAccountSelectionRequest,
    prompts,
    setPrompts,
    prompt,
    setPrompt,
    pageTitle,
    previousAgent,
    submittingPrompt,
    composingPrompt,
    events,
    setEvents,
    eventError,
    setEventError,
    eventLoading,
    setEventLoading,
    selectedSession,
    selectedAgent,
    editingAgent,
    selectedProject,
    projectDirectory,
    changingEnvironment,
    running,
    sessionRuns,
    activeRuns,
    pendingDeliveries,
    hasSessionTasks,
    Heading,
  };
}
export type WorkspaceView = ReturnType<typeof useWorkspaceController>;
