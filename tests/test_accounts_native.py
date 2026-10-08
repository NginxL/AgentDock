import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from agentdock.accounts import (
    AccountError,
    AccountManager,
    _login_hints,
    _login_worker,
    _write,
)

FAKE_CLI = r"""
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
home = Path(os.environ.get('CODEX_HOME') or os.environ['CLAUDE_CONFIG_DIR'])
if 'app-server' in args:
    for line in sys.stdin:
        value = json.loads(line)
        if 'id' not in value: continue
        method = value['method']
        result = {}
        if method == 'account/read':
            result = {'account': {'type':'chatgpt','email':'test@example.com','planType':'plus'}} if (home/'auth.json').exists() else {'account':None}
        if method == 'account/rateLimits/read':
            result = {'rateLimits': {'planType':'plus','primary': {'usedPercent':25,'windowDurationMins':300,'resetsAt':1900000000},'secondary':{'usedPercent':float('nan'),'windowDurationMins':True,'resetsAt':'not a date'}}, 'access_token':'must-not-leak'}
        print(json.dumps({'id':value['id'],'result':result}), flush=True)
elif 'login' in args:
    print('https://evil.example/oauth?access_token=secret', flush=True)
    print('https://auth.openai.com/codex/device', flush=True)
    print('ABCD-1234', flush=True)
    print('raw-secret-token-must-not-be-persisted', flush=True)
    if '--wait' in args: time.sleep(30)
    elif '--input' in args: input()
    else: time.sleep(.3)
    (home/'auth.json').write_text(json.dumps({'tokens':{'access_token':'fixture','refresh_token':'fixture-refresh'}}))
elif 'status' in args:
    print(json.dumps({'loggedIn': True,'authMethod':'claude.ai','email':'test@example.com','subscriptionType':'max','access_token':'must-not-leak'}))
elif 'logout' in args:
    assert os.environ['CLAUDE_SECURESTORAGE_CONFIG_DIR'] == str(home)
    assert home.name == 'claude' and home.parent.parent.name == 'accounts'
    (home/'.credentials.json').unlink(missing_ok=True)
"""


class NativeAccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.fixture = self.root / "native.py"
        self.fixture.write_text(FAKE_CLI)
        self.commands = {
            "codex": [sys.executable, str(self.fixture), "app-server"],
            "claude": [sys.executable, str(self.fixture)],
        }
        self.manager = AccountManager(self.root / "accounts", self.commands)
        self.account = {"id": str(uuid.uuid4()), "provider": "codex"}
        self.claude = {"id": str(uuid.uuid4()), "provider": "claude"}
        self.envpatch = patch.dict(
            os.environ, {"CLAUDE_CONFIG_DIR": str(self.root / "absent")}
        )
        self.envpatch.start()

    def tearDown(self):
        for account in (self.account, self.claude):
            try:
                self.manager.cancel(account)
                deadline = time.monotonic() + 4
                while (
                    self.manager.status(account)["status"]
                    not in ("idle", "completed", "cancelled", "failed")
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.05)
            except (AccountError, OSError):
                pass
        self.envpatch.stop()
        self.tmp.cleanup()

    def wait_status(self, expected):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            status = self.manager.status(self.account)
            if status["status"] in expected:
                return status
            time.sleep(0.04)
        self.fail("Timed out awaiting fake native login: " + str(status))

    def test_environment_drops_routing_and_keys_preserves_proxy_without_global_mutation(
        self,
    ):
        base = {
            "HOME": str(self.root),
            "PATH": os.environ["PATH"],
            "HTTPS_PROXY": "http://localhost:1234",
            "OPENAI_API_KEY": "secret",
            "OPENAI_BASE_URL": "https://relay.example",
            "ANTHROPIC_AUTH_TOKEN": "secret",
            "ANTHROPIC_BASE_URL": "https://relay.example",
            "CLAUDE_CODE_OAUTH_TOKEN": "secret",
            "CODEX_HOME": "/original",
            "CLAUDE_SECURESTORAGE_CONFIG_DIR": "/original",
            "CLAUDE_CONFIG_DIR": str(self.root / "absent"),
        }
        original = dict(base)
        env = self.manager.environment(self.account, base)
        self.assertEqual(base, original)
        self.assertEqual(env["HTTPS_PROXY"], base["HTTPS_PROXY"])
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)
        self.assertNotIn("CLAUDE_SECURESTORAGE_CONFIG_DIR", env)
        self.assertEqual(
            Path(env["CODEX_HOME"]),
            self.root / "accounts" / self.account["id"] / "codex",
        )
        claude = self.manager.environment(self.claude, base)
        self.assertEqual(
            claude["CLAUDE_CONFIG_DIR"], claude["CLAUDE_SECURESTORAGE_CONFIG_DIR"]
        )
        self.assertNotEqual(claude["CLAUDE_CONFIG_DIR"], base["CLAUDE_CONFIG_DIR"])

    def test_proxy_only_inherited_from_native_settings(self):
        settings = self.root / "original"
        settings.mkdir()
        source = {
            "env": {
                "HTTPS_PROXY": "http://localhost:5678",
                "ANTHROPIC_AUTH_TOKEN": "secret",
                "ANTHROPIC_BASE_URL": "https://relay.example",
            },
            "apiKeyHelper": "echo secret",
        }
        (settings / "settings.json").write_text(json.dumps(source))
        env = self.manager.environment(
            self.claude, {"CLAUDE_CONFIG_DIR": str(settings)}
        )
        self.assertEqual(env["HTTPS_PROXY"], "http://localhost:5678")
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)
        self.assertFalse((Path(env["CLAUDE_CONFIG_DIR"]) / "settings.json").exists())
        self.assertEqual(json.loads((settings / "settings.json").read_text()), source)

    def test_identity_provider_symlink_and_permissions(self):
        for identity in ("../outside", str(uuid.uuid4()).upper(), None):
            with self.assertRaises(AccountError):
                self.manager.environment({"id": identity, "provider": "codex"}, {})
        with self.assertRaises(AccountError):
            self.manager.environment(
                {"id": self.account["id"], "provider": "gemini"}, {}
            )
        env = self.manager.environment(self.account, {})
        self.assertEqual(Path(env["CODEX_HOME"]).stat().st_mode & 0o777, 0o700)
        self.assertEqual(
            (Path(env["CODEX_HOME"]) / "config.toml").stat().st_mode & 0o777, 0o600
        )
        with self.assertRaises(AccountError):
            self.manager.environment(dict(self.account, provider="claude"), {})
        second = dict(self.account, id=str(uuid.uuid4()))
        (self.manager.root / second["id"]).symlink_to(self.root)
        with self.assertRaises(AccountError):
            self.manager.environment(second, {})

    def test_trusted_parent_alias_is_allowed(self):
        (self.root / "alias").symlink_to(self.root / "real", target_is_directory=True)
        (self.root / "real").mkdir()
        manager = AccountManager(self.root / "alias" / "accounts", self.commands)
        env = manager.environment(self.account, {})
        self.assertEqual(
            Path(env["CODEX_HOME"]),
            self.root / "real" / "accounts" / self.account["id"] / "codex",
        )
        session_id = str(uuid.uuid4())
        session = self.root / "alias" / "sessions" / session_id / "branches" / "1"
        with manager.credential_session(self.account, session, {}):
            self.assertTrue(
                (
                    self.root
                    / "real"
                    / "sessions"
                    / session_id
                    / "branches"
                    / "1"
                    / "codex"
                ).is_dir()
            )

    def test_trusted_parent_alias_never_hides_internal_session_symlinks(self):
        real = self.root / "real"
        real.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(real, target_is_directory=True)
        manager = AccountManager(alias / "accounts", self.commands)
        source = Path(manager.environment(self.account, {})["CODEX_HOME"])
        _write(source / "auth.json", {"tokens": {"refresh_token": "fixture"}})
        first, other = str(uuid.uuid4()), str(uuid.uuid4())
        first_path, other_path = real / "sessions" / first, real / "sessions" / other
        (other_path / "branches" / "1" / "codex").mkdir(parents=True)
        first_path.mkdir()
        # The previous parent.resolve() rewrote this to the other UUID and
        # accepted its well-formed suffix, silently crossing session ownership.
        (first_path / "branches").symlink_to(
            other_path / "branches", target_is_directory=True
        )
        with self.assertRaisesRegex(AccountError, "symbolic links"):
            with manager.credential_session(
                self.account, alias / "sessions" / first / "branches" / "1", {}
            ):
                self.fail("A session symlink must not receive account credentials")
        self.assertFalse(
            (other_path / "branches" / "1" / "codex" / "auth.json").exists()
        )
        (first_path / "branches").unlink()
        first_path.rmdir()
        first_path.symlink_to(other_path, target_is_directory=True)
        with self.assertRaisesRegex(AccountError, "symbolic links"):
            with manager.credential_session(
                self.account, alias / "sessions" / first / "branches" / "1", {}
            ):
                self.fail("A session symlink must not receive account credentials")
        self.assertFalse(
            (other_path / "branches" / "1" / "codex" / "auth.json").exists()
        )

    def test_session_refresh_atomic_replace_syncs_only_credentials_even_after_failure(
        self,
    ):
        source = Path(self.manager.environment(self.account, {})["CODEX_HOME"])
        _write(source / "auth.json", {"tokens": {"refresh_token": "old"}})
        session = self.root / "sessions" / str(uuid.uuid4())
        with self.assertRaisesRegex(RuntimeError, "fake run failed"):
            with self.manager.credential_session(self.account, session, {}):
                target = session / "codex" / "auth.json"
                self.assertFalse(target.is_symlink())
                self.assertEqual(
                    json.loads(target.read_text())["tokens"]["refresh_token"], "old"
                )
                _write(target, {"tokens": {"refresh_token": "new"}})
                (session / "codex" / "history.jsonl").write_text("conversation")
                raise RuntimeError("fake run failed")
        self.assertEqual(
            json.loads((source / "auth.json").read_text())["tokens"]["refresh_token"],
            "new",
        )
        self.assertFalse((source / "history.jsonl").exists())
        self.assertFalse((session / "codex" / "auth.json").exists())
        self.assertEqual((source / "auth.json").stat().st_mode & 0o777, 0o600)

    def test_claude_account_keychain_identity_survives_session_history_isolation(self):
        source = Path(self.manager.environment(self.claude, {})["CLAUDE_CONFIG_DIR"])
        _write(source / ".credentials.json", {"claudeAiOauth": {"refreshToken": "old"}})
        session = self.root / "sessions" / str(uuid.uuid4())
        with self.manager.credential_session(self.claude, session, {}) as env:
            self.assertEqual(env["CLAUDE_SECURESTORAGE_CONFIG_DIR"], str(source))
            _write(
                session / "claude" / ".credentials.json",
                {"claudeAiOauth": {"refreshToken": "new"}},
            )
        self.assertEqual(
            json.loads((source / ".credentials.json").read_text())["claudeAiOauth"][
                "refreshToken"
            ],
            "new",
        )
        self.assertFalse((session / "claude" / ".credentials.json").exists())

    def test_parent_crash_recovers_latest_native_refresh_before_next_probe(self):
        source = Path(self.manager.environment(self.account, {})["CODEX_HOME"])
        _write(source / "auth.json", {"tokens": {"refresh_token": "old"}})
        session = self.root / "sessions" / str(uuid.uuid4())
        program = """import json, os, sys
from pathlib import Path
from agentdock.accounts import AccountManager, _write
manager=AccountManager(sys.argv[1])
with manager.credential_session(json.loads(sys.argv[2]),sys.argv[3],{}) as env:
    _write(Path(sys.argv[3])/'codex'/'auth.json',{'tokens':{'refresh_token':'new'}})
    os._exit(0)
"""
        subprocess.run(
            [
                sys.executable,
                "-c",
                program,
                str(self.manager.root),
                json.dumps(self.account),
                str(session),
            ],
            check=True,
            timeout=5,
        )
        self.assertEqual(
            json.loads((source / "auth.json").read_text())["tokens"]["refresh_token"],
            "old",
        )
        self.assertEqual(self.manager.check(self.account)["status"], "ready")
        self.assertEqual(
            json.loads((source / "auth.json").read_text())["tokens"]["refresh_token"],
            "new",
        )
        self.assertFalse((source.parent / ".pending-session.json").exists())
        self.assertFalse((session / "codex" / "auth.json").exists())

    def test_inherited_lease_blocks_recovery_while_orphan_native_process_is_alive(self):
        session = self.root / "sessions" / str(uuid.uuid4())
        program = """import json, os, subprocess, sys
from agentdock.accounts import AccountManager
manager=AccountManager(sys.argv[1])
with manager.credential_session(json.loads(sys.argv[2]),sys.argv[3],{}) as env:
    subprocess.Popen([sys.executable,'-c','import time; time.sleep(.6)'],
       pass_fds=(int(env['AGENTDOCK_ACCOUNT_LOCK_FD']),),stdin=subprocess.DEVNULL,
       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    os._exit(0)
"""
        subprocess.run(
            [
                sys.executable,
                "-c",
                program,
                str(self.manager.root),
                json.dumps(self.account),
                str(session),
            ],
            check=True,
            timeout=5,
        )
        with self.assertRaisesRegex(AccountError, "busy"):
            with self.manager.lease(self.account, timeout=0):
                pass
        with self.manager.lease(self.account, timeout=2):
            pass
        self.assertFalse(
            (self.manager.root / self.account["id"] / ".pending-session.json").exists()
        )

    def test_committed_journal_never_removes_already_published_refresh(self):
        source = Path(self.manager.environment(self.account, {})["CODEX_HOME"])
        _write(source / "auth.json", {"tokens": {"refresh_token": "new"}})
        target = self.root / "sessions" / str(uuid.uuid4()) / "codex"
        target.mkdir(parents=True)
        _write(
            source.parent / ".pending-session.json",
            {
                "provider": "codex",
                "phase": "committed",
                "target": str(target.relative_to(self.root)),
                "source_hashes": {"auth.json": "old-hash"},
            },
        )
        with self.manager.lease(self.account):
            pass
        self.assertEqual(
            json.loads((source / "auth.json").read_text())["tokens"]["refresh_token"],
            "new",
        )

    def test_recovery_rejects_paths_outside_managed_sessions(self):
        source = Path(self.manager.environment(self.account, {})["CODEX_HOME"])
        _write(
            source.parent / ".pending-session.json",
            {
                "provider": "codex",
                "phase": "copying",
                "target": "../native/codex",
                "source_hashes": {"auth.json": None},
            },
        )
        with self.assertRaises(AccountError):
            with self.manager.lease(self.account):
                pass
        (source.parent / ".pending-session.json").unlink()

    def test_session_credential_symlink_is_rejected_without_touching_target(self):
        source = Path(self.manager.environment(self.account, {})["CODEX_HOME"])
        _write(source / "auth.json", {"token": "owned"})
        outside = self.root / "outside.json"
        outside.write_text('{"secret":"external"}')
        session = self.root / "sessions" / str(uuid.uuid4())
        (session / "codex").mkdir(parents=True)
        (session / "codex" / "auth.json").symlink_to(outside)
        with self.assertRaises(AccountError):
            with self.manager.credential_session(self.account, session, {}):
                pass
        self.assertEqual(outside.read_text(), '{"secret":"external"}')

    def test_lock_serializes_same_account_but_not_other_accounts_and_cancels(self):
        other = dict(self.account, id=str(uuid.uuid4()))
        with self.manager.lease(self.account):
            with self.assertRaisesRegex(AccountError, "busy"):
                with self.manager.lease(self.account, timeout=0.01):
                    pass
            with self.manager.lease(other, timeout=0):
                pass
            stop = threading.Event()
            stop.set()
            with self.assertRaisesRegex(AccountError, "cancelled"):
                with self.manager.lease(self.account, stop=stop):
                    pass

    def test_account_lock_is_shared_between_independent_processes(self):
        program = """import json, sys
from agentdock.accounts import AccountManager, AccountError
manager=AccountManager(sys.argv[1])
try:
    with manager.lease(json.loads(sys.argv[2]),timeout=0): print('acquired')
except AccountError: print('busy')
"""
        command = [
            sys.executable,
            "-c",
            program,
            str(self.manager.root),
            json.dumps(self.account),
        ]
        with self.manager.lease(self.account):
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=5, check=True
            )
            self.assertEqual(result.stdout.strip(), "busy")
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=5, check=True
        )
        self.assertEqual(result.stdout.strip(), "acquired")

    def test_managed_login_rejects_api_key_identity_and_masks_cli_errors(self):
        with patch.object(
            self.manager,
            "_codex",
            return_value={"account": {"type": "apiKey", "email": "key-secret"}},
        ):
            self.assertEqual(
                self.manager.check(self.account),
                {
                    "status": "login_required",
                    "logged_in": False,
                    "email": None,
                    "plan": None,
                },
            )
        self.manager.commands_config["claude"] = [
            sys.executable,
            "-c",
            'print("access-token-should-never-appear")',
        ]
        with self.assertRaises(AccountError) as caught:
            self.manager.check(self.claude)
        self.assertNotIn("access-token", str(caught.exception))

    def test_codex_status_and_quota_use_native_protocol_without_model_request(self):
        self.assertEqual(self.manager.check(self.account)["status"], "login_required")
        source = Path(self.manager.environment(self.account, {})["CODEX_HOME"])
        _write(source / "auth.json", {"tokens": {"access_token": "fixture"}})
        result = self.manager.refresh(self.account)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["email"], "test@example.com")
        self.assertEqual(result["windows"][0]["used_percent"], 25)
        self.assertIsNone(result["windows"][1]["used_percent"])
        self.assertIsNone(result["windows"][1]["duration_mins"])
        self.assertNotIn("must-not-leak", json.dumps(result))

    def test_claude_status_quota_unknown_does_not_guess(self):
        with (
            patch("agentdock.accounts.claude_network", return_value={}),
            patch("agentdock.account_keychain.claude_credentials", return_value={}),
        ):
            result = self.manager.refresh(self.claude)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["error_code"], "quota_unavailable")
        self.assertEqual(result["windows"], [])
        self.assertNotIn("must-not-leak", json.dumps(result))

    def test_hints_reject_tokens_untrusted_hosts_and_control_output(self):
        text = "https://evil.example/oauth\nhttps://auth.openai.com/oauth?access_token=secret\nhttps://claude.ai/oauth/authorize?state=abc\nABCD-1234\nrawsecret"
        self.assertEqual(
            _login_hints(text),
            {
                "url": "https://claude.ai/oauth/authorize?state=abc",
                "device_code": "ABCD-1234",
            },
        )
        self.assertEqual(
            _login_hints(
                "https://auth.openai.com.evil.example/oauth\nhttps://secret@claude.ai/oauth\nhttps://claude.ai:123/oauth"
            ),
            {},
        )

    def test_detached_login_completes_and_never_persists_output(self):
        job = self.manager.start(self.account, "device")
        self.assertNotIn("command", job)
        result = self.wait_status({"completed", "failed"})
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("url", result)
        persisted = (self.manager.root / self.account["id"] / "login.json").read_text()
        self.assertNotIn("raw-secret", persisted)
        self.assertNotIn("fixture", persisted)
        self.assertEqual(self.manager.check(self.account)["status"], "ready")

    def test_delayed_login_worker_cannot_overwrite_replacement_job(self):
        self.manager.environment(self.account, {})
        home = self.manager.root / self.account["id"]
        old = {"id": str(uuid.uuid4()), "status": "starting"}
        replacement = {"id": str(uuid.uuid4()), "status": "starting"}
        _write(home / "login.json", old)

        @contextmanager
        def delayed_lease(*args, **kwargs):
            _write(home / "login.json", replacement)
            yield 100

        with (
            patch.object(AccountManager, "lease", delayed_lease),
            patch("agentdock.accounts.subprocess.Popen") as launch,
        ):
            _login_worker(str(self.manager.root), self.account["id"], old["id"])
            launch.assert_not_called()
        self.assertEqual(json.loads((home / "login.json").read_text()), replacement)
        _write(home / "login.json", {"status": "cancelled"})

    def test_detached_login_url_cancel_and_input_do_not_target_other_account(self):
        self.manager.commands_config["codex"] = [
            sys.executable,
            str(self.fixture),
            "--wait",
            "app-server",
        ]
        self.manager.start(self.account)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            state = self.manager.status(self.account)
            if state.get("url"):
                break
            time.sleep(0.04)
        self.assertEqual(state["url"], "https://auth.openai.com/codex/device")
        self.assertEqual(state["device_code"], "ABCD-1234")
        with self.assertRaises(AccountError):
            self.manager.start(self.account)
        with self.assertRaises(AccountError):
            self.manager.remove(self.account)
        self.manager.cancel(self.account)
        self.assertEqual(
            self.wait_status({"cancelled", "failed"})["status"], "cancelled"
        )
        self.assertEqual(self.manager.status(self.claude)["status"], "idle")

    def test_detached_login_confirmation_input(self):
        self.manager.commands_config["codex"] = [
            sys.executable,
            str(self.fixture),
            "--input",
            "app-server",
        ]
        self.manager.start(self.account)
        self.wait_status({"waiting"})
        with self.assertRaises(AccountError):
            self.manager.submit(self.account, "abc\nexec bad")
        self.manager.submit(self.account, "fixture-oauth-code")
        self.assertEqual(
            self.wait_status({"completed", "failed"})["status"], "completed"
        )
        self.assertFalse(list((self.manager.root / self.account["id"]).glob("input-*")))

    def test_remove_never_traverses_credential_symlinks_or_other_profiles(self):
        own = Path(self.manager.environment(self.account, {})["CODEX_HOME"])
        other = Path(self.manager.environment(self.claude, {})["CLAUDE_CONFIG_DIR"])
        (other / "retained").write_text("keep")
        (own / "auth.json").symlink_to(other / "retained")
        self.manager.remove(self.account)
        self.assertFalse(own.parent.exists())
        self.assertEqual((other / "retained").read_text(), "keep")

    def test_claude_remove_uses_native_account_scoped_logout(self):
        own = Path(self.manager.environment(self.claude, {})["CLAUDE_CONFIG_DIR"])
        _write(
            own / ".credentials.json", {"claudeAiOauth": {"refreshToken": "fixture"}}
        )
        self.manager.remove(self.claude)
        self.assertFalse(own.parent.exists())

    def test_never_prepared_claude_account_can_be_removed_without_cli(self):
        # A UI poll may have created AgentDock metadata, but no native command
        # has been prepared and the provider home has never existed.
        self.assertEqual(self.manager.status(self.claude), {"status": "idle"})
        with patch.object(
            self.manager, "_command", side_effect=AccountError("CLI unavailable")
        ) as command:
            self.manager.remove(dict(self.claude, generation=0))
            command.assert_not_called()
        self.assertFalse((self.manager.root / self.claude["id"]).exists())

    def test_claude_native_home_without_file_still_requires_keychain_logout(self):
        native = Path(self.manager.environment(self.claude, {})["CLAUDE_CONFIG_DIR"])
        self.assertFalse((native / ".credentials.json").exists())
        with patch.object(
            self.manager, "_command", side_effect=AccountError("CLI unavailable")
        ) as command:
            with self.assertRaisesRegex(AccountError, "CLI unavailable"):
                self.manager.remove(dict(self.claude, generation=0))
            command.assert_called_once()
        self.assertTrue(native.parent.exists())

    def test_claude_previous_login_generation_requires_logout_when_home_is_missing(
        self,
    ):
        with patch.object(
            self.manager, "_command", side_effect=AccountError("CLI unavailable")
        ) as command:
            with self.assertRaisesRegex(AccountError, "CLI unavailable"):
                self.manager.remove(dict(self.claude, generation=1))
            command.assert_called_once()
        self.assertTrue((self.manager.root / self.claude["id"]).exists())

    def test_claude_quota_reads_own_oauth_and_reports_actual_windows(self):
        self.manager.environment(self.claude, {})
        with (
            patch(
                "agentdock.accounts.claude_network",
                return_value={"HTTPS_PROXY": "http://existing-proxy"},
            ),
            patch(
                "agentdock.account_keychain.claude_credentials",
                return_value={"claudeAiOauth": {"accessToken": "private"}},
            ),
            patch(
                "agentdock.accounts.claude_get",
                return_value={
                    "five_hour": {
                        "utilization": 15,
                        "resets_at": "2030-01-01T00:00:00Z",
                    },
                    "seven_day": {"utilization": 40},
                    "seven_day_sonnet": {"utilization": None},
                },
            ) as query,
        ):
            value = self.manager.refresh(self.claude)
        self.assertEqual([w["duration_mins"] for w in value["windows"]], [300, 10080])
        query.assert_called_once_with(
            "usage", "private", {"HTTPS_PROXY": "http://existing-proxy"}
        )
        self.assertNotIn("private", json.dumps(value))

    def test_failed_native_logout_retains_account_and_safe_error(self):
        own = Path(self.manager.environment(self.claude, {})["CLAUDE_CONFIG_DIR"])
        self.manager.commands_config["claude"] = [
            sys.executable,
            "-c",
            'import sys; print("secret-token"); sys.exit(1)',
        ]
        with self.assertRaisesRegex(AccountError, "retained") as caught:
            self.manager.remove(self.claude)
        self.assertNotIn("secret-token", str(caught.exception))
        self.assertTrue(own.exists())


if __name__ == "__main__":
    unittest.main()
