import * as uiMessages from "./messages";
import type { DockState, Language } from "./types";

/** Fictional, local-only fixtures. No real paths, credentials, accounts or model calls. */
export function demoState(lang: Language): DockState {
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const date = "2026-09-26T09:32:00Z";
  return {
    environments: [
      { id: "local", name: "This Mac", kind: "local", status: "connected" },
      {
        id: "demo-remote",
        name: "Devbox",
        kind: "ssh",
        ssh_host: "developer@devbox.example",
        status: "connected",
        payload: {
          providers: {
            codex: { available: true, version: "codex-cli" },
            claude: { available: true, version: "Claude Code" },
          },
        },
      },
    ],
    projects: [
      { id: "demo-project", name: "Orbit", path: "/demo/projects/orbit" },
    ],
    agents: [
      {
        id: "demo-codex",
        project_id: "demo-project",
        provider: "codex",
        name: "Agent A",
        model: "example-model",
        effort: "high",
        role: "",
      },
      {
        id: "demo-claude",
        environment_id: "demo-remote",
        project_id: "demo-project",
        provider: "claude",
        name: "Agent B",
        role: "",
      },
    ],
    sessions: [
      {
        id: "demo-session-1",
        project_id: "demo-project",
        agent_id: "demo-codex",
        title: t(...uiMessages.demo_refine_the_search_experience_dea2e3),
        native_session_id: "demo-native-codex-01",
        status: "idle",
        created_at: date,
        updated_at: date,
      },
      {
        id: "demo-session-2",
        project_id: "demo-project",
        agent_id: "demo-codex",
        title: t(...uiMessages.demo_settings_accessibility_cda5ed),
        native_session_id: "demo-native-codex-02",
        status: "idle",
        created_at: date,
        updated_at: date,
      },
      {
        id: "demo-session-3",
        project_id: "demo-project",
        agent_id: "demo-claude",
        title: t(...uiMessages.demo_review_search_changes_e9da7e),
        native_session_id: "demo-native-claude-01",
        status: "idle",
        created_at: date,
        updated_at: date,
      },
    ],
    runs: [
      {
        id: "demo-run-1",
        session_id: "demo-session-1",
        agent_id: "demo-codex",
        project_id: "demo-project",
        prompt: t(
          ...uiMessages.demo_add_keyboard_navigation_to_search_and_cover_t_445903,
        ),
        status: "completed",
        origin: "human",
        root_run_id: "demo-run-1",
        depth: 0,
        created_at: date,
        updated_at: date,
      },
      {
        id: "demo-run-2",
        session_id: "demo-session-3",
        agent_id: "demo-claude",
        project_id: "demo-project",
        prompt: t(
          ...uiMessages.demo_independently_review_keyboard_navigation_and_d7b8da,
        ),
        status: "completed",
        origin: "delegate",
        root_run_id: "demo-run-1",
        parent_run_id: "demo-run-1",
        depth: 1,
        delivery_id: "demo-delivery-1",
        created_at: date,
        updated_at: date,
      },
      {
        id: "demo-run-3",
        session_id: "demo-session-1",
        agent_id: "demo-codex",
        project_id: "demo-project",
        prompt: t(
          ...uiMessages.demo_review_result_tests_pass_and_the_change_is_re_ae8930,
        ),
        status: "completed",
        origin: "reply",
        root_run_id: "demo-run-1",
        parent_run_id: "demo-run-2",
        depth: 2,
        delivery_id: "demo-delivery-1",
        created_at: date,
        updated_at: date,
      },
    ],
    messages: [
      {
        id: "demo-delivery-1",
        project_id: "demo-project",
        sender_id: "demo-codex",
        recipient_id: "demo-claude",
        sender_session_id: "demo-session-1",
        recipient_session_id: "demo-session-3",
        run_id: "demo-run-2",
        reply_run_id: "demo-run-3",
        status: "completed",
        body: t(
          ...uiMessages.demo_review_search_keyboard_navigation_focusing_on_5cdfde,
        ),
        result: t(
          ...uiMessages.demo_verified_three_edge_cases_and_the_related_tes_abef4f,
        ),
        correlation_id: "SEARCH-24",
        created_at: date,
      },
    ],
    memories: [
      {
        id: "demo-memory-1",
        project_id: "demo-project",
        key: "project.conventions",
        content: t(
          ...uiMessages.demo_default_to_chinese_with_full_english_switchin_264ee0,
        ),
        version: 3,
        author: "human",
        source: t(...uiMessages.demo_project_conventions_8c752f),
        updated_at: date,
      },
      {
        id: "demo-memory-2",
        project_id: "demo-project",
        key: "search.behavior",
        content: t(
          ...uiMessages.demo_keep_search_results_in_a_stable_order_escape_5c54a5,
        ),
        version: 1,
        author: "human",
        source: t(...uiMessages.demo_reviewed_decision_786d66),
        updated_at: date,
      },
    ],
    proposals: [
      {
        id: "demo-proposal-1",
        project_id: "demo-project",
        agent_id: "demo-claude",
        key: "testing.accessibility",
        content: t(
          ...uiMessages.demo_use_roles_and_accessible_names_in_interaction_f571a8,
        ),
        expected_version: 0,
        status: "pending",
        created_at: date,
      },
    ],
    events: [
      {
        id: "demo-model-info",
        seq: 0,
        project_id: "demo-project",
        session_id: "demo-session-1",
        kind: "model_info",
        created_at: date,
        payload: {
          run_id: "demo-run-1",
          native_id: "demo-native",
          model: "example-model",
          effort: "high",
        },
      },
      {
        id: "demo-thought",
        seq: 0,
        project_id: "demo-project",
        session_id: "demo-session-1",
        kind: "reasoning_message",
        payload: {
          run_id: "demo-run-1",
          item_id: "thought",
          part: 0,
          text: t(
            ...uiMessages.demo_check_keyboard_events_and_focus_handling_in_t_e6271e,
          ),
        },
        created_at: date,
      },
      {
        id: "demo-tool",
        seq: 0,
        project_id: "demo-project",
        session_id: "demo-session-1",
        kind: "tool_result",
        payload: {
          run_id: "demo-run-1",
          item: {
            id: "tool-1",
            type: "commandExecution",
            command: "npm test -- search",
            status: "completed",
            exitCode: 0,
            aggregatedOutput: t(
              ...uiMessages.demo_test_files_1_passed_tests_8_passed_6d56e7,
            ),
          },
        },
        created_at: date,
      },

      {
        id: "demo-event-1",
        seq: 1,
        project_id: "demo-project",
        session_id: "demo-session-1",
        kind: "user_message",
        payload: {
          run_id: "demo-run-1",
          text: t(
            ...uiMessages.demo_add_keyboard_navigation_to_search_following_t_8a0042,
          ),
        },
        created_at: date,
      },
      {
        id: "demo-event-2",
        seq: 2,
        project_id: "demo-project",
        session_id: "demo-session-1",
        kind: "assistant_message",
        payload: {
          run_id: "demo-run-1",
          text: t(
            ...uiMessages.demo_keyboard_navigation_and_focus_restoration_are_a352eb,
          ),
        },
        created_at: date,
      },
      {
        id: "demo-event-3",
        seq: 3,
        project_id: "demo-project",
        session_id: "demo-session-1",
        kind: "message_sent",
        payload: {
          run_id: "demo-run-1",
          text: t(
            ...uiMessages.demo_agent_a_agent_b_review_search_changes_00d14d,
          ),
        },
        created_at: date,
      },
      {
        id: "demo-event-4",
        seq: 4,
        project_id: "demo-project",
        session_id: "demo-session-1",
        kind: "assistant_message",
        payload: {
          run_id: "demo-run-3",
          text: t(
            ...uiMessages.demo_the_review_returned_all_three_edge_cases_and_d565a7,
          ),
        },
        created_at: date,
      },
    ],
    quotas: [
      {
        provider: "codex",
        plan: "Pro",
        status: "ok",
        source: "demo",
        fetched_at: date,
        windows: [
          {
            label: t(...uiMessages.demo_5_hour_window_d8f429),
            remaining_percent: 78,
            reset_at: "2026-09-26T12:00:00Z",
          },
          {
            label: t(...uiMessages.demo_weekly_window_d98769),
            remaining_percent: 64,
            reset_at: "2026-09-30T09:00:00Z",
          },
        ],
      },
      {
        provider: "claude",
        environment_id: "demo-remote",
        plan: "Max",
        status: "ok",
        source: "demo",
        fetched_at: date,
        windows: [
          {
            label: t(...uiMessages.demo_5_hour_window_d8f429),
            remaining_percent: 52,
            reset_at: "2026-09-26T11:30:00Z",
          },
          {
            label: t(...uiMessages.demo_weekly_window_d98769),
            remaining_percent: 83,
            reset_at: "2026-10-01T09:00:00Z",
          },
        ],
      },
    ],
    approvals: [],
    subscriptions: [
      {
        provider: "codex",
        plan: "Pro",
        renewal_date: "2026-10-12",
        monthly_cost: null,
        currency: "USD",
      },
      {
        provider: "claude",
        environment_id: "demo-remote",
        plan: "Max",
        renewal_date: "2026-10-18",
        monthly_cost: null,
        currency: "USD",
      },
    ],
    runtime: { enabled: false, version: "0.3.0" },
  };
}
