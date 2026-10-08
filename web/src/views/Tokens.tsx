import * as uiMessages from "../messages";
import type { Agent, Provider, Translate, Language } from "../types";
import { providerNames } from "../ProviderIcon";
import type { Metrics, Meter } from "../metrics";
import { TPS, tokens, exactTokens } from "../metrics";
import { Empty, PageTitle } from "../ui";
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
  const rows: [string, Meter][] = Object.entries(metrics?.providers ?? {})
    .filter(([p]) => agents.some((a) => a.provider === p))
    .map(([p, m]) => [providerNames[p as Provider] ?? p, m]);
  return (
    <>
      <PageTitle
        eyebrow={t(...uiMessages.tokens_local_usage_73d88c)}
        title={t(...uiMessages.tokens_token_statistics_4cd094)}
      />
      {!agents.length ? (
        <section className="panel">
          <Empty
            icon="dock"
            title={t(...uiMessages.tokens_no_agents_yet_be317a)}
          >
            {t(
              ...uiMessages.tokens_add_an_agent_and_start_a_conversation_to_trac_caa5cf,
            )}
          </Empty>
        </section>
      ) : (
        <>
          <div className="token-totals">
            {[
              [
                t(...uiMessages.tokens_total_tokens_278342),
                total?.total_tokens,
              ],
              [
                t(...uiMessages.tokens_input_including_cache_3c66c3),
                total?.input_tokens,
              ],
              [t(...uiMessages.tokens_output_6424f4), total?.output_tokens],
              [
                t(...uiMessages.tokens_recorded_sessions_19cd67),
                total?.sessions,
              ],
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
            <h2>{t(...uiMessages.tokens_by_provider_1b2c16)}</h2>
            <table>
              <thead>
                <tr>
                  <th>{t(...uiMessages.tokens_provider_620040)}</th>
                  <th>{t(...uiMessages.tokens_total_e4a2aa)}</th>
                  <th>{t(...uiMessages.tokens_input_58d1c4)}</th>
                  <th>{t(...uiMessages.tokens_output_6424f4)}</th>
                  <th>{t(...uiMessages.tokens_cache_read_f7e5b0)}</th>
                  <th>{t(...uiMessages.tokens_cache_write_8aacc9)}</th>
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
            <h2>{t(...uiMessages.tokens_my_agents_99e4c7)}</h2>
            <table>
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>{t(...uiMessages.tokens_total_tokens_278342)}</th>
                  <th>{t(...uiMessages.tokens_sessions_7fcc00)}</th>
                  <th>{t(...uiMessages.tokens_data_updated_1bf097)}</th>
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
                  ...uiMessages.tokens_create_an_agent_to_see_its_individual_usage_925c75,
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
      )}
    </>
  );
}
