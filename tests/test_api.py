import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from agentdock.mcp import Bridge
from agentdock.server import API
from agentdock.store import Store


class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(":memory:")
        self.runtime = Mock()
        self.quota = Mock()
        self.api = API(self.store, self.runtime, self.quota, "test-admin")
        self.h = {
            "Host": "127.0.0.1:47831",
            "Authorization": "Bearer test-admin",
            "Content-Type": "application/json",
            "Origin": "http://127.0.0.1:47831",
        }

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def call(self, method, path, payload=None, headers=None):
        return self.api.dispatch(
            method,
            path,
            self.h if headers is None else headers,
            json.dumps(payload or {}).encode(),
        )

    def test_project_agent_reuse_requires_human_auth_and_preserves_source(self):
        p = self.store.add_project("Project A", self.tmp.name)
        source = self.store.add_agent(None, "Codex", "codex")
        route = "/api/projects/" + p["id"] + "/agents"
        body = {"source_agent_id": source["id"], "name": "cr", "role": "Review"}
        self.assertEqual(
            self.call(
                "POST", route, body, {**self.h, "Authorization": "Bearer invalid"}
            )[0],
            401,
        )
        status, member = self.call("POST", route, body)
        self.assertEqual(status, 200)
        self.assertEqual(
            (member["project_id"], member["source_agent_id"], member["name"]),
            (p["id"], source["id"], "cr"),
        )
        self.assertEqual(self.store.get_agent(source["id"]), source)
        self.assertEqual(
            self.call("POST", route, {**body, "environment_id": "other"})[0], 400
        )
        self.runtime.start.assert_not_called()

    def test_provider_discovery_is_authenticated_read_only_and_device_specific(self):
        self.runtime.config = {"commands": {}}
        self.assertEqual(
            self.call(
                "GET",
                "/api/providers",
                headers={**self.h, "Authorization": "Bearer wrong"},
            )[0],
            401,
        )
        with (
            patch("agentdock.registry.find_binary", return_value=None),
            patch("subprocess.Popen") as process,
        ):
            status, result = self.call("GET", "/api/providers")
            self.assertEqual(status, 200)
            self.assertEqual(len(result["providers"]), 10)
            self.assertFalse(any(p["available"] for p in result["providers"].values()))
            process.assert_not_called()
        remote = self.store.add_environment("Fixture", "fixture-host")
        self.runtime.remote.digest = "fixture-digest"
        route = "/api/providers?environment_id=" + remote["id"]
        self.assertEqual(
            self.call("GET", route)[1]["providers"]["gemini"]["reason"],
            "connect_required",
        )
        self.store.update_environment_status(
            remote["id"],
            "connected",
            {"digest": "fixture-digest", "providers": {"gemini": {"available": True}}},
        )
        with patch("agentdock.server.availability") as local:
            values = self.call("GET", route)[1]["providers"]
            self.assertTrue(values["gemini"]["available"])
            self.assertIsNone(values["gemini"]["reason"])
            self.assertFalse(values["codex"]["available"])
            local.assert_not_called()
        self.runtime.remote.rpc.assert_not_called()
        self.assertEqual(
            self.call("GET", "/api/providers?environment_id=missing")[0], 404
        )
        status, agent = self.call(
            "POST",
            "/api/agents",
            {
                "name": "My assistant",
                "provider": "gemini",
                "environment_id": remote["id"],
            },
        )
        self.assertEqual(
            (status, agent["provider"], agent["environment_id"]),
            (200, "gemini", remote["id"]),
        )
        self.runtime.start.assert_not_called()

    def test_directory_browsing_is_authenticated_and_routes_to_the_selected_host(self):
        from pathlib import Path
        from urllib.parse import quote

        route = "/api/directories?path=" + quote(self.tmp.name)
        (Path(self.tmp.name) / "project").mkdir()
        status, result = self.call("GET", route)
        self.assertEqual(status, 200)
        self.assertEqual(result["directories"][0]["name"], "project")
        self.assertEqual(
            self.call(
                "GET", route, headers={**self.h, "Authorization": "Bearer invalid"}
            )[0],
            401,
        )
        env = self.store.add_environment("User connection", "user@own-host")
        remote = (
            "/api/directories?environment_id=" + env["id"] + "&path=%2Fremote%2Fproject"
        )
        self.assertEqual(self.call("GET", remote)[0], 403)
        self.api.execution_enabled = True
        self.runtime.remote.digest = "fixture-digest"
        self.assertEqual(self.call("GET", remote)[0], 409)
        self.store.update_environment_status(
            env["id"], "connected", {"digest": "fixture-digest"}
        )
        self.runtime.remote.rpc.return_value = {
            "path": "/remote/project",
            "directories": [],
        }
        self.assertEqual(
            self.call("GET", remote),
            (200, {"path": "/remote/project", "directories": []}),
        )
        self.runtime.remote.rpc.assert_called_once_with(
            env["id"], {"op": "directories", "path": "/remote/project"}
        )

    def test_session_model_settings_require_admin_and_do_not_execute(self):
        agent = self.store.add_agent(None, "A", "codex")
        session = self.store.add_session(agent["id"], "S")
        route = "/api/sessions/" + session["id"] + "/settings"
        status, updated = self.call(
            "POST", route, {"model": "selected-model", "effort": "high"}
        )
        self.assertEqual(
            (status, updated["model"], updated["model_override"]),
            (200, "selected-model", 1),
        )
        self.assertEqual(
            self.call(
                "POST",
                route,
                {"model": "new", "effort": None},
                headers={**self.h, "Authorization": "Bearer invalid"},
            )[0],
            401,
        )
        self.assertEqual(self.call("POST", route, {"effort": "high"})[0], 400)
        self.assertEqual(self.runtime.mock_calls, [])

    def test_auth_host_origin(self):
        for override in (
            {"Authorization": ""},
            {"Host": "evil.example:47831"},
            {"Origin": "https://evil.example"},
            {"Sec-Fetch-Site": "cross-site"},
        ):
            self.assertEqual(
                self.call("GET", "/api/state", headers={**self.h, **override})[0],
                401 if "Authorization" in override else 403,
            )
        status, state = self.call("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertFalse(state["runtime"]["enabled"])
        self.assertNotIn("test-admin", json.dumps(state))

    def test_agent_delete_requires_human_authentication(self):
        self.runtime.delete_agent.return_value = {"ok": True}
        route = "/api/agents/fixture/delete"
        self.assertEqual(
            self.call(
                "POST", route, headers={**self.h, "Authorization": "Bearer invalid"}
            )[0],
            401,
        )
        self.runtime.delete_agent.assert_not_called()
        self.assertEqual(self.call("POST", route), (200, {"ok": True}))
        self.runtime.delete_agent.assert_called_once_with("fixture")

    def test_empty_remote_session_deletion_and_safe_cleanup_errors(self):
        from agentdock.runtime import Runtime

        runtime = Runtime(self.store, {"execution_enabled": True})
        runtime.remote.rpc = Mock(side_effect=OSError("private connection details"))
        self.api.runtime = runtime
        try:
            env = self.store.add_environment("Remote", "fixture")
            agent = self.store.add_agent(None, "A", "codex", environment_id=env["id"])
            empty = self.store.add_session(agent["id"], "Empty")
            route = "/api/sessions/" + empty["id"] + "/delete"
            self.assertEqual(
                self.call(
                    "POST", route, headers={**self.h, "Authorization": "Bearer wrong"}
                )[0],
                401,
            )
            self.assertEqual(self.call("POST", route), (200, {"ok": True}))
            runtime.remote.rpc.assert_not_called()
            used = self.store.add_session(agent["id"], "Used")
            run = self.store.begin_run(used["id"], "Fixture")
            self.store.finish_run(run["id"], "completed")
            code, result = self.call("POST", "/api/sessions/" + used["id"] + "/delete")
            self.assertEqual(code, 409)
            self.assertIn("Check the SSH connection and retry", result["error"])
            self.assertNotIn("private connection details", result["error"])
            self.assertEqual(self.store.get_session(used["id"])["id"], used["id"])
        finally:
            runtime.close()

    def test_review_mode_never_invokes_runtime_or_quota(self):
        self.assertEqual(
            self.call("POST", "/api/quotas/authorize", {"provider": "claude"})[0], 404
        )
        for path in (
            "/api/sessions/x/run",
            "/api/sessions/x/cancel",
            "/api/quotas/refresh",
            "/api/approvals/x",
            "/api/messages",
            "/api/runs/x/cancel",
        ):
            self.assertEqual(
                self.call("POST", path, {"prompt": "go", "provider": "codex"})[0], 403
            )
        self.assertEqual(self.runtime.mock_calls, [])
        self.assertEqual(self.quota.mock_calls, [])

    def test_menu_quota_read_is_authenticated_and_cache_only(self):
        self.assertEqual(
            self.call(
                "GET",
                "/api/quotas",
                headers={**self.h, "Authorization": "Bearer wrong"},
            )[0],
            401,
        )
        self.quota.cached.assert_not_called()
        snapshot = {"provider": "codex", "status": "stale", "windows": []}
        self.store.add_agent(None, "C", "codex")
        self.quota.cached.return_value = snapshot
        status, result = self.call("GET", "/api/quotas")
        self.assertEqual(
            (status, result), (200, {"quotas": [{**snapshot, "agent_names": ["C"]}]})
        )
        self.assertEqual(
            [c.args for c in self.quota.cached.call_args_list], [("codex",)]
        )
        self.quota.refresh.assert_not_called()
        self.assertEqual(self.runtime.mock_calls, [])

    def test_no_agents_hides_saved_provider_data_without_probing(self):
        self.store.set_quota(
            "claude", {"provider": "claude", "status": "available", "windows": []}
        )
        self.store.save_subscription("claude", "Pro")
        self.assertEqual(self.call("GET", "/api/quotas")[1], {"quotas": []})
        state = self.call("GET", "/api/state")[1]
        self.assertEqual(state["quotas"], [])
        self.assertEqual(state["subscriptions"], [])
        self.assertEqual(self.quota.mock_calls, [])
        self.store.add_agent(None, "C", "claude")
        self.assertEqual(self.store.state()["subscriptions"][0]["provider"], "claude")

    def test_interactive_usage_requires_admin_and_valid_provider(self):
        self.api.execution_enabled = True
        self.quota.refresh.return_value = {"status": "available"}
        self.assertEqual(
            self.call("POST", "/api/quotas/authorize", {"provider": "codex"})[0], 404
        )
        self.quota.refresh.assert_not_called()
        self.assertEqual(
            self.call(
                "POST",
                "/api/quotas/authorize",
                {"provider": "claude"},
                {**self.h, "Authorization": "Bearer bad"},
            )[0],
            401,
        )
        self.quota.refresh.assert_not_called()
        self.assertEqual(
            self.call("POST", "/api/quotas/authorize", {"provider": "claude"})[0], 404
        )
        self.quota.refresh.assert_not_called()

    def test_agent_role_updates_work_without_enabling_execution(self):
        _, project = self.call(
            "POST", "/api/projects", {"name": "P", "path": self.tmp.name}
        )
        _, agent = self.call(
            "POST",
            "/api/agents",
            {"project_id": project["id"], "name": "Helper", "provider": "claude"},
        )
        route = "/api/agents/" + agent["id"]
        status, updated = self.call(
            "POST", route, {"name": "Custom specialist", "role": "Implement and test"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            (updated["name"], updated["role"], updated["provider"]),
            ("Custom specialist", "Implement and test", "claude"),
        )
        self.assertEqual(self.call("POST", route, {"role": ""})[1]["role"], "")
        for invalid in ({"provider": "codex"}, {"name": " "}, {"role": None}, {}):
            self.assertEqual(self.call("POST", route, invalid)[0], 400)
        self.assertEqual(
            self.call("POST", "/api/agents/missing", {"role": "Research"})[0], 404
        )
        self.assertEqual(
            self.call(
                "POST",
                route,
                {"role": "Unauthorized"},
                headers={**self.h, "Authorization": "Bearer invalid"},
            )[0],
            401,
        )
        self.assertEqual(self.runtime.mock_calls, [])
        self.assertEqual(self.quota.mock_calls, [])

    def test_permission_settings_require_admin_and_never_start_execution(self):
        for provider in ("codex", "claude"):
            status, agent = self.call(
                "POST",
                "/api/agents",
                {
                    "name": "Helper",
                    "provider": provider,
                    "permission_mode": "full_access",
                },
            )
            self.assertEqual((status, agent["permission_mode"]), (200, "full_access"))
            route = "/api/agents/" + agent["id"]
            self.assertEqual(
                self.call("POST", route, {"permission_mode": "ask"})[1][
                    "permission_mode"
                ],
                "ask",
            )
            for value in (None, "", "full", True, {}):
                self.assertEqual(
                    self.call("POST", route, {"permission_mode": value})[0], 400
                )
                self.assertEqual(
                    self.call(
                        "POST",
                        "/api/agents",
                        {
                            "name": "Invalid",
                            "provider": provider,
                            "permission_mode": value,
                        },
                    )[0],
                    400,
                )
        self.assertEqual(self.runtime.mock_calls, [])

    def test_scoped_tools_cannot_call_human_approval_endpoints(self):
        _, p = self.call("POST", "/api/projects", {"name": "P", "path": self.tmp.name})
        _, a = self.call(
            "POST",
            "/api/agents",
            {"project_id": p["id"], "name": "A", "provider": "codex"},
        )
        _, s = self.call(
            "POST", "/api/sessions", {"agent_id": a["id"], "title": "Task"}
        )
        r = self.store.begin_run(s["id"], "Hi")
        token = self.store.issue_capability(r["id"])
        h = {**self.h, "Authorization": "Bearer " + token}
        status, proposal = self.call(
            "POST",
            "/mcp/tool",
            {
                "name": "memory_propose",
                "arguments": {"key": "Fact", "content": "Value", "expected_version": 0},
            },
            h,
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.call("GET", "/api/state", headers=h)[0], 401)
        self.assertEqual(
            self.call(
                "POST", "/api/agents/" + a["id"], {"role": "Self-assigned authority"}, h
            )[0],
            401,
        )
        self.assertEqual(self.store.get_agent(a["id"])["role"], "")
        self.assertEqual(
            self.call(
                "POST", "/api/agents/" + a["id"], {"permission_mode": "full_access"}, h
            )[0],
            401,
        )
        self.assertEqual(self.store.get_agent(a["id"])["permission_mode"], "ask")
        route = "/api/proposals/" + proposal["id"] + "/approve"
        self.assertEqual(self.call("POST", route, {"expected_version": 0}, h)[0], 401)
        self.assertEqual(self.call("POST", route, {"expected_version": 0})[0], 200)

    def test_human_cannot_impersonate_agent(self):
        self.assertEqual(
            self.call("POST", "/api/messages", {"sender_id": "agent"})[0], 403
        )

    def test_ssh_management_does_not_connect_in_review_mode(self):
        status, env = self.call(
            "POST", "/api/environments", {"name": "Test host", "ssh_host": "test-host"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            self.call("POST", "/api/environments/" + env["id"] + "/connect")[0], 403
        )
        self.assertEqual(
            self.call("GET", "/api/models/codex?environment_id=" + env["id"])[0], 403
        )
        self.assertEqual(self.runtime.mock_calls, [])
        self.api.execution_enabled = True
        self.runtime.remote.connect.return_value = {"status": "connected"}
        self.assertEqual(
            self.call("POST", "/api/environments/" + env["id"] + "/connect")[0], 200
        )
        self.runtime.remote.connect.assert_called_once_with(env["id"])

    def test_remote_quota_routes_never_substitute_local_snapshot(self):
        env = self.store.add_environment("Remote", "test-host")
        self.store.add_agent(None, "Remote Codex", "codex", environment_id=env["id"])
        self.quota.cached.return_value = {
            "provider": "codex",
            "status": "unknown",
            "windows": [],
        }
        status, result = self.call("GET", "/api/quotas")
        self.assertEqual(status, 200)
        self.quota.cached.assert_called_once_with("codex", env["id"])
        self.assertEqual(result["quotas"][0]["environment_name"], "Remote")
        self.api.execution_enabled = True
        self.quota.refresh.return_value = {"status": "unknown"}
        self.assertEqual(
            self.call(
                "POST",
                "/api/quotas/refresh",
                {"provider": "codex", "environment_id": env["id"]},
            )[0],
            200,
        )
        self.quota.refresh.assert_called_once_with("codex", environment_id=env["id"])

    def test_equal_agent_names_keep_distinct_connections_and_sessions(self):
        env = self.store.add_environment("Remote", "test-host")
        local = self.store.add_agent(None, "Helper", "codex")
        remote = self.store.add_agent(None, "Helper", "codex", environment_id=env["id"])
        self.assertNotEqual(local["id"], remote["id"])
        a = self.store.add_session(local["id"], "Conversation")
        b = self.store.add_session(remote["id"], "Conversation")
        self.assertEqual(
            (a["environment_id"], b["environment_id"]), ("local", env["id"])
        )
        self.assertEqual(
            self.store.connection_agent_names("codex", "local"), ["Helper"]
        )
        self.assertEqual(
            self.store.connection_agent_names("codex", env["id"]), ["Helper"]
        )
        self.quota.cached.return_value = {
            "provider": "codex",
            "status": "unknown",
            "windows": [],
        }
        values = self.call("GET", "/api/quotas")[1]["quotas"]
        self.assertEqual(len(values), 2)
        self.assertTrue(all(q["agent_names"] == ["Helper"] for q in values))
        self.store.update_agent(remote["id"], {"name": "Renamed"})
        values = self.call("GET", "/api/quotas")[1]["quotas"]
        self.assertEqual(
            next(q for q in values if q.get("environment_id") == env["id"])[
                "agent_names"
            ],
            ["Renamed"],
        )
        self.assertEqual(
            next(q for q in values if not q.get("environment_id"))["agent_names"],
            ["Helper"],
        )

    def test_content_type_json_size_and_nan(self):
        self.assertEqual(
            self.call(
                "POST",
                "/api/projects",
                headers={**self.h, "Content-Type": "text/plain"},
            )[0],
            400,
        )
        for body in (b"{bad", b" " * 262145, b'{"monthly_cost": NaN}'):
            self.assertEqual(
                self.api.dispatch("POST", "/api/subscriptions", self.h, body)[0], 400
            )


class MCPTests(unittest.TestCase):
    def test_handshake_tools_and_impersonation(self):
        calls = []
        b = Bridge(lambda name, args: calls.append((name, args)) or {"ok": True})
        self.assertIn(
            "error", b.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        )
        r = b.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertIsNone(
            b.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )
        self.assertEqual(
            {
                t["name"]
                for t in b.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})[
                    "result"
                ]["tools"]
            },
            {
                "agent_list",
                "message_send",
                "task_status",
                "memory_search",
                "memory_propose",
                "task_context",
                "task_history",
                "task_result",
                "task_ask",
                "task_deliver",
                "task_review",
            },
        )
        bad = b.handle(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "message_send",
                    "arguments": {
                        "sender_id": "fake",
                        "recipient_id": "x",
                        "body": "Hi",
                    },
                },
            }
        )
        self.assertIn("error", bad)
        self.assertEqual(calls, [])
        r = b.handle(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "agent_list"},
            }
        )
        self.assertFalse(r["result"]["isError"])
        self.assertEqual(calls, [("agent_list", {})])

    def test_private_tool_error_not_returned(self):
        def fail(*args):
            raise ValueError("sk-private-credential")

        b = Bridge(fail)
        b.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        r = b.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "agent_list"},
            }
        )
        self.assertTrue(r["result"]["isError"])
        self.assertNotIn("sk-private", json.dumps(r))


if __name__ == "__main__":
    unittest.main()
