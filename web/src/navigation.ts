import { useCallback, useEffect, useRef, useState } from "react";

export type Tab =
  | "workspace"
  | "projects"
  | "conversations"
  | "usage"
  | "tokens"
  | "accounts";
export type ProjectView = "agents" | "tasks" | "memory";
type Route = {
  tab: Tab;
  projectID: string;
  projectView: ProjectView;
  agentID: string;
  sessionID: string;
  taskID: string;
};
const home: Route = {
  tab: "workspace",
  projectID: "",
  projectView: "tasks",
  agentID: "",
  sessionID: "",
  taskID: "",
};

function readRoute(): Route | null {
  const hash = window.location.hash;
  if (!hash) return home;
  // Native anchor links (for example Skip to content) do not change pages.
  if (!hash.startsWith("#/")) return null;
  const [path, query] = hash.slice(2).split("?", 2);
  const params = new URLSearchParams(query);
  const projectID = params.get("project") ?? "";
  if (path === "conversations")
    return {
      ...home,
      tab: "conversations",
      sessionID: params.get("session") ?? "",
    };
  if (path.startsWith("agents/")) {
    try {
      return {
        ...home,
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
      ...home,
      tab: "projects",
      projectID,
      projectView: path === "messages" ? "tasks" : "memory",
      agentID: "",
    };
  if (path === "projects" || (path === "workspace" && projectID)) {
    const view = params.get("view");
    return {
      ...home,
      tab: "projects",
      projectID,
      projectView:
        path === "workspace"
          ? "agents"
          : view === "agents" || view === "memory"
            ? view
            : "tasks",
      agentID: "",
      taskID: params.get("task") ?? "",
    };
  }
  return {
    ...home,
    tab:
      path === "usage" || path === "tokens" || path === "accounts"
        ? path
        : "workspace",
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
    if (next.tab === "conversations" && next.sessionID)
      params.set("session", next.sessionID);
    if (next.tab === "projects" && next.projectID) {
      params.set("project", next.projectID);
      if (!next.agentID) params.set("view", next.projectView);
      if (next.projectView === "tasks" && next.taskID)
        params.set("task", next.taskID);
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
