"""Read local CLI model capabilities without submitting a prompt."""
import os
import threading
import time
from pathlib import Path
from .providers import _Pipe, _Codex, _Callbacks, ProviderError
from .store import Forbidden


class Catalog:
    def __init__(self, config):
        self.config, self.cache = config, {}
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def close(self):
        self.stop.set()
        with self.lock: pass

    def read(self, provider):
        if not self.config.get('execution_enabled'): raise Forbidden('Execution is disabled for review')
        if provider not in ('codex', 'claude'): raise ValueError('Unsupported provider')
        with self.lock:
            stamp, value = self.cache.get(provider, (0, None))
            if value and time.monotonic() - stamp < 300: return value
            command = self.config.get('commands', {}).get(provider)
            if not isinstance(command, list) or not command: raise ValueError('Native CLI is not configured')
            argv = command + (['--listen', 'stdio://'] if provider == 'codex' else
                ['--print', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose'])
            pipe = _Pipe(argv, str(Path.home()), dict(os.environ), self.stop, 25)
            try:
                if provider == 'codex':
                    adapter = _Codex(pipe, _Callbacks(pipe, lambda *a: None, lambda *a: None, lambda *a: None, {}))
                    adapter.request('initialize', {'clientInfo': {'name': 'agentdock', 'version': '0.3.0'}})
                    pipe.send({'method': 'initialized', 'params': {}})
                    raw, cursor = [], None
                    for _ in range(5):
                        result = adapter.request('model/list', {'limit': 100, 'includeHidden': False, **({'cursor': cursor} if cursor else {})})
                        raw.extend(result.get('data', [])); cursor = result.get('nextCursor')
                        if not cursor: break
                    models = [{'id': m.get('model'), 'name': m.get('displayName', m.get('model')), 'efforts': [v.get('reasoningEffort') for v in m.get('supportedReasoningEfforts', [])]} for m in raw if isinstance(m, dict)]
                else:
                    pipe.send({'type': 'control_request', 'request_id': 'catalog', 'request': {'subtype': 'initialize', 'hooks': None}})
                    while True:
                        message = pipe.next()
                        if message.get('type') == 'control_response':
                            response = message.get('response', {})
                            if response.get('request_id') != 'catalog' or response.get('subtype') != 'success': raise ProviderError('Model discovery failed')
                            raw = response.get('response', {}).get('models', [])
                            break
                    models = [{'id': m.get('value'), 'name': m.get('displayName', m.get('value')), 'efforts': m.get('supportedEffortLevels', [])} for m in raw if isinstance(m, dict)]
                # Whitelist metadata: initialize may also return private account information.
                models = [m for m in models if isinstance(m['id'], str) and len(m['id']) <= 160 and isinstance(m['name'], str) and isinstance(m['efforts'], list) and all(isinstance(e, str) and len(e) <= 32 for e in m['efforts'])][:100]
                value = {'provider': provider, 'models': models}
                self.cache[provider] = (time.monotonic(), value)
                return value
            finally:
                pipe.close()
