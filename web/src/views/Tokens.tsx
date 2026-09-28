import type { Agent, Translate, Language } from "../types";
import type { Metrics, Meter } from "../metrics";
import { TPS, tokens, exactTokens } from "../metrics";
import { PageTitle } from "../ui";
import DailyActivity from "../DailyActivity";

function TokenValue({ value }: { value?: number }) {
  const exact = exactTokens(value);
  return (
    <span
      className="token-value"
      title={value == null ? undefined : exact}
      aria-label={exact}
    >
      {tokens(value)}
    </span>
  );
}

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
          "查看 Codex 和 Claude Code 的累计用量与每日活跃情况。",
          "Track total usage and daily activity across Codex and Claude Code.",
        )}
      />
      <div className="token-totals">
        {[
          [t("累计 Token", "Total tokens"), total?.total_tokens],
          [t("输入（含缓存）", "Input (including cache)"), total?.input_tokens],
          [t("输出", "Output"), total?.output_tokens],
          [t("已记录会话", "Recorded sessions"), total?.sessions],
        ].map(([label, n], i) => (
          <div className="panel token-stat" key={label as string}>
            <span>{label}</span>
            <strong>
              {i === 3 ? (
                total?.sessions ? (
                  exactTokens(n as number)
                ) : (
                  "—"
                )
              ) : (
                <TokenValue
                  value={total?.sessions ? (n as number) : undefined}
                />
              )}
            </strong>
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
                  <td key={i}>
                    <TokenValue value={m.sessions ? v : undefined} />
                  </td>
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
                  <td>
                    <TokenValue
                      value={m?.sessions ? m.total_tokens : undefined}
                    />
                  </td>
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
      <DailyActivity
        activity={metrics?.activity}
        failed={failed}
        t={t}
        lang={lang}
      />
    </>
  );
}
