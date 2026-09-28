import { useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent } from "react";
import type { Activity } from "./metrics";
import { exactTokens, tokens } from "./metrics";
import type { Language, Translate } from "./types";

const DAY = 86_400_000;
const ranges = [365, 180, 90];
const rangeLabels = ["1Y", "6M", "3M"];

export default function DailyActivity({
  activity,
  failed,
  t,
  lang,
}: {
  activity?: Activity;
  failed: boolean;
  t: Translate;
  lang: Language;
}) {
  const [range, setRange] = useState(365);
  const [focus, setFocus] = useState<string | null>(null);
  const [tip, setTip] = useState<{
    label: string;
    left: number;
    top: number;
  } | null>(null);
  const cells = useRef(new Map<string, HTMLButtonElement>());
  const today = activity?.today ?? new Date().toLocaleDateString("en-CA");
  // UTC arithmetic represents calendar dates, avoiding DST gaps and duplicates.
  const end = Date.parse(`${today}T00:00:00Z`);
  const start = end - (range - 1) * DAY;
  const pad = new Date(start).getUTCDay();
  const columns = Math.ceil((range + pad) / 7);
  const counts = new Map(activity?.days.map((d) => [d.date, d.tokens]) ?? []);
  const days = Array.from({ length: range }, (_, i) => {
    const at = start + i * DAY;
    const date = new Date(at).toISOString().slice(0, 10);
    return { date, at, count: counts.get(date) ?? 0 };
  });
  const max = Math.max(1, ...days.map((d) => d.count));
  const active = days.filter((d) => d.count > 0).length;
  const known = Boolean(activity);
  const busy =
    activity?.status === "pending" || activity?.status === "scanning";
  const partial = activity?.status === "partial";
  const dayFormat = new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
  const monthFormat = new Intl.DateTimeFormat(
    lang === "zh" ? "zh-CN" : "en-US",
    {
      month: "short",
      timeZone: "UTC",
    },
  );
  const months = days.flatMap((d, i) => {
    if (i !== 0 && new Date(d.at).getUTCDate() !== 1) return [];
    const column = Math.floor((i + pad) / 7) + 1;
    if ((i === 0 && new Date(start).getUTCDate() > 24) || column > columns - 2)
      return [];
    return [{ column, label: monthFormat.format(d.at) }];
  });
  function navigate(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const steps: Record<string, number> = {
      ArrowLeft: -7,
      ArrowRight: 7,
      ArrowUp: -1,
      ArrowDown: 1,
    };
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? days.length - 1
          : event.key in steps
            ? Math.max(0, Math.min(days.length - 1, index + steps[event.key]))
            : null;
    if (next === null) return;
    event.preventDefault();
    cells.current.get(days[next].date)?.focus();
  }
  function showTip(element: HTMLButtonElement, label: string) {
    const rect = element.getBoundingClientRect();
    setTip({
      label,
      left: Math.max(
        160,
        Math.min(window.innerWidth - 160, rect.left + rect.width / 2),
      ),
      top: rect.top - 10,
    });
  }
  return (
    <section
      className="panel daily-activity"
      aria-label={t("每日活跃", "Daily activity")}
    >
      <div className="activity-heading">
        <div>
          <h2>{t("每日活跃", "DAILY ACTIVITY")}</h2>
          <p aria-live="polite">
            {known ? t(`${active} 个活跃日`, `${active} active days`) : "—"}
            {" · "}
            {rangeLabels[ranges.indexOf(range)]}
            {(failed || partial || busy || !known) && (
              <span className="activity-status" role="status">
                {" · "}
                {failed
                  ? t("连接中断", "Disconnected")
                  : partial
                    ? t("部分数据", "Partial data")
                    : t("更新中", "Updating")}
              </span>
            )}
          </p>
        </div>
        <select
          aria-label={t("活跃图时间范围", "Activity range")}
          value={range}
          onChange={(e) => {
            setRange(Number(e.target.value));
            setFocus(null);
            setTip(null);
          }}
        >
          {ranges.map((n, i) => (
            <option key={n} value={n}>
              {rangeLabels[i]}
            </option>
          ))}
        </select>
      </div>
      <div className="activity-scroll" onScroll={() => setTip(null)}>
        <div
          className="activity-calendar"
          style={{ "--activity-columns": columns } as CSSProperties}
        >
          <div className="activity-months" aria-hidden="true">
            {months.map(({ column, label }) => (
              <span key={column} style={{ gridColumn: `${column} / span 3` }}>
                {label}
              </span>
            ))}
          </div>
          <div
            className="activity-grid"
            role="group"
            aria-label={t("每日 Token 用量", "Daily token usage")}
          >
            {Array.from({ length: pad }, (_, i) => (
              <span key={`pad-${i}`} aria-hidden="true" />
            ))}
            {days.map((d, i) => {
              const level =
                d.count > 0
                  ? Math.min(4, Math.max(1, Math.ceil((d.count / max) * 4)))
                  : 0;
              const date = dayFormat.format(d.at);
              const label = known
                ? `${date} · ${tokens(d.count)} Tokens`
                : `${date} · —`;
              return (
                <button
                  type="button"
                  key={d.date}
                  ref={(node) => {
                    if (node) cells.current.set(d.date, node);
                    else cells.current.delete(d.date);
                  }}
                  className={`activity-cell activity-level-${level}`}
                  aria-label={`${date}: ${known ? exactTokens(d.count) : "—"} Tokens`}
                  tabIndex={d.date === (focus ?? today) ? 0 : -1}
                  onMouseEnter={(e) => showTip(e.currentTarget, label)}
                  onMouseLeave={() => setTip(null)}
                  onFocus={(e) => {
                    setFocus(d.date);
                    showTip(e.currentTarget, label);
                  }}
                  onBlur={() => setTip(null)}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setTip(null);
                    else navigate(e, i);
                  }}
                />
              );
            })}
          </div>
        </div>
      </div>
      <div
        className="activity-legend"
        aria-label={t("用量由少到多", "Usage from less to more")}
      >
        <span>{t("少", "Less")}</span>
        {[0, 1, 2, 3, 4].map((level) => (
          <i
            key={level}
            className={`activity-level-${level}`}
            aria-hidden="true"
          />
        ))}
        <span>{t("多", "More")}</span>
      </div>
      {tip && (
        <div
          className="activity-tooltip"
          role="tooltip"
          style={{ left: tip.left, top: tip.top }}
        >
          {tip.label}
        </div>
      )}
    </section>
  );
}
