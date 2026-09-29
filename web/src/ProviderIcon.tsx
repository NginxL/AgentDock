import type { Provider } from "./types";

const icons: Record<Provider, string> = {
  codex: new URL("./assets/providers/codex.svg", import.meta.url).href,
  claude: new URL("./assets/providers/claude.svg", import.meta.url).href,
  trae: new URL("./assets/providers/trae.svg", import.meta.url).href,
  pi: new URL("./assets/providers/pi.svg", import.meta.url).href,
  cursor: new URL("./assets/providers/cursor.svg", import.meta.url).href,
  antigravity: new URL("./assets/providers/antigravity.svg", import.meta.url)
    .href,
  grok: new URL("./assets/providers/grok.svg", import.meta.url).href,
  opencode: new URL("./assets/providers/opencode.svg", import.meta.url).href,
  gemini: new URL("./assets/providers/gemini.svg", import.meta.url).href,
  qwen: new URL("./assets/providers/qwen.svg", import.meta.url).href,
};

export const providerNames: Record<Provider, string> = {
  codex: "Codex",
  claude: "Claude Code",
  trae: "Trae CLI",
  pi: "Pi",
  cursor: "Cursor CLI",
  antigravity: "Antigravity",
  grok: "Grok Build",
  opencode: "OpenCode",
  gemini: "Gemini CLI",
  qwen: "Qwen Code",
};

export const providers = Object.keys(providerNames) as Provider[];

export default function ProviderIcon({
  provider,
  size = 24,
}: {
  provider: Provider;
  size?: number;
}) {
  return (
    <img
      className="provider-icon"
      src={icons[provider]}
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
      draggable={false}
    />
  );
}
