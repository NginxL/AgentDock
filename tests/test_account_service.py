import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from agentdock.account_service import AccountService, account_usage
from agentdock.accounts import AccountError
from agentdock.server import API
from agentdock.store import Store, Conflict


class AccountServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/'state.sqlite3')
        self.runtime = Mock(enabled=True, config={'commands': {}}, _wake=Mock())
        self.service = AccountService(self.store, self.runtime)
        self.service.manager = Mock()
        self.service.watch = Mock()
        self.runtime.accounts = self.service
        self.api = API(self.store, self.runtime, Mock(), 'admin', execution_enabled=True)
        self.headers = {'Host':'127.0.0.1:47831', 'Authorization':'Bearer admin', 'Content-Type':'application/json'}
        self.account = self.store.add_account('codex', 'Personal')

    def tearDown(self):
        self.api.close(); self.service.close(); self.store.close(); self.temp.cleanup()

    def call(self, method, path, payload=None):
        return self.api.dispatch(method, path, self.headers, json.dumps(payload or {}).encode())

    def test_login_completion_is_reconciled_once_and_contains_no_credential_fields(self):
        self.service.manager.status.return_value = {'id':'job', 'status':'completed'}
        self.service.manager.check.return_value = {'logged_in':True, 'email':'person@example.test','plan':'plus'}
        self.service.login_status(self.account['id'])
        self.service.login_status(self.account['id'])
        ready = self.store.get_account(self.account['id'])
        self.assertEqual((ready['status'], ready['generation']), ('ready', 1))
        self.service.manager.check.assert_called_once()
        self.assertNotIn('token', json.dumps(ready))

    def test_stale_completed_login_cannot_mark_a_logged_out_profile_ready(self):
        self.service.manager.status.return_value = {'id':'old', 'status':'completed'}
        self.service.manager.check.return_value = {'logged_in':False}
        self.service.login_status(self.account['id'])
        self.assertEqual(self.store.get_account(self.account['id'])['status'], 'expired')

    def test_start_failure_restores_previous_account_state(self):
        self.store.complete_account_login(self.account['id'])
        self.service.manager.start.side_effect = AccountError('Native CLI unavailable')
        with self.assertRaises(AccountError): self.service.start_login(self.account['id'])
        self.assertEqual(self.store.get_account(self.account['id'])['status'], 'ready')

    def test_quota_normalization_preserves_last_observation_when_native_has_no_endpoint(self):
        self.store.complete_account_login(self.account['id'])
        self.service.manager.refresh.return_value = {'logged_in':True, 'windows':[
            {'name':'primary','used_percent':25,'duration_mins':300,'resets_at':2000000000}]}
        first = self.service.refresh(self.account['id'])
        self.assertEqual(first['quota']['windows'][0]['remaining_percent'], 75)
        self.assertEqual(first['quota']['windows'][0]['duration_minutes'], 300)
        self.service.manager.refresh.return_value = {'logged_in':True, 'windows':[], 'error_code':'quota_unavailable'}
        second = self.service.refresh(self.account['id'])
        self.assertEqual(second['quota']['windows'], first['quota']['windows'])
        self.assertEqual(second['quota']['status'], 'stale')

    def test_refresh_cannot_reenable_an_account_disabled_during_native_read(self):
        self.store.complete_account_login(self.account['id'])
        self.store.set_account_status(self.account['id'], 'cooldown', cooldown_until='2030-01-01T00:00:00+00:00')
        def native_refresh(_):
            self.store.update_account(self.account['id'], {'enabled': False})
            return {'logged_in': True, 'email': 'old@example.test', 'windows': [
                {'name': 'primary', 'used_percent': 20, 'resets_at': 2000000000}]}
        self.service.manager.refresh.side_effect = native_refresh
        result = self.service.refresh(self.account['id'])
        self.assertEqual(result['status'], 'disabled')
        self.assertEqual(result['identity'], {})
        self.assertEqual(result['quota'], {})

    def test_refresh_failure_does_not_expire_newer_login_generation(self):
        self.store.complete_account_login(self.account['id'])
        def native_refresh(_):
            self.store.complete_account_login(self.account['id'])
            self.store.set_account_identity(self.account['id'], {'email': 'new@example.test'})
            return {'logged_in': False}
        self.service.manager.refresh.side_effect = native_refresh
        result = self.service.refresh(self.account['id'])
        self.assertEqual((result['status'], result['generation']), ('ready', 2))
        self.assertEqual(result['identity'], {'email': 'new@example.test'})

    def test_check_discards_result_after_disable_and_reenable_same_generation(self):
        self.store.complete_account_login(self.account['id'])
        def native_check(_):
            self.store.update_account(self.account['id'], {'enabled': False})
            self.store.update_account(self.account['id'], {'enabled': True})
            return {'logged_in': False}
        self.service.manager.check.side_effect = native_check
        self.service.check(self.account['id'])
        result = self.store.get_account(self.account['id'])
        self.assertEqual((result['status'], result['generation']), ('pending', 1))

    def test_old_terminal_login_status_does_not_reconcile_a_new_login(self):
        for terminal in ('completed', 'failed', 'cancelled'):
            with self.subTest(terminal=terminal):
                self.store.set_account_status(self.account['id'], 'pending')
                def native_status(_):
                    self.store.set_account_status(self.account['id'], 'pending')
                    return {'id': 'old-job', 'status': terminal}
                self.service.manager.status.side_effect = native_status
                self.service.login_status(self.account['id'])
                self.assertEqual(self.store.get_account(self.account['id'])['status'], 'pending')
                self.service.manager.check.assert_not_called()

    def test_start_failure_does_not_undo_a_concurrent_disable(self):
        self.store.complete_account_login(self.account['id'])
        def native_start(*args, **kwargs):
            self.store.update_account(self.account['id'], {'enabled': False})
            raise AccountError('Native CLI unavailable')
        self.service.manager.start.side_effect = native_start
        with self.assertRaises(AccountError): self.service.start_login(self.account['id'])
        self.assertEqual(self.store.get_account(self.account['id'])['status'], 'disabled')

    def test_failed_credential_removal_retains_account_and_history(self):
        self.service.manager.remove.side_effect = AccountError('Logout unavailable')
        with self.assertRaises(AccountError): self.service.remove(self.account['id'])
        self.assertEqual(self.store.get_account(self.account['id'])['status'], 'pending')

    def test_remote_login_operations_send_identity_only_and_never_local_configuration(self):
        device = self.store.add_environment('Remote', 'fixture-box')
        remote = self.store.add_account('claude', 'Remote account', device['id'])
        self.runtime.remote.rpc.return_value = {'id':'job','status':'starting'}
        self.service.start_login(remote['id'])
        args, kwargs = self.runtime.remote.rpc.call_args
        self.assertEqual(args[0],device['id'])
        self.assertEqual(args[1]['account'], {'id':remote['id'],'provider':'claude'})
        self.assertEqual(args[1]['controller'],self.store.controller_id)
        self.assertTrue(kwargs['install'])
        self.service.manager.start.assert_not_called()
        self.assertNotIn('credentials',json.dumps(args))

    def test_http_models_cannot_mix_device_and_account_and_review_mode_never_authenticates(self):
        status,_ = self.call('GET','/api/models/claude?account_id='+self.account['id'])
        self.assertEqual(status,400)
        self.service.manager.environment.assert_not_called()
        self.api.execution_enabled = False
        status,_ = self.call('POST','/api/accounts/'+self.account['id']+'/login')
        self.assertEqual(status,403)
        self.service.manager.start.assert_not_called()

    def test_invalid_account_on_new_session_does_not_leave_an_orphan_session(self):
        agent = self.store.add_agent(None,'Codex','codex')
        status,_ = self.call('POST','/api/sessions',{'agent_id':agent['id'],'title':'New','account_id':'missing'})
        self.assertEqual(status,404)
        self.assertEqual(self.store.state()['sessions'],[])

    def test_account_usage_includes_retired_branches_and_stays_separate(self):
        from agentdock.metrics import record
        import time
        self.store.complete_account_login(self.account['id'])
        other = self.store.add_account('codex','Other')
        self.store.complete_account_login(other['id'])
        agent = self.store.add_agent(None,'Codex','codex',account_id=self.account['id'])
        session = self.store.add_session(agent['id'],'Thread')
        for i,account in enumerate((self.account,other)):
            if i: self.store.switch_session_account(session['id'], account['id'])
            run = self.store.begin_run(session['id'],'Message')
            attempt = self.store.reserve_run_account(run['id'])
            native = 'native-'+str(i)
            self.store.bind_native_session(session['id'],native,run_id=run['id'])
            record(self.store,'codex',native,'total',{'input_tokens':i+2,'output_tokens':3,
                'cache_read_tokens':0,'cache_write_tokens':0,'total_tokens':i+5},time.time(),'managed')
            self.store.finish_account_attempt(attempt['id'],'completed')
            self.store.finish_run(run['id'],'completed',result='Done')
        totals = {a['id']:a['usage']['total_tokens'] for a in account_usage(self.store,self.store.accounts())}
        self.assertEqual(totals,{self.account['id']:5,other['id']:6})


if __name__ == '__main__': unittest.main()
