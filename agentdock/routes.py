"""Declared admin routes; execution permission is checked before every handler."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs

from . import __version__
from .errors import Conflict, Forbidden, Invalid, Missing
from .registry import ACP_PROVIDERS, PROVIDERS, availability


@dataclass(frozen=True)
class Route:
    method: str
    pattern: str
    handler: str
    execution: object = False


ROUTES = []


def route(method, pattern, *, execution=False):
    def register(handler):
        ROUTES.append(Route(method, pattern, handler.__name__, execution))
        return handler

    return register


def dispatch_admin(api, method, parsed, payload):
    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
    for route in ROUTES:
        if method != route.method:
            continue
        match = re.fullmatch(route.pattern, parsed.path)
        if not match:
            continue
        required = (
            route.execution(api, payload, query)
            if callable(route.execution)
            else route.execution
        )
        if required and not api.execution_enabled:
            error = Forbidden("Execution is disabled for review")
            error.code = "execution_disabled"
            raise error
        return getattr(AdminRoutes(api), route.handler)(
            match.groupdict(), payload, query
        )
    raise Missing("Route not found")


class AdminRoutes:
    def __init__(self, api):
        self.api = api
        self.store, self.runtime = api.store, api.runtime

    @route("GET", r"/api/state/version")
    def version(self, ids, p, q):
        return {"version": self.store.state_version()}

    @route("GET", r"/api/diagnostics")
    def diagnostics(self, ids, p, q):
        from .diagnostics import export

        return export(self.store)

    @route("POST", r"/api/features")
    def features(self, ids, p, q):
        return self.store.set_feature(
            p.get("name"), p.get("enabled"), p.get("acknowledged")
        )

    @route("GET", r"/api/providers")
    def providers(self, ids, p, q):
        environment = self.store.get_environment(q.get("environment_id", "local"))
        if environment["kind"] == "local":
            providers = availability(self.runtime.config.get("commands", {}))
        else:
            ready = (
                environment["status"] == "connected"
                and environment["payload"].get("digest") == self.runtime.remote.digest
            )
            saved = environment["payload"].get("providers", {}) if ready else {}
            providers = {}
            for key, entry in PROVIDERS.items():
                available = saved.get(key, {}).get("available") is True
                reason = (
                    None
                    if available
                    else saved.get(key, {}).get("reason")
                    or ("not_installed" if ready else "connect_required")
                )
                providers[key] = {
                    "name": entry[0],
                    "available": available,
                    "supports_ask": key != "pi",
                    "reason": reason,
                }
        return {"environment_id": environment["id"], "providers": providers}

    @route(
        "GET",
        r"/api/directories",
        execution=lambda api, p, q: q.get("environment_id", "local") != "local",
    )
    def directories(self, ids, p, q):
        environment = self.store.get_environment(q.get("environment_id", "local"))
        path = q.get("path", "~")
        if environment["kind"] == "ssh":
            if environment["payload"].get("digest") != self.runtime.remote.digest:
                raise Conflict(
                    "Connect this SSH environment before browsing directories."
                )
            return self.runtime.remote.rpc(
                environment["id"], {"op": "directories", "path": path}
            )
        from .directories import list_directories

        return list_directories(path)

    @route("GET", r"/api/metrics")
    def metrics(self, ids, p, q):
        from .metrics import snapshot

        with self.store.reader() as reader:
            result = snapshot(reader, cache_activity=True)
        result["scan_status"] = self.api.usage.status if self.api.usage else "disabled"
        result["activity"]["status"] = (
            self.api.usage.activity_status if self.api.usage else "disabled"
        )
        return result

    @route("GET", r"/api/quotas")
    def quotas(self, ids, p, q):
        quotas = []
        for provider, env in self.store.configured_connections():
            value = self.api._quota(provider, env) or {
                "provider": provider,
                "status": "unknown",
                "windows": [],
            }
            if env != "local":
                value = {
                    **value,
                    "environment_id": env,
                    "environment_name": self.store.get_environment(env)["name"],
                }
            quotas.append(
                {
                    **value,
                    "agent_names": self.store.connection_agent_names(provider, env),
                }
            )
        return {"quotas": quotas}

    @route("GET", r"/api/state")
    def state(self, ids, p, q):
        from .account_service import account_usage

        state = self.store.state(q.get("since"))
        if "accounts" in state:
            with self.store.reader() as reader:
                state["accounts"] = account_usage(reader, state["accounts"])
        connections = set(self.store.configured_connections())
        if "quotas" in state:
            state["quotas"] = [
                self.api._quota(item["provider"], item.get("environment_id", "local"))
                or item
                for item in state["quotas"]
                if (item["provider"], item.get("environment_id", "local"))
                in connections
            ]
        if "subscriptions" in state:
            state["subscriptions"] = [
                item
                for item in state["subscriptions"]
                if (item["provider"], item.get("environment_id", "local"))
                in connections
            ]
        state["runtime"] = {
            "enabled": self.api.execution_enabled,
            "version": __version__,
            "features": self.store.features(),
        }
        return state

    @route("GET", r"/api/tasks/(?P<id>[^/]+)")
    def task(self, ids, p, q):
        result = self.store.task_detail(ids["id"])
        result["can_steer_run_id"] = next(
            (
                run.record["id"]
                for run in getattr(self.runtime, "_runs", {}).copy().values()
                if run.record.get("work_task_id") == ids["id"]
                and run.record.get("task_role") == "owner"
                and run.control.available
                and not run.stop.is_set()
            ),
            None,
        )
        return result

    @route("GET", r"/api/accounts")
    def accounts(self, ids, p, q):
        from .account_service import account_usage

        with self.store.reader() as reader:
            return {"accounts": account_usage(reader, reader.accounts())}

    @route("GET", r"/api/accounts/(?P<id>[^/]+)/login")
    def login_status(self, ids, p, q):
        return self.runtime.accounts.login_status(ids["id"])

    @route("GET", r"/api/accounts/(?P<id>[^/]+)/native", execution=True)
    def native_status(self, ids, p, q):
        return self.runtime.accounts.native_status(ids["id"])

    @route("GET", r"/api/models/(?P<provider>[^/]+)", execution=True)
    def models(self, ids, p, q):
        provider = ids["provider"]
        if provider in ACP_PROVIDERS:
            self.store.require_feature("acp_agents")
        environment = q.get("environment_id", "local")
        if q.get("account_id"):
            account = self.store.get_account(q["account_id"])
            if (
                account["provider"] != provider
                or account["environment_id"] != environment
            ):
                raise Invalid("Account must match this service and device")
            return self.runtime.accounts.models(account, self.api.catalog)
        if environment != "local":
            return self.runtime.remote.models(environment, provider)
        return self.api.catalog.read(provider)

    @route("GET", r"/api/sessions/(?P<id>[^/]+)/events")
    def events(self, ids, p, q):
        return {"events": self.store.session_events(ids["id"], int(q.get("after", 0)))}

    @route("POST", r"/api/tasks")
    def add_task(self, ids, p, q):
        return self.store.create_task(
            p.get("project_id"),
            p.get("title"),
            p.get("goal"),
            p.get("criteria"),
            p.get("owner_id"),
            acceptance_policy=p.get("acceptance_policy", "owner"),
            review_required=p.get("review_required", False),
            workspace_mode=p.get("workspace_mode", "shared"),
            source_session_id=p.get("source_session_id"),
        )

    @route(
        "POST",
        r"/api/tasks/(?P<id>[^/]+)/questions/(?P<question>[^/]+)/answer",
        execution=True,
    )
    def answer(self, ids, p, q):
        return self.runtime.answer_task(ids["id"], ids["question"], p.get("answer"))

    @route(
        "POST",
        r"/api/tasks/(?P<id>[^/]+)/inputs",
        execution=lambda api, p, q: p.get("intent") != "record",
    )
    def task_input(self, ids, p, q):
        return self.runtime.submit_task(
            ids["id"],
            p.get("body"),
            p.get("intent"),
            p.get("request_id"),
            p.get("action", "queue"),
            p.get("expected_run_id"),
        )

    @route("POST", r"/api/tasks/(?P<id>[^/]+)/resume", execution=True)
    def resume(self, ids, p, q):
        return self.runtime.recover_task(
            ids["id"],
            p.get("owner_id"),
            p.get("intent", "develop"),
            p.get("request_id"),
        )

    @route("POST", r"/api/tasks/(?P<id>[^/]+)/(?P<action>pause|cancel)", execution=True)
    def stop_task(self, ids, p, q):
        return self.runtime.stop_task(ids["id"], ids["action"])

    @route("POST", r"/api/tasks/(?P<id>[^/]+)/accept")
    def accept(self, ids, p, q):
        return self.store.accept_task(ids["id"])

    @route("POST", r"/api/tasks/(?P<id>[^/]+)/settings")
    def task_settings(self, ids, p, q):
        return self.store.update_task(
            ids["id"],
            p.get("title"),
            p.get("goal"),
            p.get("criteria"),
            p.get("acceptance_policy"),
            p.get("review_required"),
        )

    @route("POST", r"/api/tasks/(?P<id>[^/]+)/(?P<action>archive|reopen)")
    def task_transition(self, ids, p, q):
        return self.store.task_transition(ids["id"], ids["action"])

    @route("POST", r"/api/accounts")
    def add_account(self, ids, p, q):
        return self.store.add_account(
            p.get("provider"),
            p.get("label"),
            p.get("environment_id", "local"),
            p.get("priority", 0),
        )

    @route("POST", r"/api/accounts/(?P<id>[^/]+)")
    def update_account(self, ids, p, q):
        result = self.store.update_account(ids["id"], p)
        if p.get("enabled") is True and self.api.execution_enabled:
            self.runtime.accounts.check(ids["id"])
            result = self.store.get_account(ids["id"])
        return result

    @route(
        "POST",
        r"/api/accounts/(?P<id>[^/]+)/(?P<action>login|check|refresh|cancel|input|delete|native)",
        execution=True,
    )
    def account_action(self, ids, p, q):
        account_id = ids["id"]
        actions = {
            "login": lambda: self.runtime.accounts.start_login(
                account_id, p.get("method")
            ),
            "check": lambda: self.runtime.accounts.check(account_id),
            "refresh": lambda: self.runtime.accounts.refresh(account_id, force=True),
            "cancel": lambda: self.runtime.accounts.cancel(account_id),
            "input": lambda: self.runtime.accounts.submit(account_id, p.get("code")),
            "delete": lambda: self.runtime.accounts.remove(account_id),
            "native": lambda: self.runtime.accounts.native_action(
                account_id, p.get("operation"), p.get("client")
            ),
        }
        return actions[ids["action"]]()

    @route("POST", r"/api/environments")
    def environment(self, ids, p, q):
        return self.store.add_environment(
            p.get("name"), p.get("ssh_host"), p.get("python", "python3")
        )

    @route("POST", r"/api/environments/(?P<id>[^/]+)/connect", execution=True)
    def connect(self, ids, p, q):
        return self.runtime.remote.connect(ids["id"])

    @route("POST", r"/api/environments/(?P<id>[^/]+)/remove")
    def remove_environment(self, ids, p, q):
        self.store.remove_environment(ids["id"])
        return {"ok": True}

    @route("POST", r"/api/projects")
    def project(self, ids, p, q):
        return self.store.add_project(
            p.get("name"), p.get("path"), p.get("environment_id", "local")
        )

    @route("POST", r"/api/projects/(?P<id>[^/]+)/policy")
    def policy(self, ids, p, q):
        return self.store.update_project_policy(ids["id"], p.get("confirm_dispatch"))

    @route("POST", r"/api/projects/(?P<id>[^/]+)/agents")
    def project_agent(self, ids, p, q):
        return self.store.add_project_agent(ids["id"], p)

    @route("POST", r"/api/agents")
    def add_agent(self, ids, p, q):
        return self.store.add_agent(
            p.get("project_id"),
            p.get("name"),
            p.get("provider"),
            p.get("role", ""),
            p.get("workspace"),
            p.get("model"),
            p.get("effort"),
            p.get("environment_id", "local"),
            p.get("permission_mode", "ask"),
            account_id=p.get("account_id"),
            account_policy=p.get("account_policy", "manual"),
            account_ids=p.get("account_ids"),
            run_timeout=p.get("run_timeout"),
        )

    @route("POST", r"/api/agents/(?P<id>[^/]+)")
    def agent(self, ids, p, q):
        return self.store.update_agent(ids["id"], p)

    @route("POST", r"/api/agents/(?P<id>[^/]+)/delete")
    def delete_agent(self, ids, p, q):
        return self.runtime.delete_agent(ids["id"])

    @route("POST", r"/api/sessions")
    def add_session(self, ids, p, q):
        fields = {
            k: p[k] for k in ("account_id", "account_policy", "account_ids") if k in p
        }
        return self.store.add_session(
            p.get("agent_id"),
            p.get("title"),
            **({"account_settings": fields} if fields else {}),
        )

    @route("POST", r"/api/messages", execution=True)
    def message(self, ids, p, q):
        if p.get("sender_id", "human") != "human":
            raise Forbidden("Human endpoint cannot impersonate an agent")
        return self.runtime.send_message(
            p.get("project_id"),
            p.get("recipient_id"),
            p.get("body"),
            p.get("correlation_id"),
            p.get("idempotency_key"),
            p.get("recipient_session_id"),
        )

    @route("POST", r"/api/memories")
    def memory(self, ids, p, q):
        return self.store.put_memory(
            p.get("project_id"),
            p.get("key"),
            p.get("content"),
            p.get("expected_version"),
        )

    @route("POST", r"/api/subscriptions")
    def subscription(self, ids, p, q):
        return self.store.save_subscription(
            p.get("provider"),
            p.get("plan", ""),
            p.get("renewal_date"),
            p.get("monthly_cost"),
            p.get("currency", "USD"),
            p.get("environment_id", "local"),
        )

    @route("POST", r"/api/quotas/refresh", execution=True)
    def refresh_quota(self, ids, p, q):
        if p.get("environment_id", "local") == "local":
            return self.api.quota.refresh(p.get("provider"))
        return self.api.quota.refresh(
            p.get("provider"), environment_id=p["environment_id"]
        )

    @route("POST", r"/api/sessions/(?P<id>[^/]+)/delete")
    def delete_session(self, ids, p, q):
        return self.runtime.delete_session(ids["id"])

    @route("POST", r"/api/sessions/(?P<id>[^/]+)/settings")
    def session_settings(self, ids, p, q):
        return self.store.update_session_settings(ids["id"], p)

    @route("POST", r"/api/sessions/(?P<id>[^/]+)/account")
    def session_account(self, ids, p, q):
        if set(p) - {"account_id", "account_policy", "account_ids"}:
            raise Invalid("Invalid account settings")
        return self.store.switch_session_account(
            ids["id"],
            p.get("account_id"),
            p.get("account_policy", "manual"),
            p.get("account_ids"),
        )

    @route("POST", r"/api/sessions/(?P<id>[^/]+)/run", execution=True)
    def run(self, ids, p, q):
        return self.runtime.start(ids["id"], p.get("prompt"))

    @route("POST", r"/api/sessions/(?P<id>[^/]+)/cancel", execution=True)
    def cancel_session(self, ids, p, q):
        self.runtime.cancel(ids["id"])
        return {"ok": True}

    @route("POST", r"/api/runs/(?P<id>[^/]+)/cancel", execution=True)
    def cancel_run(self, ids, p, q):
        self.runtime.cancel_run(ids["id"])
        return {"ok": True}

    @route("POST", r"/api/memories/(?P<id>[^/]+)/archive")
    def archive_memory(self, ids, p, q):
        return self.store.archive_memory(ids["id"], p.get("expected_version"))

    @route("POST", r"/api/proposals/(?P<id>[^/]+)/approve")
    def approve_proposal(self, ids, p, q):
        return self.store.approve_proposal(ids["id"], p.get("expected_version"))

    @route("POST", r"/api/proposals/(?P<id>[^/]+)/reject")
    def reject_proposal(self, ids, p, q):
        return self.store.reject_proposal(ids["id"])

    @route("POST", r"/api/approvals/(?P<id>[^/]+)", execution=True)
    def approval(self, ids, p, q):
        self.runtime.approve(ids["id"], p.get("option_id"))
        return {"ok": True}
