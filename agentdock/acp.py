"""ACP v1 stdio client. No model request is sent during capability discovery."""
import time
import uuid

from .providers import ProviderError, ProviderCancelled, _MAX_RESULT


def identifier(value):
    # ACP identifiers are opaque, sometimes file paths. Never use them as paths.
    return isinstance(value, str) and 0 < len(value) <= 512 and not any(ord(c) < 32 for c in value)


def values(option):
    result = []
    for value in option.get('options', []) if isinstance(option.get('options'), list) else []:
        if not isinstance(value, dict): continue
        group = value.get('options') if 'group' in value else [value]
        if not isinstance(group, list): continue
        result.extend(v for v in group if isinstance(v, dict) and isinstance(v.get('value'), str)
                      and 0 < len(v['value']) <= 160 and isinstance(v.get('name'), str))
    return result[:200]


class ACP:
    def __init__(self, pipe, callbacks, provider, permission_mode='ask'):
        self.pipe, self.cb, self.provider = pipe, callbacks, provider
        self.permission_mode = permission_mode
        self.sequence = 0
        self.native_id = None
        self.capabilities = {}
        self.settings = {}
        self.running = False
        self.texts = {}
        self.message = None
        self.last_kind = None
        self.turn = uuid.uuid4().hex
        self.started_at = time.time()
        self.pending_permission = None

    def request(self, method, params):
        self.sequence += 1
        request_id = 'agentdock-' + str(self.sequence)
        self.pipe.send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
        while True:
            message = self.pipe.next()
            if message.get('jsonrpc') != '2.0':
                raise ProviderError('The CLI did not return an ACP v1 message. Check its ACP command and version.')
            if 'method' in message:
                self.handle(message)
            elif message.get('id') == request_id:
                if 'error' in message:
                    error = message['error']
                    if isinstance(error, dict) and error.get('code') == -32000:
                        raise ProviderError('CLI authentication is required. Sign in to this CLI on the selected device first.')
                    raise ProviderError('The CLI rejected ACP operation ' + method + '. Check CLI authentication and compatibility.')
                result = message.get('result')
                if not isinstance(result, dict): raise ProviderError('The CLI returned an invalid ACP result.')
                return result

    def initialize(self):
        result = self.request('initialize', {'protocolVersion': 1,
            'clientInfo': {'name': 'agentdock', 'version': '0.3.0'},
            'clientCapabilities': {'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False}})
        if result.get('protocolVersion') != 1:
            raise ProviderError('This CLI requires a different ACP protocol version.')
        self.capabilities = result.get('agentCapabilities') or {}
        if not isinstance(self.capabilities, dict): raise ProviderError('Invalid ACP capabilities.')

    def setup(self, cwd, native_id, mcp_servers):
        self.initialize()
        self.native_id = native_id
        params = {'cwd': cwd, 'mcpServers': mcp_servers}
        if native_id:
            caps = self.capabilities.get('sessionCapabilities') or {}
            if isinstance(caps, dict) and isinstance(caps.get('resume'), dict):
                method = 'session/resume'
            elif self.capabilities.get('loadSession') is True:
                method = 'session/load'
            else:
                raise ProviderError('This CLI cannot resume saved ACP sessions. Update the CLI or start a new conversation.')
            params['sessionId'] = native_id
        else:
            method = 'session/new'
        # session/load can replay history. handle() discards all conversation and
        # permission events until setup and configuration have finished.
        self.settings = self.request(method, params)
        if native_id and self.settings.get('sessionId', native_id) != native_id:
            raise ProviderError('The CLI attempted to replace the saved ACP session.')
        self.native_id = native_id or self.settings.get('sessionId')
        if not identifier(self.native_id): raise ProviderError('The CLI returned an invalid ACP session identifier.')
        self.cb.bind_session(self.native_id)

    def options(self):
        raw = self.settings.get('configOptions', [])
        return [v for v in raw if isinstance(v, dict) and v.get('type') == 'select'] if isinstance(raw, list) else []

    def option(self, category):
        aliases = {'model': ('model',), 'thought_level': ('thought_level', 'thinking_level', 'reasoning_effort', 'effort')}
        return next((o for o in self.options() if o.get('category') == category or o.get('id') in aliases[category]), None)

    def models(self):
        model, effort = self.option('model'), self.option('thought_level')
        efforts = [v['value'] for v in values(effort or {}) if len(v['value']) <= 32]
        if model:
            return [{'id': v['value'], 'name': v['name'][:200], 'efforts': efforts} for v in values(model)]
        raw = self.settings.get('models') or {}
        return [{'id': m['modelId'], 'name': str(m.get('name') or m['modelId'])[:200], 'efforts': efforts}
                for m in raw.get('availableModels', []) if isinstance(m, dict)
                and isinstance(m.get('modelId'), str) and 0 < len(m['modelId']) <= 160][:100] if isinstance(raw, dict) else []

    def configure(self, model, effort):
        for category, selected in (('model', model), ('thought_level', effort)):
            if not selected: continue
            option = self.option(category)
            if option and selected in [v['value'] for v in values(option)]:
                result = self.request('session/set_config_option', {'sessionId': self.native_id,
                    'configId': option['id'], 'value': selected})
                self.settings.update(result)
            elif category == 'model' and not option and selected in [m['id'] for m in self.models()]:
                self.request('session/set_model', {'sessionId': self.native_id, 'modelId': selected})
                self.settings.setdefault('models', {})['currentModelId'] = selected
            else:
                raise ProviderError('The selected model or reasoning effort is not supported by this CLI. Choose CLI default or an available option.')
        actual_model = (self.option('model') or {}).get('currentValue') or (self.settings.get('models') or {}).get('currentModelId')
        actual_effort = (self.option('thought_level') or {}).get('currentValue')
        payload = {k: v for k, v in (('model', actual_model), ('effort', actual_effort)) if isinstance(v, str) and 0 < len(v) <= 160}
        if payload: self.cb.emit('model_info', {'native_id': self.native_id, **payload})

    def handle(self, message):
        method, params = message.get('method'), message.get('params') or {}
        if not isinstance(method, str): raise ProviderError('Invalid ACP method.')
        if not isinstance(params, dict): raise ProviderError('The CLI returned invalid ACP parameters.')
        if method.startswith('session/') and self.native_id is not None and params.get('sessionId') != self.native_id:
            raise ProviderError('The CLI emitted an event for a different ACP session.')
        if 'id' in message:
            if method == 'session/request_permission':
                self.permission(message['id'], params)
            else:
                # Never execute arbitrary filesystem/terminal requests or pretend
                # to approve provider extensions not advertised by this client.
                self.pipe.send({'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': -32601, 'message': 'Unsupported client method'}})
            return
        if method != 'session/update': return
        update = params.get('update')
        if not isinstance(update, dict): raise ProviderError('The CLI returned an invalid ACP update.')
        kind = update.get('sessionUpdate')
        if not self.running: return
        if kind == 'config_option_update':
            self.settings['configOptions'] = update.get('configOptions', [])
            return
        if kind in ('agent_message_chunk', 'agent_thought_chunk'):
            content = update.get('content') or {}
            if not isinstance(content, dict) or content.get('type') != 'text': return
            text = content.get('text')
            if not isinstance(text, str): raise ProviderError('The CLI returned invalid ACP text.')
            if kind == 'agent_thought_chunk':
                self.cb.emit('reasoning_chunk', {'provider': self.provider, 'item_id': self.turn + '-thought', 'part': 0, 'text': text})
            else:
                supplied_id = update.get('messageId')
                if supplied_id is not None and not identifier(supplied_id): raise ProviderError('Invalid ACP message ID.')
                if supplied_id:
                    self.message = supplied_id
                elif self.last_kind != kind or self.message is None:
                    self.message = self.turn + '-' + str(len(self.texts))
                self.texts[self.message] = self.texts.get(self.message, '') + text
                if sum(len(v.encode()) for v in self.texts.values()) > _MAX_RESULT:
                    raise ProviderError('ACP response exceeded the text limit.')
                self.cb.text(text, item_id=self.message, provider=self.provider)
            self.last_kind = kind
        elif kind in ('tool_call', 'tool_call_update'):
            if self.message and self.last_kind == 'agent_message_chunk':
                self.cb.text(self.texts[self.message], item_id=self.message, provider=self.provider, phase='commentary', complete=True)
            self.last_kind = 'tool'
            item = {k: update[k] for k in ('toolCallId', 'title', 'kind', 'status', 'content', 'rawInput', 'rawOutput') if k in update}
            item['id'] = item.pop('toolCallId', '')
            item['name'] = item.pop('title', item.get('kind', 'Tool'))
            self.cb.emit('tool_call' if kind == 'tool_call' else 'tool_result', {'provider': self.provider, 'item': item})
        elif kind == 'plan':
            self.cb.emit('plan_update', {'provider': self.provider, 'entries': update.get('entries', [])})
        elif kind == 'usage_update':
            # used/size are CONTEXT occupancy, not token consumption or TPS.
            self.cb.emit('context_usage', {k: update[k] for k in ('used', 'size') if isinstance(update.get(k), (int, float))})

    def permission(self, request_id, params):
        options = params.get('options')
        if not isinstance(options, list) or not options or len(options) > 32 or any(
                not isinstance(o, dict) or not identifier(o.get('optionId')) or not isinstance(o.get('name'), str)
                or o.get('kind') not in ('allow_once', 'allow_always', 'reject_once', 'reject_always') for o in options):
            raise ProviderError('The CLI returned invalid ACP permission options.')
        outcome = {'outcome': 'cancelled'}
        if self.running:
            # Full access only permits tool approvals, not arbitrary extension
            # questions represented by multiple different allow_once choices.
            allow = [o for o in options if o['kind'] == 'allow_once']
            if self.permission_mode == 'full_access' and len(allow) == 1:
                selected = allow[0]['optionId']
            else:
                self.pending_permission = request_id
                selected = self.cb.approve_options({'provider': self.provider, 'tool': params.get('toolCall', {})}, options)
                self.pending_permission = None
            if selected in [o['optionId'] for o in options]: outcome = {'outcome': 'selected', 'optionId': selected}
        self.pipe.send({'jsonrpc': '2.0', 'id': request_id, 'result': {'outcome': outcome}})

    def run(self, cwd, prompt, native_id, mcp, env, model, effort):
        servers = [{'name': 'agentdock', **mcp, 'env': [{'name': k, 'value': v} for k, v in env.items()]}]
        self.setup(cwd, native_id, servers)
        self.configure(model, effort)
        self.running = True
        result = self.request('session/prompt', {'sessionId': self.native_id, 'prompt': [{'type': 'text', 'text': prompt}]})
        reason = result.get('stopReason')
        if reason == 'cancelled': raise ProviderCancelled()
        if reason != 'end_turn':
            reason = reason if reason in ('max_tokens', 'max_turn_requests', 'refusal') else 'unknown stop reason'
            raise ProviderError('The CLI stopped before completing the turn (' + reason + ').')
        final = self.texts.get(self.message, '') if self.last_kind == 'agent_message_chunk' else ''
        if final: self.cb.text(final, item_id=self.message, provider=self.provider, phase='final_answer', complete=True)
        return self.cb.clean(final)

    def cancel(self):
        if self.pending_permission is not None:
            self.pipe.cancel_notice({'jsonrpc': '2.0', 'id': self.pending_permission, 'result': {'outcome': {'outcome': 'cancelled'}}})
        if self.native_id:
            self.pipe.cancel_notice({'jsonrpc': '2.0', 'method': 'session/cancel', 'params': {'sessionId': self.native_id}})
