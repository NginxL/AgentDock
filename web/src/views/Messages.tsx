import { useState } from "react";
import type { Agent, DockState, Language, Mutate, Translate } from "../types";
import { DateText, Empty, Icon, PageTitle } from "../ui";

export default function Messages({
  t,
  lang,
  state,
  projectID,
  agents,
  busy,
  mutate,
}: {
  t: Translate;
  lang: Language;
  state: DockState;
  projectID: string;
  agents: Agent[];
  busy: boolean;
  mutate: Mutate;
}) {
  const [recipient, setRecipient] = useState(agents[0]?.id ?? "");
  const [filter, setFilter] = useState("all");
  const [body, setBody] = useState("");
  const messages = state.messages
    .filter(
      (m) =>
        m.project_id === projectID &&
        (filter === "all" || m.recipient_id === filter),
    )
    .slice()
    .reverse();
  const name = (id: string) =>
    id === "human"
      ? t("你", "You")
      : (agents.find((a) => a.id === id)?.name ??
        t("已移除的 Agent", "Removed agent"));
  return (
    <>
      <PageTitle
        eyebrow="EXPLICIT COMMUNICATION"
        title={t("把信息交给对的人", "Keep collaboration explicit")}
        description={t(
          "项目内消息留痕。Agent 可通过 MCP 读取收件箱和向同伴发信；收到消息不会自动执行。",
          "Messages stay within the project. Agents can read their inbox and send peer messages through MCP. Receiving a message does not start a run.",
        )}
      />
      <div className="two-column">
        <section className="panel">
          <div className="panel-heading">
            <h2>{t("项目消息", "Project messages")}</h2>
            <label className="compact-select">
              <span className="sr-only">
                {t("按收件人筛选", "Filter by recipient")}
              </span>
              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                <option value="all">{t("所有收件人", "All recipients")}</option>
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {messages.length ? (
            <div className="message-list">
              {messages.map((message) => (
                <article className="message-card" key={message.id}>
                  <header>
                    <strong>
                      {name(message.sender_id)}
                      <Icon name="arrow" size={14} />
                      {name(message.recipient_id)}
                    </strong>
                    <DateText date={message.created_at} lang={lang} />
                  </header>
                  <p>{message.body}</p>
                  <footer>
                    <span className="pill">
                      {message.acknowledged_at
                        ? t("已确认读取", "Acknowledged")
                        : t("已送达收件箱", "Delivered to inbox")}
                    </span>
                    {message.correlation_id && (
                      <span className="small-text muted">
                        {t("关联", "Reference")}: {message.correlation_id}
                      </span>
                    )}
                  </footer>
                </article>
              ))}
            </div>
          ) : (
            <Empty
              icon="message"
              title={t("还没有协作消息", "No messages yet")}
            >
              {t(
                "给 Agent 发送上下文、问题或交接说明。之后手动运行对应 Agent，它才会开始处理。",
                "Send context, questions or handoff notes. Start the recipient agent manually when it should act.",
              )}
            </Empty>
          )}
        </section>
        <section className="panel inset-form sticky-panel">
          <span className="eyebrow">HUMAN → AGENT</span>
          <h2>{t("发送消息", "Send a message")}</h2>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              await mutate(
                "/api/messages",
                {
                  project_id: projectID,
                  sender_id: "human",
                  recipient_id: recipient,
                  body: body.trim(),
                },
                () => setBody(""),
              );
            }}
          >
            <label>
              {t("收件人", "Recipient")}
              <select
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                required
              >
                {!agents.length && (
                  <option value="">
                    {t("先添加 Agent", "Add an agent first")}
                  </option>
                )}
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name} · {agent.provider}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("消息内容", "Message")}
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={8}
                maxLength={12000}
                required
                placeholder={t(
                  "说明背景、待确认事项或下一步建议…",
                  "Share context, open questions or suggested next steps…",
                )}
              />
            </label>
            <p className="form-hint">
              {t(
                "以你的身份发送，仅进入当前项目的收件箱。",
                "Sent as you, into this project’s mailbox only.",
              )}
            </p>
            <button
              className="primary full"
              disabled={busy || !recipient || !body.trim()}
            >
              {t("发送到收件箱", "Send to inbox")}
              <Icon name="arrow" size={17} />
            </button>
          </form>
        </section>
      </div>
    </>
  );
}
