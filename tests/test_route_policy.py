import json
import re
import unittest
from unittest.mock import Mock

from agentdock.routes import ROUTES
from agentdock.server import API
from agentdock.store import Store


class RoutePolicyTests(unittest.TestCase):
    def test_every_declared_execution_route_rejects_before_calling_handler(self):
        store = Store(":memory:")
        runtime = Mock()
        api = API(store, runtime, Mock(), "fixture")
        headers = {
            "Host": "127.0.0.1:47831",
            "Authorization": "Bearer fixture",
            "Content-Type": "application/json",
        }
        try:
            paths = set()
            for route in ROUTES:
                self.assertNotIn((route.method, route.pattern), paths)
                paths.add((route.method, route.pattern))
                if route.execution is not True:
                    continue
                path = re.sub(
                    r"\(\?P<\w+>([^)]+)\)",
                    lambda match: (
                        match[1].split("|")[0] if "|" in match[1] else "fixture"
                    ),
                    route.pattern,
                )
                status, body = api.dispatch(route.method, path, headers, b"{}")
                self.assertEqual(
                    (status, body.get("code")), (403, "execution_disabled"), path
                )
            runtime.start.assert_not_called()
            runtime.accounts.start_login.assert_not_called()
        finally:
            store.close()

    def test_dynamic_guards_reject_remote_browse_and_task_execution(self):
        store = Store(":memory:")
        api = API(store, Mock(), Mock(), "fixture")
        headers = {
            "Host": "127.0.0.1:47831",
            "Authorization": "Bearer fixture",
            "Content-Type": "application/json",
        }
        try:
            for method, path, payload in [
                ("GET", "/api/directories?environment_id=remote", {}),
                ("POST", "/api/tasks/fixture/inputs", {"intent": "develop"}),
            ]:
                status, body = api.dispatch(
                    method, path, headers, json.dumps(payload).encode()
                )
                self.assertEqual(
                    (status, body.get("code")), (403, "execution_disabled")
                )
        finally:
            store.close()
