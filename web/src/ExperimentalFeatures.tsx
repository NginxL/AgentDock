import * as uiMessages from "./messages";
import { createContext, useContext, useState } from "react";
import type { Mutate, Translate } from "./types";

export type Features = Partial<
  Record<"automatic_failover" | "native_switching" | "acp_agents", boolean>
>;
// Undefined supports older servers and offline demos. New servers always send
// explicit defaults, including false for every unaccepted experimental feature.
export const FeatureContext = createContext<Features>({});
export const useFeature = (name: keyof Features) =>
  useContext(FeatureContext)[name] !== false;

const descriptions = {
  automatic_failover: [
    "自动换号",
    "Automatic failover",
    "在明确拒绝且任务尚未开始时选择其他账号。账号轮换可能违反服务条款；不得用于规避用量限制。",
    "Select another account only after a definite rejection and before any work. Account rotation may breach provider terms; do not use it to evade usage limits.",
  ],
  native_switching: [
    "本机客户端换号",
    "Native client switching",
    "保存、切换或恢复时可能退出并重新打开所选客户端。会话仍由原生客户端管理，真实换号需要自行验收。",
    "Saving, switching or recovering may quit and reopen the selected client. Native clients retain their histories; verify switching with your own accounts.",
  ],
  acp_agents: [
    "更多 Agent",
    "Additional agents",
    "启用 ACP 客户端。协议测试已覆盖，具体 CLI 版本和真实任务仍需验收。",
    "Enable ACP clients. Protocol tests are covered; verify your CLI version with real tasks.",
  ],
} as const;

export default function ExperimentalFeatures({
  features,
  mutate,
  busy,
  t,
}: {
  features: Features;
  mutate: Mutate;
  busy: boolean;
  t: Translate;
}) {
  const [acknowledged, setAcknowledged] = useState<Features>({});
  return (
    <details className="panel experimental-settings">
      <summary>
        {t(...uiMessages.experimentalfeatures_experimental_features_4a98cf)}
      </summary>
      {Object.entries(descriptions).map(([key, labels]) => {
        const name = key as keyof Features;
        const enabled = features[name] === true;
        return (
          <section key={name} className="form-grid">
            <div>
              <strong>{t(labels[0], labels[1])}</strong>
              <p className="form-hint">{t(labels[2], labels[3])}</p>
            </div>
            <div>
              {!enabled && (
                <label className="account-check">
                  <input
                    type="checkbox"
                    checked={acknowledged[name] === true}
                    onChange={(event) =>
                      setAcknowledged({
                        ...acknowledged,
                        [name]: event.target.checked,
                      })
                    }
                  />
                  {t(
                    ...uiMessages.experimentalfeatures_i_understand_these_limitations_9ffd3d,
                  )}
                </label>
              )}
              <button
                disabled={busy || (!enabled && !acknowledged[name])}
                onClick={() =>
                  void mutate("/api/features", {
                    name,
                    enabled: !enabled,
                    acknowledged: acknowledged[name] === true,
                  })
                }
              >
                {enabled
                  ? t(...uiMessages.experimentalfeatures_disable_d0c525)
                  : t(...uiMessages.experimentalfeatures_enable_025e9d)}
              </button>
            </div>
          </section>
        );
      })}
    </details>
  );
}
