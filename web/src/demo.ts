import type { DockState, Language } from "./types";

/** Fictional, local-only fixtures. No real paths, credentials, accounts or model calls. */
export function demoState(lang: Language): DockState {
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const date = "2026-09-26T09:32:00Z";
  return {
    projects: [
      { id: "demo-project", name: "Orbit", path: "/demo/projects/orbit" },
    ],
    agents: [
      {
        id: "demo-codex",
        project_id: "demo-project",
        provider: "codex",
        name: "Agent A",
        role: "",
      },
      {
        id: "demo-claude",
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
        title: t("完善搜索体验", "Refine the search experience"),
        native_session_id: "demo-native-codex-01",
        status: "idle",
        created_at: date,
        updated_at: date,
      },
      {
        id: "demo-session-2",
        project_id: "demo-project",
        agent_id: "demo-codex",
        title: t("设置页可访问性", "Settings accessibility"),
        native_session_id: "demo-native-codex-02",
        status: "idle",
        created_at: date,
        updated_at: date,
      },
      {
        id: "demo-session-3",
        project_id: "demo-project",
        agent_id: "demo-claude",
        title: t("审阅搜索变更", "Review search changes"),
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
          "为搜索加入键盘导航，并补充相关测试。",
          "Add keyboard navigation to search and cover the behavior with tests.",
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
          "独立审阅键盘导航与焦点恢复。",
          "Independently review keyboard navigation and focus restoration.",
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
          "审阅结果：测试通过，可交付。",
          "Review result: tests pass and the change is ready.",
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
          "请审阅搜索的键盘导航变更，重点检查 Esc 关闭、焦点恢复以及空结果。",
          "Review search keyboard navigation, focusing on Escape, focus restoration and empty results.",
        ),
        result: t(
          "已检查 3 个边界场景，相关测试通过。焦点会回到触发按钮，未发现阻塞问题。",
          "Verified three edge cases and the related tests. Focus returns to the trigger; no blocking issues found.",
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
          "界面默认中文，提供完整英语切换。交互变更需覆盖键盘操作和焦点管理。",
          "Default to Chinese with full English switching. Cover keyboard interaction and focus management for UI changes.",
        ),
        version: 3,
        author: "human",
        source: t("项目约定", "Project conventions"),
        updated_at: date,
      },
      {
        id: "demo-memory-2",
        project_id: "demo-project",
        key: "search.behavior",
        content: t(
          "搜索结果保持稳定排序；Esc 关闭浮层后，焦点回到搜索入口。",
          "Keep search results in a stable order. Escape closes the overlay and restores focus to the search trigger.",
        ),
        version: 1,
        author: "human",
        source: t("已确认决策", "Reviewed decision"),
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
          "交互测试优先使用角色和可访问名称定位元素，覆盖键盘输入路径。",
          "Use roles and accessible names in interaction tests, including keyboard input paths.",
        ),
        expected_version: 0,
        status: "pending",
        created_at: date,
      },
    ],
    events: [
      {
        id: "demo-event-1",
        seq: 1,
        project_id: "demo-project",
        session_id: "demo-session-1",
        kind: "user_message",
        payload: {
          text: t(
            "为搜索加入键盘导航，沿用项目的可访问性约定。完成后请 Agent B 独立审阅。",
            "Add keyboard navigation to search following the project accessibility conventions. Ask Agent B for an independent review when ready.",
          ),
        },
        created_at: date,
      },
      {
        id: "demo-event-2",
        seq: 2,
        project_id: "demo-project",
        session_id: "demo-session-1",
        kind: "agent_message",
        payload: {
          text: t(
            "已完成键盘导航和焦点恢复。\n\n• ↑ / ↓ 在结果中移动，Enter 打开所选项\n• Esc 关闭搜索并恢复焦点\n• 空结果不会触发无效选择\n\n已将审阅任务派给 Agent B，沿用独立的审阅会话。",
            "Keyboard navigation and focus restoration are complete.\n\n• ↑ / ↓ move through results; Enter opens the selection\n• Escape closes search and restores focus\n• Empty results cannot trigger invalid selections\n\nThe review was dispatched to Agent B in its own review session.",
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
          text: t(
            "Agent A → Agent B · 审阅搜索变更",
            "Agent A → Agent B · Review search changes",
          ),
        },
        created_at: date,
      },
      {
        id: "demo-event-4",
        seq: 4,
        project_id: "demo-project",
        session_id: "demo-session-1",
        kind: "agent_message",
        payload: {
          text: t(
            "审阅结果已回传：3 个边界场景与相关测试均通过。变更已准备好供你查看。",
            "The review returned: all three edge cases and related tests pass. The change is ready for your review.",
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
            label: t("5 小时额度", "5-hour window"),
            remaining_percent: 78,
            reset_at: "2026-09-26T12:00:00Z",
          },
          {
            label: t("每周额度", "Weekly window"),
            remaining_percent: 64,
            reset_at: "2026-09-30T09:00:00Z",
          },
        ],
      },
      {
        provider: "claude",
        plan: "Max",
        status: "ok",
        source: "demo",
        fetched_at: date,
        windows: [
          {
            label: t("5 小时额度", "5-hour window"),
            remaining_percent: 52,
            reset_at: "2026-09-26T11:30:00Z",
          },
          {
            label: t("每周额度", "Weekly window"),
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
        plan: "Max",
        renewal_date: "2026-10-18",
        monthly_cost: null,
        currency: "USD",
      },
    ],
    runtime: { enabled: false, version: "0.2.0" },
  };
}
