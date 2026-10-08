import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import zipfile

from agentdock import diagnostics
from agentdock.server import API
from agentdock.store import Store


class DiagnosticsTests(unittest.TestCase):
    def test_exception_messages_prompts_and_tokens_never_reach_logs_or_export(self):
        canaries = ['admin-secret-fixture', 'run-capability-fixture', 'Prompt text should stay private']
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'state.sqlite3')
            api = API(store, Mock(), Mock(), canaries[0])
            try:
                logs = diagnostics.configure(directory)
                store.state = Mock(side_effect=RuntimeError(' '.join(canaries)))
                status, result = api.dispatch('GET', '/api/state',
                    {'Host': '127.0.0.1:47831', 'Authorization': 'Bearer ' + canaries[0]})
                self.assertEqual(status, 500)
                self.assertEqual(result['code'], 'internal_error')
                self.assertRegex(result['error_id'], '^[a-f0-9]{16}$')
                raw = (logs / 'agentdock.jsonl').read_text()
                self.assertIn(result['error_id'], raw)
                self.assertEqual((logs / 'agentdock.jsonl').stat().st_mode & 0o777, 0o600)
                package = diagnostics.export(store)
                with zipfile.ZipFile(io.BytesIO(base64.b64decode(package['data']))) as archive:
                    self.assertEqual(set(archive.namelist()), {'system.json', 'errors.jsonl'})
                    contents = '\n'.join(archive.read(name).decode() for name in archive.namelist())
                for canary in canaries:
                    self.assertNotIn(canary, raw + contents + json.dumps(result))
                self.assertNotIn(directory, contents)
            finally:
                api.close()
                store.close()
                for handler in diagnostics._logger.handlers[:]:
                    handler.close()
                    diagnostics._logger.removeHandler(handler)
