import { useCallback, useEffect, useRef, useState } from "react";

export type Tab = "workspace" | "projects" | "usage" | "tokens";
export type ProjectView = "agents" | "tasks" | "memory";
type Route = {
  tab: Tab;
  projectID: string;
  projectView: ProjectView;
  agentID: string;
};
const home: Route = {
  tab: "workspace",
  projectID: "",
  projectView: "agents",
  agentID: "",
};

function readRoute(): Route | null {
  const hash = window.location.hash;
  if (!hash) return home;
  // Native anchor links (for example Skip to content) do not change pages.
  if (!hash.startsWith("#/")) return null;
  const [path, query] = hash.slice(2).split("?", 2);
  const params = new URLSearchParams(query);
  const projectID = params.get("project") ?? "";
  if (path.startsWith("agents/")) {
    try {
      return {
        tab: projectID ? "projects" : "workspace",
        projectID,
        projectView: "agents",
        agentID: decodeURIComponent(path.slice(7)),
      };
    } catch {
      return home;
    }
  }
  // Existing bookmarks retain their project and destination inside Projects.
  if (path === "messages" || path === "memory")
    return {
      tab: "projects",
      projectID,
      projectView: path === "messages" ? "tasks" : "memory",
      agentID: "",
    };
  if (path === "projects" || (path === "workspace" && projectID)) {
    const view = params.get("view");
    return {
      tab: "projects",
      projectID,
      projectView: view === "tasks" || view === "memory" ? view : "agents",
      agentID: "",
    };
  }
  return {
    ...home,
    tab: path === "usage" || path === "tokens" ? path : "workspace",
  };
}

export function useNavigation() {
  const [route, setRoute] = useState<Route>(() => readRoute() ?? home);
  const current = useRef(route);
  const navigate = useCallback((change: Partial<Route>, replace = false) => {
    const next = { ...current.current, ...change };
    const page =
      (next.tab === "workspace" || next.tab === "projects") && next.agentID
        ? `agents/${encodeURIComponent(next.agentID)}`
        : next.tab;
    const params = new URLSearchParams();
    if (next.tab === "projects" && next.projectID) {
      params.set("project", next.projectID);
      if (!next.agentID && next.projectView !== "agents")
        params.set("view", next.projectView);
    }
    const query = params.size ? `?${params}` : "";
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
