import type { Provider } from "./types";

const icons: Record<Provider, string> = {
  codex: new URL("./assets/providers/codex.svg", import.meta.url).href,
  claude: new URL("./assets/providers/claude.svg", import.meta.url).href,
};

export const providerNames: Record<Provider, string> = {
  codex: "Codex",
  claude: "Claude Code",
};

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
