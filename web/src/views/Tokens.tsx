import type { Agent, Translate, Language } from "../types";
import type { Metrics, Meter } from "../metrics";
import { TPS, tokens } from "../metrics";
import { PageTitle } from "../ui";

export default function Tokens({
  metrics,
  failed,
  agents,
  t,
  lang,
}: {
  metrics: Metrics | null;
  failed: boolean;
  agents: Agent[];
  t: Translate;
  lang: Language;
}) {
  const total = metrics?.total;
  const rows: [string, Meter][] = Object.entries(metrics?.providers ?? {}).map(
    ([p, m]) => [p === "codex" ? "Codex" : "Claude Code", m],
  );
  return (
    <>
      <PageTitle
        eyebrow={t("本机用量", "LOCAL USAGE")}
        title={t("Token 统计", "Token statistics")}
        description={t(
          "累计统计本机 Codex、Claude Code 的可读取用量记录，包含历史会话及 AgentDock 会话，按原生会话与消息标识去重。",
          "Cumulative usage from readable local Codex and Claude Code records, including history and AgentDock sessions. Deduplicated by native session and message identity.",
        )}
      />
      <div className="token-totals">
        {[
          [t("累计 Token", "Total tokens"), total?.total_tokens],
          [t("输入（含缓存）", "Input (including cache)"), total?.input_tokens],
          [t("输出", "Output"), total?.output_tokens],
          [t("已记录会话", "Recorded sessions"), total?.sessions],
        ].map(([label, n]) => (
          <div className="panel token-stat" key={label as string}>
            <span>{label}</span>
            <strong>{total?.sessions ? tokens(n as number) : "—"}</strong>
          </div>
        ))}
      </div>
      <section className="panel">
        <TPS meter={total} t={t} stale={failed} />
      </section>
      <section className="panel token-table">
        <h2>{t("按服务", "By provider")}</h2>
        <table>
          <thead>
            <tr>
              <th>{t("服务", "Provider")}</th>
              <th>{t("累计", "Total")}</th>
              <th>{t("输入", "Input")}</th>
              <th>{t("输出", "Output")}</th>
              <th>{t("缓存读取", "Cache read")}</th>
              <th>{t("缓存写入", "Cache write")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([name, m]) => (
              <tr key={name}>
                <th>{name}</th>
                {[
                  m.total_tokens,
                  m.input_tokens,
                  m.output_tokens,
                  m.cache_read_tokens,
                  m.cache_write_tokens,
                ].map((v, i) => (
                  <td key={i}>{m.sessions ? tokens(v) : "—"}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="panel token-table">
        <h2>{t("我的 Agent", "My agents")}</h2>
        <table>
          <thead>
            <tr>
              <th>Agent</th>
              <th>{t("累计 Token", "Total tokens")}</th>
              <th>{t("会话", "Sessions")}</th>
              <th>{t("数据更新于", "Data updated")}</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => {
              const m = metrics?.agents[a.id];
              return (
                <tr key={a.id}>
                  <th>{a.name}</th>
                  <td>{m?.sessions ? tokens(m.total_tokens) : "—"}</td>
                  <td>{m?.sessions ?? 0}</td>
                  <td>
                    {m?.updated_at
                      ? new Date(m.updated_at * 1000).toLocaleString(
                          lang === "zh" ? "zh-CN" : "en-US",
                        )
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!agents.length && (
          <p>
            {t(
              "创建 Agent 后可查看各自统计。",
              "Create an agent to see its individual usage.",
            )}
          </p>
        )}
      </section>
      <p className="form-hint" role="status">
        {metrics?.scan_status === "scanning"
          ? t(
              "正在索引本地用量，累计数值会继续补全。",
              "Indexing local usage. Totals will continue to populate.",
            )
          : metrics?.scan_status === "partial"
            ? t(
                "部分本地记录暂时无法读取，当前统计不完整。",
                "Some local records could not be read. Totals are incomplete.",
              )
            : t(
                "本地记录缺失的用量无法回溯，统计不等同于服务商账单。缓存是输入的子集，不重复加总。",
                "Usage missing from local records cannot be recovered. These totals are not a provider bill. Cache tokens are a subset of input and are not added twice.",
              )}{" "}
        {t(
          "未关联 Agent 的历史会话：",
          "Historical sessions not linked to an agent: ",
        )}
        {metrics?.unassigned_sessions ?? 0}
      </p>
    </>
  );
}
