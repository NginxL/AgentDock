import { useEffect, useRef, useState } from "react";
import { useModelCatalog } from "./modelCatalog";
import type { Agent, Session, Mutate, Translate } from "./types";

const effortLabels: Record<string, [string, string]> = {
  none: ["关闭", "None"],
  minimal: ["最低", "Minimal"],
  low: ["低", "Low"],
  medium: ["中", "Medium"],
  high: ["高", "High"],
  xhigh: ["很高", "Extra high"],
  max: ["最高", "Max"],
  ultra: ["超高", "Ultra"],
  ultracode: ["Ultra Code", "Ultra Code"],
};

export default function InferenceControls({
  agent,
  session,
  token,
  busy,
  runtimeEnabled,
  demo,
  mutate,
  t,
}: {
  agent: Agent;
  session: Session;
  token: string;
  busy: boolean;
  runtimeEnabled: boolean;
  demo: boolean;
  mutate: Mutate;
  t: Translate;
}) {
  const [open, setOpen] = useState<"model" | "effort" | null>(null);
  const [saving, setSaving] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const modelButton = useRef<HTMLButtonElement>(null);
  const effortButton = useRef<HTMLButtonElement>(null);
  const settings = session.model_override ? session : agent;
  const model = settings.model ?? "";
  const effort = settings.effort ?? "";
  const environment = agent.environment_id ?? "local";
  const catalog = useModelCatalog(
    token,
    agent.provider,
    environment,
    runtimeEnabled && !demo,
    open,
  );
  const models = demo
    ? [
        {
          id: "example-model",
          name: "Example model",
          efforts: ["low", "medium", "high", "max"],
        },
        {
          id: "example-fast",
          name: "Example fast",
          efforts: ["low", "medium", "high"],
        },
      ]
    : catalog.models;
  const { loading, failed } = catalog;
  const selected = models.find((item) => item.id === model);
  const modelName = selected?.name || model || t("默认模型", "Default model");
  const effortName = effortLabels[effort]
    ? t(...effortLabels[effort])
    : effort || t("自动", "Auto");

  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(null);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        setOpen(null);
        (open === "model" ? modelButton : effortButton).current?.focus();
      }
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  async function choose(
    nextModel: string,
    nextEffort: string,
    inherit = false,
  ) {
    if (busy || saving || demo) return;
    setSaving(true);
    try {
      const ok = await mutate(
        `/api/sessions/${encodeURIComponent(session.id)}/settings`,
        inherit
          ? { inherit: true }
          : { model: nextModel || null, effort: nextEffort || null },
      );
      if (ok) {
        setOpen(null);
        (open === "model" ? modelButton : effortButton).current?.focus();
      }
    } finally {
      setSaving(false);
    }
  }
  const options =
    open === "model"
      ? [
          { id: "", name: t("默认模型", "Default model") },
          ...(model && !selected ? [{ id: model, name: model }] : []),
          ...models,
        ]
      : [
          { id: "", name: t("自动", "Auto") },
          ...(effort && !selected?.efforts.includes(effort)
            ? [{ id: effort, name: effortName }]
            : []),
          ...(selected?.efforts ?? []).map((id) => ({
            id,
            name: effortLabels[id] ? t(...effortLabels[id]) : id,
          })),
        ];
  return (
    <div className="inference-controls" ref={root}>
      <div className="inference-pill">
        <button
          type="button"
          ref={modelButton}
          aria-label={`${t("模型", "Model")}: ${modelName}`}
          aria-haspopup="dialog"
          aria-expanded={open === "model"}
          aria-controls={`inference-${session.id}`}
          disabled={saving || (busy && !demo)}
          onClick={() => setOpen(open === "model" ? null : "model")}
        >
          <span>{modelName}</span>
          <span aria-hidden="true">⌄</span>
        </button>
        <span className="inference-divider" aria-hidden="true" />
        <button
          type="button"
          ref={effortButton}
          aria-label={`${t("推理等级", "Reasoning effort")}: ${effortName}`}
          aria-haspopup="dialog"
          aria-expanded={open === "effort"}
          aria-controls={`inference-${session.id}`}
          disabled={saving || (busy && !demo)}
          onClick={() => setOpen(open === "effort" ? null : "effort")}
        >
          <span>{effortName}</span>
          <span aria-hidden="true">⌄</span>
        </button>
      </div>
      {open && (
        <div
          className="inference-popover"
          id={`inference-${session.id}`}
          role="dialog"
          aria-label={
            open === "model"
              ? t("选择模型", "Select model")
              : t("选择推理等级", "Select reasoning effort")
          }
        >
          <div className="inference-heading">
            <span>
              {open === "model"
                ? t("选择模型", "Select model")
                : t("选择推理等级", "Select reasoning effort")}
            </span>
            <button
              type="button"
              className="icon-button"
              aria-label={t("关闭", "Close")}
              onClick={() => setOpen(null)}
            >
              ×
            </button>
          </div>
          <div
            className="inference-options"
            role="menu"
            aria-label={
              open === "model"
                ? t("模型", "Model")
                : t("推理等级", "Reasoning effort")
            }
          >
            {options.map((item) => (
              <button
                type="button"
                role="menuitemradio"
                key={item.id}
                aria-checked={item.id === (open === "model" ? model : effort)}
                disabled={busy || saving || demo}
                onClick={() =>
                  void choose(
                    open === "model" ? item.id : model,
                    open === "model"
                      ? item.id === model
                        ? effort
                        : ""
                      : item.id,
                  )
                }
              >
                <span>{item.name}</span>
                <span aria-hidden="true">
                  {item.id === (open === "model" ? model : effort) ? "✓" : ""}
                </span>
              </button>
            ))}
          </div>
          {loading && (
            <p role="status">
              {t("正在读取可用模型…", "Loading available models…")}
            </p>
          )}
          {!loading &&
            !demo &&
            (failed || !runtimeEnabled || !models.length) && (
              <p role="status">
                {t(
                  "模型列表暂不可用，当前设置已保留。",
                  "Model list unavailable. Your current settings are kept.",
                )}
              </p>
            )}
          {!loading && open === "effort" && !model && (
            <p>
              {t(
                "选择模型后可设置推理等级。",
                "Choose a model to select its reasoning effort.",
              )}
            </p>
          )}
          {!!session.model_override && (
            <button
              type="button"
              className="inference-reset"
              disabled={busy || saving || demo}
              onClick={() => void choose("", "", true)}
            >
              {t("使用 Agent 默认设置", "Use agent defaults")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
