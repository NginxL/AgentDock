export type Language = "zh" | "en";
export type Provider =
  | "codex"
  | "claude"
  | "trae"
  | "pi"
  | "cursor"
  | "antigravity"
  | "grok"
  | "opencode"
  | "gemini"
  | "qwen";
export type ProviderAvailability = Partial<
  Record<
    Provider,
    {
      available: boolean;
      reason?: string | null;
      supports_ask?: boolean;
    }
  >
>;
export type PermissionMode = "ask" | "full_access";
export type AccountPolicy = "manual" | "auto" | "failover";
export interface AccountSettings {
  account_id?: string | null;
  account_policy?: AccountPolicy;
  account_ids?: string[];
}
export interface Account extends AccountSettings {
  id: string;
  label: string;
  provider: "codex" | "claude";
  environment_id: string;
  status: "pending" | "ready" | "expired" | "cooldown" | "disabled" | "removed";
  generation?: number;
  priority?: number;
  enabled?: boolean;
  cooldown_until?: string | null;
  error?: string | null;
  identity?: {
    email?: string | null;
    plan?: string | null;
  } | null;
  usage?: {
    input_tokens?: number | null;
    output_tokens?: number | null;
    total_tokens?: number | null;
    updated_at?: number | string | null;
  } | null;
  quota?: {
    windows?: {
      name?: string;
      label?: string;
      remaining_percent?: number | null;
      reset_at?: string | null;
      duration_minutes?: number;
    }[];
    source?: string;
    status?: string;
    fetched_at?: string;
  } | null;
  created_at?: string;
  updated_at?: string;
}
export interface AccountAttempt {
  id: string;
  run_id: string;
  account_id?: string | null;
  status: string;
  number?: number;
  generation?: number;
  account_branch?: string | number;
  progress?: boolean;
  error_code?: string | null;
  finished_at?: string | null;
  reason?: string | null;
  error?: string | null;
  created_at: string;
}
export interface Environment {
  id: string;
  name: string;
  kind: "local" | "ssh";
  ssh_host?: string;
  python?: string;
  status: string;
  updated_at?: string;
  payload?: {
    providers?: Record<string, { available: boolean; version?: string }>;
  };
}
export interface Project {
  environment_id?: string;
  id: string;
  name: string;
  path: string;
}
export interface Agent extends AccountSettings {
  source_agent_id?: string | null;
  environment_id?: string;
  id: string;
  project_id: string | null;
  name: string;
  provider: Provider;
  role: string;
  workspace?: string;
  workspace_is_default?: boolean;
  model?: string | null;
  effort?: string | null;
  permission_mode?: PermissionMode;
}
export interface Session extends AccountSettings {
  work_task_id?: string | null;
  task_role?: string | null;
  task_intent?: string | null;
  account_branch?: string | number | null;
  agent_defaults?: {
    model?: string | null;
    effort?: string | null;
    permission_mode?: PermissionMode;
  } | null;
  model?: string | null;
  effort?: string | null;
  model_override?: boolean | 0 | 1;
  environment_id?: string;
  id: string;
  project_id: string | null;
  agent_id: string;
  title: string;
  native_session_id?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}
