import { useCallback, useEffect, useRef, useState } from "react";

export type Tab = "workspace" | "messages" | "memory" | "usage" | "tokens";
type Route = { tab: Tab; projectID: string; agentID: string };
const home: Route = { tab: "workspace", projectID: "", agentID: "" };

function readRoute(): Route | null {
  const hash = window.location.hash;
  if (!hash) return home;
  // Native anchor links (for example Skip to content) do not change pages.
  if (!hash.startsWith("#/")) return null;
  const [path, query] = hash.slice(2).split("?", 2);
  const projectID = new URLSearchParams(query).get("project") ?? "";
  if (path.startsWith("agents/")) {
    try {
      return {
        tab: "workspace",
        projectID,
        agentID: decodeURIComponent(path.slice(7)),
      };
    } catch {
      return home;
    }
  }
  const tab = ["workspace", "messages", "memory", "usage", "tokens"].includes(
    path,
  )
    ? (path as Tab)
    : "workspace";
  return { tab, projectID, agentID: "" };
}

export function useNavigation() {
  const [route, setRoute] = useState<Route>(() => readRoute() ?? home);
  const current = useRef(route);
  const navigate = useCallback((change: Partial<Route>, replace = false) => {
    const next = { ...current.current, ...change };
    const page =
      next.tab === "workspace" && next.agentID
        ? `agents/${encodeURIComponent(next.agentID)}`
        : next.tab;
    const query = next.projectID
      ? `?${new URLSearchParams({ project: next.projectID })}`
      : "";
    const hash = `#/${page}${query}`;
    if (window.location.hash !== hash) {
      window.history[replace ? "replaceState" : "pushState"](
        null,
        "",
        window.location.pathname + window.location.search + hash,
      );
    }
    current.current = next;
    setRoute(next);
  }, []);
  useEffect(() => {
    const restore = () => {
      const next = readRoute();
      if (!next) return;
      current.current = next;
      setRoute(next);
    };
    window.addEventListener("popstate", restore);
    window.addEventListener("hashchange", restore);
    return () => {
      window.removeEventListener("popstate", restore);
      window.removeEventListener("hashchange", restore);
    };
  }, []);
  return { ...route, navigate };
}
