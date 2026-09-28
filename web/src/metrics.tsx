import { useEffect, useState } from "react";
import { request } from "./api";
import type { Translate } from "./types";

export interface Meter {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  total_tokens: number;
  sessions: number;
  active_sessions: number;
  current_tps: number | null;
  average_tps: number;
  points: number[];
  updated_at: number | null;
}
export interface Metrics {
  as_of: number;
  total: Meter;
  providers: Record<string, Meter>;
  agents: Record<string, Meter>;
  unassigned_sessions: number;
  scan_status: string;
  activity?: Activity;
}
export interface Activity {
  today: string;
  days: { date: string; tokens: number }[];
  updated_at: number | null;
  status: string;
}
export function useMetrics(token: string, demo: boolean, agentIDs: string[]) {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [failed, setFailed] = useState(false);
  const demoKey = agentIDs.join(",");
  useEffect(() => {
    setMetrics(null);
    setFailed(false);
    if (demo) {
      const meter = (factor: number): Meter => ({
        input_tokens: Math.round(823400 * factor),
        output_tokens: Math.round(134600 * factor),
        cache_read_tokens: Math.round(612000 * factor),
        cache_write_tokens: Math.round(54000 * factor),
        total_tokens: Math.round(958000 * factor),
        sessions: Math.round(20 * factor),
        active_sessions: 1,
        current_tps: 36.8 * factor,
        average_tps: 24.5 * factor,
        points: Array.from(
          { length: 60 },
          (_, i) =>
            factor *
            (i < 12
              ? 0
              : i < 18
                ? 12 + (i - 12) * 9
                : i < 38
                  ? 62
                  : i < 45
                    ? 62 - (i - 38) * 7
                    : 36.8),
        ),
        updated_at: Date.now() / 1000,
      });
      const weights = Array.from({ length: 365 }, (_, i) =>
        i < 160 || i % 9 < 2 ? 0 : (Math.sin(i * 1.7) + 1.2) * i,
      );
      const weightSum = weights.reduce((sum, n) => sum + n, 0);
      const activityDays = weights.map((weight, i) => {
        const date = new Date();
        date.setDate(date.getDate() - 364 + i);
        return {
          date: date.toLocaleDateString("en-CA"),
          tokens: Math.floor((weight / weightSum) * 958000),
        };
      });
      activityDays[364].tokens +=
        958000 - activityDays.reduce((sum, d) => sum + d.tokens, 0);
      setMetrics({
        as_of: Date.now() / 1000,
        total: { ...meter(1), active_sessions: 2 },
        providers: { codex: meter(0.6), claude: meter(0.4) },
        agents: Object.fromEntries(
          agentIDs.map((id, i) => [id, meter(i % 2 ? 0.3 : 0.45)]),
        ),
        unassigned_sessions: 5,
        scan_status: "ready",
        activity: {
          today: new Date().toLocaleDateString("en-CA"),
          days: activityDays,
          updated_at: Date.now() / 1000,
          status: "ready",
        },
      });
      return;
    }
    if (!token) return;
    const abort = new AbortController();
    let pending = false;
    async function poll() {
      if (pending) return;
      pending = true;
      try {
        const next = await request<Metrics>(
          token,
          "/api/metrics",
          undefined,
          abort.signal,
        );
        if (!abort.signal.aborted) {
          if (!next?.total || !Array.isArray(next.total.points))
            throw new Error("Invalid metrics");
          setMetrics(next);
          setFailed(false);
        }
      } catch {
        if (!abort.signal.aborted) setFailed(true);
      } finally {
        pending = false;
      }
    }
    void poll();
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "hidden") void poll();
    }, 3000);
    return () => {
      abort.abort();
      window.clearInterval(timer);
    };
  }, [token, demo, demoKey]);
  return { metrics, failed };
}
const exactNumber = new Intl.NumberFormat("en-US");
const shortNumber = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
});
const tokenUnits = ["", "K", "M", "B"];
export const exactTokens = (n?: number | null) =>
  n == null || !Number.isFinite(n) || n < 0 ? "—" : exactNumber.format(n);
export function tokens(n?: number | null) {
  if (n == null || !Number.isFinite(n) || n < 0) return "—";
  let unit = 0;
  while (n >= 1000 && unit < tokenUnits.length - 1) {
    n /= 1000;
    unit++;
  }
  n = Math.round(n * 100) / 100;
  // Promote rounded boundary values so 999,999 becomes 1M, not 1,000K.
  if (n >= 1000 && unit < tokenUnits.length - 1) {
    n /= 1000;
    unit++;
  }
  return shortNumber.format(n) + tokenUnits[unit];
}
export function TPS({
  meter,
  t,
  compact = false,
  stale = false,
}: {
  meter?: Meter;
  t: Translate;
  compact?: boolean;
  stale?: boolean;
}) {
  const points = meter?.points ?? [];
  const max = Math.max(100, ...points);
  const path = points
    .map((n, i) => `${i ? "L" : "M"}${(i * 600) / 59},${100 - (n / max) * 100}`)
    .join(" ");
  const number = (n?: number | null) =>
    n == null || stale ? "—" : n.toFixed(1);
  return (
    <div
      className={`tps-panel ${compact ? "compact" : ""}`}
      aria-label={t("输出 Token 吞吐量", "Output token throughput")}
    >
      <div className="tps-heading">
        <strong>TPS</strong>
        <span className="session-pill">
          ● {meter?.active_sessions ?? 0}{" "}
          {t("会话", meter?.active_sessions === 1 ? "session" : "sessions")}
        </span>
        <span className="tps-latest">
          {t("当前", "Current")} <b>{number(meter?.current_tps)} TPS</b>
        </span>
        <span>
          {t("3m 均值", "3m avg")} <b>{number(meter?.average_tps)} TPS</b>
        </span>
      </div>
      <div className="tps-plot">
        {[0, 50, 100].map((top, i) => (
          <span key={top} className="tps-tick" style={{ top: `${top}%` }}>
            {Math.round(max * (1 - i / 2))}
          </span>
        ))}
        <svg
          viewBox="0 0 600 100"
          preserveAspectRatio="none"
          role="img"
          aria-label={t(
            "最近三分钟输出吞吐趋势",
            "Output throughput over the last three minutes",
          )}
        >
          {[0, 50, 100].map((y) => (
            <path
              key={y}
              d={`M0,${y}H600`}
              stroke="#d3d7d8"
              strokeDasharray="4 5"
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {points.length > 0 && !stale && (
            <path
              d={path}
              fill="none"
              stroke="#cc963d"
              strokeWidth="2"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>
      </div>
      <div className="tps-axis">
        <span>-3m</span>
        <span>{t("现在", "now")}</span>
      </div>
      {!compact && stale && (
        <p className="form-hint">
          {t("连接中断，等待更新。", "Connection lost. Waiting for an update.")}
        </p>
      )}
    </div>
  );
}
