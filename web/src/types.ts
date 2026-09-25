export type Language = "zh" | "en";
export type Provider = "codex" | "claude";
export interface Project {
  id: string;
  name: string;
  path: string;
}
export interface Agent {
  id: string;
  project_id: string;
  name: string;
  provider: Provider;
  role: string;
}
export interface Session {
  id: string;
  project_id: string;
  agent_id: string;
  title: string;
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
  acknowledged_at?: string | null;
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
  project_id: string;
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
  project_id: string;
  session_id: string;
  run_id: string;
  request: unknown;
  options: ApprovalOption[];
  status: string;
  picked_option_id?: string;
  created_at: string;
}
export interface Quota {
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
}
export interface Subscription {
  provider: string;
  plan: string;
  renewal_date: string | null;
  monthly_cost: number | null;
  currency: string;
}
export interface DockState {
  projects: Project[];
  agents: Agent[];
  sessions: Session[];
  messages: Message[];
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
