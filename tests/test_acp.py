import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from agentdock.acp_home import prepare
from agentdock.catalog import Catalog
from agentdock.providers import ProviderCancelled, ProviderError, execute
from agentdock.registry import ACP_PROVIDERS, acp_command, availability, commands
from agentdock.runtime import Runtime
from agentdock.store import Store

FIXTURE = str(Path(__file__).with_name("fake_acp.py"))


class ACPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.events, self.bound, self.approvals = [], [], []
        self.stop = threading.Event()
        self.native_environment = {"HOME": str(self.root / "native-empty")}

    def tearDown(self):
        self.tmp.cleanup()

    def run_agent(
        self,
        provider="gemini",
        scenario="normal",
        native=None,
        permission="ask",
        **extra,
    ):
        def approve(request, options):
            self.approvals.append((request, options))
            return options[0]["optionId"]

        extra.setdefault("base_environment", self.native_environment)
        return execute(
            provider,
            [sys.executable, FIXTURE, scenario],
            self.tmp.name,
            "fixture prompt",
            native,
            {
                "command": sys.executable,
                "args": ["-m", "agentdock.mcp"],
                "env": {"AGENTDOCK_CAPABILITY": "private-token"},
            },
            self.stop,
            lambda kind, payload: self.events.append((kind, payload)),
            self.bound.append,
            approve,
            permission_mode=permission,
            session_home=str(self.root / "session"),
            **extra,
        )

    def test_each_acp_provider_runs_and_resumes_without_replaying_history(self):
        for provider in sorted(ACP_PROVIDERS):
            with self.subTest(provider=provider):
                self.events.clear()
                self.approvals.clear()
                permission = "full_access" if provider == "pi" else "ask"
                self.assertEqual(
                    self.run_agent(provider, permission=permission), "Final answer"
                )
                native = self.bound[-1]
                self.assertEqual(
                    self.run_agent(provider, native=native, permission=permission),
                    "Final answer",
                )
                self.assertEqual(native, self.bound[-1])
                self.assertNotIn("OLD", json.dumps(self.events))
                self.assertEqual(self.approvals, [])
                self.assertTrue(
                    (
                        self.root / "session" / provider / "private-session.json"
                    ).is_file()
                )

    def test_progress_final_model_and_usage_semantics(self):
        self.assertEqual(
            self.run_agent(model="fixture-model", effort="high"), "Final answer"
        )
        kinds = [kind for kind, _ in self.events]
        self.assertIn("model_info", kinds)
        self.assertIn("reasoning_chunk", kinds)
        self.assertIn("tool_result", kinds)
        self.assertIn("context_usage", kinds)
        self.assertNotIn("usage", kinds)
        messages = [v for k, v in self.events if k == "agent_message"]
        self.assertEqual([m["phase"] for m in messages], ["commentary", "final_answer"])

    def test_discussion_negotiates_plan_mode_or_stops_before_prompt(self):
        with self.assertRaisesRegex(ProviderError, "read-only planning mode"):
            self.run_agent(permission="read_only")
        self.assertFalse(any(kind == "agent_message" for kind, _ in self.events))
        self.assertEqual(
            self.run_agent(scenario="read_only", permission="read_only"), "Final answer"
        )

    def test_custom_native_roots_are_read_only_and_runtime_roots_are_private(self):
        for provider, key, relative, filename in (
            ("qwen", "QWEN_HOME", ".qwen", "settings.json"),
            ("pi", "PI_CODING_AGENT_DIR", ".pi/agent", "auth.json"),
            ("grok", "GROK_HOME", ".grok", "config.toml"),
            ("cursor", "CURSOR_CONFIG_DIR", ".cursor", "cli-config.json"),
            ("opencode", "XDG_DATA_HOME", ".local/share", "opencode/auth.json"),
        ):
            with self.subTest(provider=provider):
                native = self.root / "native" / provider
                (native / filename).parent.mkdir(parents=True)
                (native / filename).write_text("private settings")
                target = self.root / "owned" / provider
                env = prepare(
                    provider,
                    target,
                    {
                        "HOME": str(self.root / "empty"),
                        key: str(native),
                        "QWEN_RUNTIME_DIR": str(native),
                        "GROK_LOG_FILE": str(native / "log"),
                    },
                )
                self.assertEqual(
                    (target / relative / filename).read_text(), "private settings"
                )
                self.assertEqual(env[key], str(target / relative))
                self.assertEqual(env["QWEN_RUNTIME_DIR"], str(target / ".qwen"))
                self.assertNotIn("GROK_LOG_FILE", env)
                (target / relative / filename).write_text("changed private copy")
                self.assertEqual((native / filename).read_text(), "private settings")

    def test_trae_launch_forms_are_detected_without_starting_a_prompt(self):
        for help_output, suffix in (
            ("  serve   Start ACP server", ["serve", "--permission-mode", "default"]),
            ("Usage: traecli acp [OPTIONS]", []),
        ):
            binary = self.root / "traecli"
            binary.write_text(
                "#!" + sys.executable + "\nimport sys\n"
                'assert sys.argv[1:] == ["acp", "--help"]\n'
                f"print({help_output!r})\n"
            )
            binary.chmod(0o700)
            self.assertEqual(
                acp_command(
                    "trae",
                    [str(binary), "acp"],
                    self.tmp.name,
                    dict(os.environ),
                    self.stop,
                ),
                [str(binary), "acp", *suffix],
            )
        custom = [sys.executable, "custom-wrapper.py"]
        self.assertEqual(
            acp_command("trae", custom, self.tmp.name, {}, self.stop), custom
        )

    def test_quota_without_an_official_reader_is_unknown_without_a_probe(self):
        from agentdock.quota import QuotaService

        store = Store(":memory:")
        service = QuotaService(store, ["must-not-run"], True)
        try:
            remote = store.add_environment("Fixture", "fixture-host")
            for environment in ("local", remote["id"]):
                store.add_agent(None, "Gemini", "gemini", environment_id=environment)
                with (
                    patch.object(service, "_probe") as probe,
                    patch.object(service, "_remote_refresh") as ssh,
                ):
                    value = service.refresh("gemini", environment_id=environment)
                    self.assertEqual(
                        (value["status"], value["windows"]), ("unknown", [])
                    )
                    probe.assert_not_called()
                    ssh.assert_not_called()
        finally:
            service.close()
            store.close()

    def test_permission_policy_and_unsupported_client_calls(self):
        self.run_agent(scenario="permission")
        self.assertEqual(len(self.approvals), 1)
        self.approvals.clear()
        self.run_agent(scenario="full_access", permission="full_access")
        self.assertEqual(self.approvals, [])
        self.assertEqual(self.run_agent(scenario="unsupported"), "Final answer")
        with self.assertRaisesRegex(ProviderError, "full access"):
            self.run_agent(provider="pi")

    def test_failures_never_fall_back_to_new_conversations_or_report_success(self):
        for scenario in ("no_resume", "foreign", "version", "incomplete", "error"):
            with (
                self.subTest(scenario=scenario),
                self.assertRaises(ProviderError) as caught,
            ):
                self.run_agent(
                    scenario=scenario,
                    native="fixture-session" if scenario == "no_resume" else None,
                )
            self.assertNotIn("private-token", str(caught.exception))
        with self.assertRaisesRegex(ProviderError, "not supported"):
            self.run_agent(model="not-offered")
        with self.assertRaisesRegex(ProviderError, "timed out"):
            self.run_agent(scenario="hang", timeout=0.25)
        self.stop.set()
        with self.assertRaises(ProviderCancelled):
            self.run_agent()

    def test_model_discovery_is_cached_isolated_and_never_prompts(self):
        catalog = Catalog(
            {
                "execution_enabled": True,
                "commands": {"gemini": [sys.executable, FIXTURE, "normal"]},
            }
        )
        try:
            value = catalog.read("gemini", environment=self.native_environment)
            self.assertEqual(
                value["models"],
                [{"id": "fixture-model", "name": "Fixture model", "efforts": ["high"]}],
            )
            with patch("agentdock.catalog._Pipe") as pipe:
                self.assertEqual(
                    catalog.read("gemini", environment=self.native_environment), value
                )
                pipe.assert_not_called()
        finally:
            catalog.close()

    def test_acp_options_round_trip_without_changing_native_provider_validation(self):
        from agentdock.store import Invalid

        store = Store(":memory:")
        try:
            agent = store.add_agent(
                None, "Pi", "pi", model="vendor/model:default", effort="off"
            )
            session = store.add_session(agent["id"], "Settings")
            settings = store.update_session_settings(
                session["id"], {"model": "vendor/model:default", "effort": "adaptive"}
            )
            self.assertEqual(settings["effort"], "adaptive")
            self.assertEqual(
                store.update_agent(agent["id"], {"effort": "off"})["effort"], "off"
            )
            with self.assertRaises(Invalid):
                store.add_agent(None, "Codex", "codex", effort="adaptive")
            with self.assertRaises(Invalid):
                store.add_agent(None, "Pi", "pi", effort="bad\x00option")
        finally:
            store.close()

    def test_private_home_preserves_auth_and_settings_without_importing_history(self):
        native = self.root / "native"
        (native / ".gemini").mkdir(parents=True)
        (native / ".gemini/settings.json").write_text('{"model":"test"}')
        (native / ".gemini/oauth_creds.json").write_text('{"token":"private"}')
        (native / ".gemini/history.json").write_text("must not copy")
        target = self.root / "owned"
        environment = {
            "HOME": str(native),
            "HTTPS_PROXY": "http://127.0.0.1:1080",
            "GEMINI_CLI_IDE_PID": "123",
        }
        result = prepare("gemini", target, environment)
        self.assertEqual(result["HOME"], str(target))
        self.assertEqual(result["GEMINI_CLI_HOME"], str(target))
        self.assertEqual(result["HTTPS_PROXY"], environment["HTTPS_PROXY"])
        self.assertNotIn("GEMINI_CLI_IDE_PID", result)
        self.assertFalse((target / ".gemini/history.json").exists())
        copied = target / ".gemini/oauth_creds.json"
        self.assertEqual(copied.stat().st_mode & 0o777, 0o600)
        copied.write_text("refreshed")
        prepare("gemini", target, environment)
        self.assertEqual(copied.read_text(), "refreshed")
        self.assertEqual(
            (native / ".gemini/oauth_creds.json").read_text(), '{"token":"private"}'
        )

    def test_provider_detection_does_not_start_or_install_commands(self):
        with (
            patch(
                "agentdock.registry.find_binary",
                side_effect=lambda name: (
                    "/usr/bin/true" if name in ("gemini", "/usr/bin/true") else None
                ),
            ),
            patch("subprocess.Popen") as process,
        ):
            found = availability()
            self.assertTrue(found["gemini"]["available"])
            self.assertNotIn("picode", found)
            self.assertEqual(found["pi"]["reason"], "adapter_required")
            self.assertEqual(commands()["gemini"], ["/usr/bin/true", "--acp"])
            process.assert_not_called()
        with self.assertRaises(ValueError):
            commands({"not-a-provider": ["example"]})

    def test_new_provider_session_deletion_never_retires_native_claude_history(self):
        store = Store(self.root / "dock.sqlite3")
        runtime = Runtime(store, {"execution_enabled": False})
        try:
            agent = store.add_agent(None, "Gemini", "gemini")
            session = store.add_session(agent["id"], "Test")
            store.bind_native_session(session["id"], "fixture-session")
            directory = store.session_directory(session["id"])
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "owned").write_text("record")
            with patch("agentdock.session_storage.retire_legacy_claude") as retire:
                runtime.delete_session(session["id"])
                retire.assert_not_called()
            self.assertFalse(directory.exists())
        finally:
            runtime.close()
            store.close()


if __name__ == "__main__":
    unittest.main()
