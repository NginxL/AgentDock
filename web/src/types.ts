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
export interface Agent {
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
export interface Session {
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
export interface Run {
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

export type Translate = (zh: string, en: string) => string;
export type Mutate = (
  path: string,
  data: unknown,
  success?: (result: any) => void,
) => Promise<boolean>;
