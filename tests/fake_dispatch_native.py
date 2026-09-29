"""Native protocol fixture. Only contacts AgentDock's temporary loopback MCP endpoint."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

provider, mode = sys.argv[1:3]
log_path = Path.cwd() / 'native-transcript.jsonl'


def log(**event):
    with log_path.open('a') as output:
        output.write(json.dumps({'provider': provider, **event}) + '\n')


def emit(value):
    print(json.dumps(value), flush=True)


class MCP:
    def __init__(self, config):
        self.child = subprocess.Popen([config['command'], *config.get('args', [])],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, env=dict(os.environ))
        self.sequence = 0
        self.request('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                                    'clientInfo': {'name': 'dispatch-fixture', 'version': '1'}})

    def request(self, method, params):
        self.sequence += 1
        self.child.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.sequence, 'method': method, 'params': params}) + '\n')
        self.child.stdin.flush()
        result = json.loads(self.child.stdout.readline())
        if result.get('id') != self.sequence or 'result' not in result:
            raise RuntimeError('MCP fixture handshake failed')
        return result['result']

    def tool(self, name, arguments, error=False):
        result = self.request('tools/call', {'name': name, 'arguments': arguments})
        if bool(result.get('isError')) != error:
            raise RuntimeError('MCP tool returned unexpected status: ' + name)
        if error:
            return None
        return json.loads(result['content'][0]['text'])

    def close(self):
        self.child.stdin.close()
        self.child.wait(timeout=2)
        self.child.stdout.close()


def run_codex():
    native_id = None
    mcp_config = None
    for raw in sys.stdin:
        request = json.loads(raw)
        method, args = request.get('method'), request.get('params', {})
        if method == 'initialize':
            emit({'id': request['id'], 'result': {}})
        elif method in ('thread/start', 'thread/resume'):
            native_id = args.get('threadId') or str(uuid.uuid4())
            mcp_config = args['config']['mcp_servers']['agentdock']
            log(method=method, native_id=native_id)
            emit({'id': request['id'], 'result': {'thread': {'id': native_id}, 'cwd': str(Path.cwd())}})
        elif method == 'turn/start':
            prompt = args['input'][0]['text']
            log(method=method, native_id=native_id, prompt=prompt)
            turn_id = str(uuid.uuid4())
            emit({'id': request['id'], 'result': {'turn': {'id': turn_id}}})
            result = 'Codex reviewed the implementation.'
            if mode in ('delegate', 'nested', 'fanout', 'nestedcancel', 'fanoutfail') and '<fixture-delegate>' in prompt:
                bridge = MCP(mcp_config)
                try:
                    agents = bridge.tool('agent_list', {})
                    target = next(a for a in agents if a['provider'] == 'claude')
                    control_path = Path.cwd() / 'fixture-control.json'
                    if control_path.exists():
                        foreign = json.loads(control_path.read_text()).get('foreign_agent')
                        if foreign:
                            bridge.tool('message_send', {'recipient_id': foreign, 'body': 'Cross-project attempt'}, error=True)
                            log(method='cross_project_rejected')
                    body = {'recipient_id': target['id'], 'body': 'Implement the reviewed plan.', 'idempotency_key': 'native-fixture-delegation'}
                    one = bridge.tool('message_send', body)
                    two = bridge.tool('message_send', body)
                    if one['id'] != two['id'] or one['run_id'] != two['run_id']:
                        raise RuntimeError('Delivery deduplication failed')
                    status = bridge.tool('task_status', {'message_id': one['id']})
                    if status['status'] != 'queued':
                        raise RuntimeError('Child started before parent released the shared workspace')
                    log(method='delegated', delivery_id=one['id'], run_id=one['run_id'])
                    result = 'Implementation delegated; current turn complete.'
                finally:
                    bridge.close()
            elif mode == 'nul':
                result = 'before\x00after'
            elif mode == 'permission' or (mode == 'nestedcancel' and '<current-task>\nReview the implementation.\n</current-task>' in prompt):
                emit({'id': 'fixture-permission', 'method': 'item/commandExecution/requestApproval',
                      'params': {'threadId': native_id, 'turnId': turn_id, 'itemId': 'cmd-one', 'command': 'fixture-command'}})
                answer = json.loads(sys.stdin.readline())
                log(method='permission_result', decision=answer.get('result', {}).get('decision'))
                result = 'Permission handled.'
            emit({'method': 'item/completed', 'params': {'threadId': native_id, 'turnId': turn_id,
                  'item': {'type': 'agentMessage', 'id': 'message-final', 'text': result}}})
            emit({'method': 'turn/completed', 'params': {'threadId': native_id, 'turn': {'id': turn_id, 'status': 'completed'}}})
        elif method == 'turn/interrupt':
            return


def run_claude():
    native_id = next((x.split('=', 1)[1] for x in sys.argv if x.startswith('--resume=')), None)
    resumed = native_id is not None
    native_id = native_id or sys.argv[sys.argv.index('--session-id') + 1]
    mcp_config = json.loads(sys.argv[sys.argv.index('--mcp-config') + 1])['mcpServers']['agentdock']
    log(method='claude/resume' if resumed else 'claude/start', native_id=native_id)
    for raw in sys.stdin:
        request = json.loads(raw)
        if request.get('type') == 'control_request':
            if request.get('request', {}).get('subtype') == 'interrupt':
                return
            emit({'type': 'control_response', 'response': {'subtype': 'success',
                  'request_id': request['request_id'], 'response': {}}, 'session_id': native_id})
        elif request.get('type') == 'user':
            prompt = request['message']['content']
            log(method='claude/prompt', native_id=native_id, prompt=prompt)
            bridge = MCP(mcp_config)
            try:
                memories = bridge.tool('memory_search', {'query': 'Project rule'})
                fact = memories[0]['content'] if memories else 'No shared rule'
                bridge.tool('memory_propose', {'key': 'Implementation note', 'content': 'Test-only proposal', 'expected_version': 0})
                delegated = False
                if mode in ('nested', 'fanout', 'nestedcancel', 'fanoutfail') and '<teammate-result>' not in prompt:
                    agents = bridge.tool('agent_list', {})
                    reviewers = [a for a in agents if a['name'].startswith('Reviewer')]
                    for index, reviewer in enumerate(reviewers):
                        bridge.tool('message_send', {'recipient_id': reviewer['id'], 'body': 'Review the implementation.', 'idempotency_key': 'nested-review-' + str(index)})
                    delegated = True
            finally:
                bridge.close()
            result = 'Claude implemented the plan. Shared rule: ' + fact
            if mode in ('nested', 'fanout', 'nestedcancel', 'fanoutfail'):
                result = 'Builder delegated review.' if delegated else 'Builder completed implementation after review.'
                if mode in ('fanout', 'fanoutfail') and not delegated:
                    counter = Path.cwd() / ('reviews-consumed-' + native_id)
                    count = int(counter.read_text()) + 1 if counter.exists() else 1
                    counter.write_text(str(count))
                    result = 'Builder completed implementation after all reviews.' if count == 2 else 'Builder consumed the first review.'
            if mode == 'fanoutfail' and not delegated:
                emit({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True,
                      'session_id': native_id, 'result': 'Fixture continuation failure'})
                continue
            emit({'type': 'assistant', 'session_id': native_id,
                  'message': {'content': [{'type': 'text', 'text': result}]}})
            emit({'type': 'result', 'subtype': 'success', 'is_error': False,
                  'session_id': native_id, 'result': result})


if __name__ == '__main__':
    run_codex() if provider == 'codex' else run_claude()
