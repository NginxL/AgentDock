import { useState } from "react";
import type {
  Agent,
  DockState,
  Language,
  Mutate,
  Proposal,
  Translate,
} from "../types";
import { DateText, Empty, Icon, PageTitle, isArchived } from "../ui";

export default function Memories({
  t,
  lang,
  state,
  projectID,
  agents,
  proposals,
  busy,
  mutate,
}: {
  t: Translate;
  lang: Language;
  state: DockState;
  projectID: string;
  agents: Agent[];
  proposals: Proposal[];
  busy: boolean;
  mutate: Mutate;
}) {
  const [query, setQuery] = useState("");
  const [archived, setArchived] = useState(false);
  const [editor, setEditor] = useState<{
    key: string;
    content: string;
    version: number;
    id?: string;
  } | null>(null);
  const records = state.memories.filter(
    (m) =>
      m.project_id === projectID &&
      !!isArchived(m) === archived &&
      `${m.key} ${m.content}`
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase()),
  );
  const editorLatest = editor?.id
    ? state.memories.find((m) => m.id === editor.id)
    : undefined;
  const changed = !!editorLatest && editorLatest.version !== editor?.version;
  return (
    <>
      <PageTitle
        eyebrow={t("项目知识", "PROJECT KNOWLEDGE")}
        title={t("共享记忆", "Shared memory")}
        description={t(
          "仅共享已确认的项目约定与结论。各 Agent 的原生会话历史独立保留；记忆写入需经审阅，并按版本更新。",
          "Share reviewed project conventions and decisions. Native session histories remain private; memory changes are reviewed and versioned.",
        )}
        action={
          <button
            className="primary"
            aria-expanded={!!editor && !editor.id}
            aria-controls="memory-form"
            onClick={() =>
              setEditor(
                editor && !editor.id
                  ? null
                  : { key: "", content: "", version: 0 },
              )
            }
          >
            <Icon name="plus" size={18} />
            {t("新增记忆", "Add memory")}
          </button>
        }
      />
      {!!proposals.length && (
        <section className="panel proposals">
          <div className="panel-heading">
            <div>
              <h2>{t("等待审阅的提案", "Proposals awaiting review")}</h2>
              <p>
                {t(
                  "批准后才进入共享上下文。",
                  "Only approved content enters shared context.",
                )}
              </p>
            </div>
            <span className="count-badge">{proposals.length}</span>
          </div>
          {proposals.map((proposal) => {
            const current = state.memories.find(
              (m) => m.project_id === projectID && m.key === proposal.key,
            );
            const conflict =
              (current?.version ?? 0) !== proposal.expected_version;
            return (
              <article className="proposal" key={proposal.id}>
                <div className="record-heading">
                  <h3>{proposal.key}</h3>
                  <span className="pill">
                    {agents.find((a) => a.id === proposal.agent_id)?.name ??
                      "Agent"}{" "}
                    · v{proposal.expected_version} → v
                    {proposal.expected_version + 1}
                  </span>
                </div>
                {current && (
                  <details>
                    <summary>
                      {t("查看当前记忆", "View current memory")}
                    </summary>
                    <pre>{current.content}</pre>
                  </details>
                )}
                <pre>{proposal.content}</pre>
                {conflict && (
                  <p className="inline-error">
                    {t(
                      "原记忆版本已变化。此提案不能直接批准，请让 Agent 基于最新版本重新提案。",
                      "The memory version changed. Ask the agent for a proposal based on the latest version before approving.",
                    )}
                  </p>
                )}
                <div className="button-row">
                  <button
                    className="primary"
                    disabled={busy || conflict}
                    onClick={() =>
                      void mutate(
                        `/api/proposals/${encodeURIComponent(proposal.id)}/approve`,
                        { expected_version: proposal.expected_version },
                      )
                    }
                  >
                    {t("批准写入", "Approve memory")}
                  </button>
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      void mutate(
                        `/api/proposals/${encodeURIComponent(proposal.id)}/reject`,
                        {},
                      )
                    }
                  >
                    {t("拒绝提案", "Reject proposal")}
                  </button>
                </div>
              </article>
            );
          })}
        </section>
      )}
      {editor && (
        <section className="panel inset-form" id="memory-form">
          <div className="panel-heading">
            <h2>
              {editor.id
                ? t("编辑记忆", "Edit memory")
                : t("新增已审阅记忆", "Add reviewed memory")}
            </h2>
            <button
              className="icon-button"
              onClick={() => setEditor(null)}
              aria-label={t("关闭记忆编辑器", "Close memory editor")}
            >
              <Icon name="close" />
            </button>
          </div>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              await mutate(
                "/api/memories",
                {
                  project_id: projectID,
                  key: editor.key.trim(),
                  content: editor.content,
                  expected_version: editor.version,
                },
                () => setEditor(null),
              );
            }}
          >
            <label>
              {t("记忆键名", "Memory key")}
              <input
                value={editor.key}
                onChange={(e) => setEditor({ ...editor, key: e.target.value })}
                required
                readOnly={!!editor.id}
                maxLength={160}
                placeholder="project.architecture"
              />
            </label>
            <label>
              {t("内容", "Content")}
              <textarea
                value={editor.content}
                onChange={(e) =>
                  setEditor({ ...editor, content: e.target.value })
                }
                rows={6}
                required
                maxLength={16000}
              />
            </label>
            <p className="form-hint">
              {t(
                "你提交的内容将作为已审阅记忆提供给本项目 Agent。不要存放密码或访问令牌。",
                "Your content will become reviewed context for this project’s agents. Do not store passwords or access tokens.",
              )}{" "}
              · v{editor.version} → v{editor.version + 1}
            </p>
            {changed && (
              <div className="conflict-notice">
                <p>
                  {t(
                    "此记录已有更新。草稿保留中，请先审阅最新内容。",
                    "This record was updated. Your draft is preserved; review the latest content first.",
                  )}
                </p>
                <button
                  type="button"
                  className="secondary"
                  onClick={() =>
                    editorLatest &&
                    setEditor({
                      id: editorLatest.id,
                      key: editorLatest.key,
                      content: editorLatest.content,
                      version: editorLatest.version,
                    })
                  }
                >
                  {t("用最新内容替换草稿", "Replace draft with latest content")}
                </button>
              </div>
            )}
            <button
              className="primary"
              disabled={
                busy || changed || !editor.key.trim() || !editor.content.trim()
              }
            >
              {t("保存已审阅记忆", "Save reviewed memory")}
            </button>
          </form>
        </section>
      )}
      <section className="panel">
        <div className="panel-heading memory-toolbar">
          <label className="search-box">
            <Icon name="search" size={18} />
            <span className="sr-only">
              {t("搜索共享记忆", "Search shared memory")}
            </span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("搜索键名或内容…", "Search keys or content…")}
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={archived}
              onChange={(e) => setArchived(e.target.checked)}
            />
            {t("查看已归档", "Show archived")}
          </label>
        </div>
        {records.length ? (
          <div className="memory-list">
            {records.map((memory) => (
              <article className="memory-record" key={memory.id}>
                <div className="record-heading">
                  <h3>{memory.key}</h3>
                  <span className="pill">
                    v{memory.version} ·{" "}
                    {isArchived(memory)
                      ? t("已归档", "Archived")
                      : t("已审阅", "Reviewed")}
                  </span>
                </div>
                <pre>{memory.content}</pre>
                <footer>
                  <span className="small-text muted">
                    <DateText date={memory.updated_at} lang={lang} />
                    {memory.source ? ` · ${memory.source}` : ""}
                  </span>
                  {!isArchived(memory) && (
                    <div className="button-row">
                      <button
                        className="text-button"
                        aria-expanded={editor?.id === memory.id}
                        aria-controls="memory-form"
                        onClick={() =>
                          setEditor(
                            editor?.id === memory.id
                              ? null
                              : {
                                  id: memory.id,
                                  key: memory.key,
                                  content: memory.content,
                                  version: memory.version,
                                },
                          )
                        }
                      >
                        {t("编辑", "Edit")}
                      </button>
                      <button
                        className="text-button muted"
                        disabled={busy}
                        onClick={() =>
                          void mutate(
                            `/api/memories/${encodeURIComponent(memory.id)}/archive`,
                            { expected_version: memory.version },
                          )
                        }
                      >
                        {t("归档", "Archive")}
                      </button>
                    </div>
                  )}
                </footer>
              </article>
            ))}
          </div>
        ) : (
          <Empty
            icon="memory"
            title={
              query
                ? t("没有匹配的记忆", "No matching memories")
                : archived
                  ? t("没有已归档记忆", "No archived memories")
                  : t("为协作建立共同上下文", "Build shared context")
            }
          >
            {t(
              "保存项目约定、已确认决策和可复用结论。归档记录不会继续注入 Agent 上下文。",
              "Store project conventions, confirmed decisions and reusable findings. Archived records are excluded from agent context.",
            )}
          </Empty>
        )}
      </section>
    </>
  );
}