export interface Message {
  id: string;
  project_id: string;
  sender_id: string;
  recipient_id: string;
  body: string;
  created_at: string;
  correlation_id?: string;
  status?: string;
  sender_session_id?: string | null;
  recipient_session_id?: string | null;
  run_id?: string | null;
  reply_run_id?: string | null;
  result?: string | null;
  error?: string | null;
}
export interface Run extends AccountSettings {
  work_task_id?: string | null;
  task_role?: string | null;
  task_intent?: string | null;
  account_branch?: string | number | null;
  result?: string | null;
  id: string;
  session_id: string;
  agent_id: string;
  project_id: string | null;
  prompt: string;
  status: string;
  error?: string | null;
  origin: "human" | "delegate" | "reply";
  parent_run_id?: string | null;
  root_run_id?: string | null;
  task_run_id?: string | null;
  depth: number;
  delivery_id?: string | null;
  created_at: string;
  updated_at: string;
}
export interface Memory {
  id: string;
  project_id: string;
  key: string;
  content: string;
  version: number;
  status?: string;
  archived?: boolean | 0 | 1;
  archived_at?: string | null;
  author?: string;
  source?: string;
  updated_at?: string;
}
export interface Proposal {
  id: string;
  project_id: string;
  agent_id: string;
  key: string;
  content: string;
  expected_version: number;
  status: string;
  created_at: string;
}
export interface AgentEvent {
  seq: number;
  id: string;
  project_id: string | null;
  session_id: string;
  kind: string;
  payload: unknown;
  created_at: string;
}
export interface ApprovalOption {
  optionId: string;
  name: string;
  kind: string;
}
export interface Approval {
  id: string;
  project_id: string | null;
  session_id: string;
  run_id: string;
  request: unknown;
  options: ApprovalOption[];
  status: string;
  picked_option_id?: string;
  created_at: string;
}
export interface Quota {
  environment_id?: string;
  provider: Provider;
  plan?: string | null;
  windows: {
    label: string;
    remaining_percent?: number | null;
    reset_at?: string | null;
  }[];
  fetched_at?: string;
  status: string;
  error?: string;
  source: string;
  error_code?: string;
}
export interface Subscription {
  environment_id?: string;
  provider: string;
  plan: string;
  renewal_date: string | null;
  monthly_cost: number | null;
  currency: string;
}
export interface DockState {
  tasks?: ProjectTask[];
  task_questions?: TaskQuestion[];
  accounts?: Account[];
  account_attempts?: AccountAttempt[];
  environments?: Environment[];
  projects: Project[];
  agents: Agent[];
  sessions: Session[];
  messages: Message[];
  runs?: Run[];
  memories: Memory[];
  proposals: Proposal[];
  events: AgentEvent[];
  quotas: Quota[] | Record<string, Quota>;
  approvals: Approval[];
  subscriptions: Subscription[] | Record<string, Subscription>;
  runtime: { enabled: boolean; version: string };
}

export type TaskIntent = "record" | "discuss" | "develop";
export interface ProjectTask {
  id: string;
  project_id: string;
  title: string;
  goal: string;
  criteria: string;
  owner_id: string;
  session_id: string | null;
  status: string;
  intent: TaskIntent;
  acceptance_policy: "owner" | "human";
  review_required: boolean | number;
  workspace_mode: "shared" | "worktree";
  revision: number;
  delivery_id: string | null;
  source_session_id?: string | null;
  created_at: string;
  updated_at: string;
}
export interface TaskQuestion {
  id: string;
  task_id: string;
  run_id: string;
  question: string;
  options: string[];
  status: string;
  answer?: string | null;
  created_at: string;
}
export interface TaskDelivery {
  id: string;
  run_id: string;
  revision: number;
  summary: string;
  status: string;
  checks: {
    criterion: string;
    status: "passed" | "failed" | "unverified";
    evidence: string;
  }[];
  artifacts: string[];
  risks: string;
  created_at: string;
}
export interface TaskDetail extends ProjectTask {
  inputs: {
    id: string;
    body: string;
    intent: TaskIntent;
    action: string;
    status: string;
    created_at: string;
  }[];
  questions: TaskQuestion[];
  deliveries: TaskDelivery[];
  sessions: Session[];
  runs: Run[];
  reviews?: {
    id: string;
    run_id: string;
    revision: number;
    verdict: string;
    summary: string;
  }[];
  journal: {
    seq: number;
    kind: string;
    payload: Record<string, unknown>;
    created_at: string;
  }[];
  workspaces: {
    agent_id: string;
    environment_id: string;
    path: string;
    base_commit: string;
  }[];
  can_steer_run_id?: string | null;
}

export type Translate = (zh: string, en: string) => string;
export type Mutate = (
  path: string,
  data: unknown,
  success?: (result: any) => void,
) => Promise<boolean>;
