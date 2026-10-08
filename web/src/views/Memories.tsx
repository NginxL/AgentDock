import * as uiMessages from "../messages";
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
        headingLevel={2}
        eyebrow=""
        title={t(...uiMessages.memories_project_memory_772393)}
        description={t(
          ...uiMessages.memories_share_reviewed_project_conventions_and_decisi_3e9526,
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
            {t(...uiMessages.memories_add_memory_b33b9a)}
          </button>
        }
      />
      {!!proposals.length && (
        <section className="panel proposals">
          <div className="panel-heading">
            <div>
              <h2>
                {t(...uiMessages.memories_proposals_awaiting_review_d0b5d7)}
              </h2>
              <p>
                {t(
                  ...uiMessages.memories_only_approved_content_enters_shared_context_da8308,
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
                      {t(...uiMessages.memories_view_current_memory_11e18a)}
                    </summary>
                    <pre>{current.content}</pre>
                  </details>
                )}
                <pre>{proposal.content}</pre>
                {conflict && (
                  <p className="inline-error">
                    {t(
                      ...uiMessages.memories_the_memory_version_changed_ask_the_agent_for_fc6c2f,
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
                    {t(...uiMessages.memories_approve_memory_1e414f)}
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
                    {t(...uiMessages.memories_reject_proposal_a285a8)}
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
                ? t(...uiMessages.memories_edit_memory_3a725f)
                : t(...uiMessages.memories_add_reviewed_memory_17668c)}
            </h2>
            <button
              className="icon-button"
              onClick={() => setEditor(null)}
              aria-label={t(...uiMessages.memories_close_memory_editor_14546e)}
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
              {t(...uiMessages.memories_memory_key_6c6a3a)}
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
              {t(...uiMessages.memories_content_12defa)}
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
                ...uiMessages.memories_your_content_will_become_reviewed_context_for_1e25b4,
              )}{" "}
              · v{editor.version} → v{editor.version + 1}
            </p>
            {changed && (
              <div className="conflict-notice">
                <p>
                  {t(
                    ...uiMessages.memories_this_record_was_updated_your_draft_is_preserv_ee0477,
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
                  {t(
                    ...uiMessages.memories_replace_draft_with_latest_content_554da4,
                  )}
                </button>
              </div>
            )}
            <button
              className="primary"
              disabled={
                busy || changed || !editor.key.trim() || !editor.content.trim()
              }
            >
              {t(...uiMessages.memories_save_reviewed_memory_e3180b)}
            </button>
          </form>
        </section>
      )}
      <section className="panel">
        <div className="panel-heading memory-toolbar">
          <label className="search-box">
            <Icon name="search" size={18} />
            <span className="sr-only">
              {t(...uiMessages.memories_search_project_memory_6517ef)}
            </span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t(
                ...uiMessages.memories_search_keys_or_content_bc81ec,
              )}
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={archived}
              onChange={(e) => setArchived(e.target.checked)}
            />
            {t(...uiMessages.memories_show_archived_b4d896)}
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
                      ? t(...uiMessages.memories_archived_c1c10b)
                      : t(...uiMessages.memories_reviewed_817c6b)}
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
                        {t(...uiMessages.memories_edit_b936a3)}
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
                        {t(...uiMessages.memories_archive_990782)}
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
                ? t(...uiMessages.memories_no_matching_memories_70af51)
                : archived
                  ? t(...uiMessages.memories_no_archived_memories_3ef280)
                  : t(...uiMessages.memories_build_shared_context_13b29b)
            }
          >
            {t(
              ...uiMessages.memories_store_project_conventions_confirmed_decisions_613036,
            )}
          </Empty>
        )}
      </section>
    </>
  );
}
