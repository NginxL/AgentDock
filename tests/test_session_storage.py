import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

from agentdock.codex_home import prepare
from agentdock.session_storage import prepare_claude, remove_session_directory
from agentdock.session_storage import retire_legacy_claude
from agentdock.runtime import Runtime
from agentdock.store import Store, Conflict


class SessionStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root/'original'; self.source.mkdir()
        self.store = Store(self.root/'data'/'agentdock.sqlite3')

    def tearDown(self):
        self.store.close(); self.tmp.cleanup()

    def test_codex_isolates_state_and_settings_but_keeps_native_login(self):
        (self.source/'auth.json').write_text('fixture credential')
        (self.source/'config.toml').write_text('model = "custom/model"\nsqlite_home = "/original/state"\n')
        original = (self.source/'config.toml').read_bytes()
        homes = [self.root/'one'/'codex', self.root/'two'/'codex']
        for home in homes:
            env, flags, legacy = prepare(home, {'CODEX_HOME':str(self.source), 'HTTPS_PROXY':'http://localhost:1234'})
            self.assertEqual(env['CODEX_HOME'], str(home))
            self.assertEqual(env['CODEX_SQLITE_HOME'], str(home))
            self.assertEqual(env['HTTPS_PROXY'], 'http://localhost:1234')
            self.assertIn('sqlite_home='+json.dumps(str(home)), flags)
            self.assertEqual((home/'auth.json').resolve(), self.source/'auth.json')
            self.assertFalse((home/'config.toml').is_symlink())
            self.assertFalse((home/'sessions').exists())
            self.assertIsNone(legacy)
        (homes[0]/'config.toml').write_text('isolated change')
        self.assertEqual((self.source/'config.toml').read_bytes(), original)
        self.assertEqual((homes[1]/'config.toml').read_bytes(), original)

    def test_import_only_the_bound_agentdock_rollout(self):
        folder=self.source/'sessions'/'2026'; folder.mkdir(parents=True)
        native=str(uuid.uuid4())
        def rollout(identifier, origin):
            path=folder/('rollout-'+identifier+'.jsonl')
            path.write_text(json.dumps({'type':'session_meta','payload':{'id':identifier,'originator':origin,'cwd':'/old/workspace'}})+'\n')
            return path
        owned=rollout(native,'agentdock'); other=rollout(str(uuid.uuid4()),'codex-desktop')
        home=self.root/'isolated'
        _,_,legacy=prepare(home,{'CODEX_HOME':str(self.source)},native,'/new/workspace')
        self.assertEqual(legacy,owned)
        self.assertEqual([p.name for p in (home/'sessions').rglob('*.jsonl')],[owned.name])
        self.assertTrue(other.exists()); self.assertTrue(owned.exists())
        _,_,legacy=prepare(self.root/'refused',{'CODEX_HOME':str(self.source)},other.stem.removeprefix('rollout-'),'/old/workspace')
        self.assertIsNone(legacy)

    def test_claude_uses_private_config_with_original_credential_store(self):
        (self.source/'settings.json').write_text('{"theme":"dark"}')
        (self.source/'.claude.json').write_text('{"fixture":true}')
        env=prepare_claude(self.root/'claude',{'CLAUDE_CONFIG_DIR':str(self.source),'CLAUDECODE':'1','HTTPS_PROXY':'fixture'})
        self.assertEqual(env['CLAUDE_CONFIG_DIR'], str(self.root/'claude'))
        self.assertEqual(env['CLAUDE_SECURESTORAGE_CONFIG_DIR'], str(self.source))
        self.assertNotIn('CLAUDECODE',env)
        self.assertEqual(env['HTTPS_PROXY'],'fixture')
        self.assertEqual((self.root/'claude'/'settings.json').read_text(),'{"theme":"dark"}')
        with patch('agentdock.session_storage.Path.home', return_value=self.root):
            self.assertEqual(prepare_claude(self.root/'default',{})['CLAUDE_SECURESTORAGE_CONFIG_DIR'],'')

    def test_private_workspaces_are_distinct_and_explicit_projects_stay_shared(self):
        agent=self.store.add_agent(None,'A','codex')
        first=self.store.add_session(agent['id'],'One'); second=self.store.add_session(agent['id'],'Two')
        self.assertNotEqual(first['workspace'],second['workspace'])
        shared=self.store.add_agent(None,'B','claude',workspace=str(self.source))
        session=self.store.add_session(shared['id'],'Shared project')
        self.assertEqual(session['workspace'],str(self.source))

    def test_claude_migration_and_cleanup_are_limited_to_the_bound_native_id(self):
        folder=self.source/'projects'/'fixture'; folder.mkdir(parents=True)
        owned,other=str(uuid.uuid4()),str(uuid.uuid4())
        for native in (owned,other): (folder/(native+'.jsonl')).write_text(json.dumps({'sessionId':native})+'\n')
        env={'CLAUDE_CONFIG_DIR':str(self.source)}
        prepare_claude(self.root/'claude',env,owned)
        self.assertTrue((self.root/'claude'/'projects'/'fixture'/(owned+'.jsonl')).exists())
        self.assertFalse((self.root/'claude'/'projects'/'fixture'/(other+'.jsonl')).exists())
        retire_legacy_claude(env,owned)
        self.assertFalse((folder/(owned+'.jsonl')).exists())
        self.assertTrue((folder/(other+'.jsonl')).exists())

    def test_old_automatic_workspace_migration_preserves_files_and_native_id(self):
        agent=self.store.add_agent(None,'A','codex')
        session=self.store.add_session(agent['id'],'Legacy')
        (Path(agent['workspace'])/'keep.txt').write_text('existing session work')
        self.store.db.execute('UPDATE sessions SET workspace=?,native_session_id=? WHERE id=?',(agent['workspace'],'owned-native',session['id']))
        self.store.close(); self.store=Store(self.root/'data'/'agentdock.sqlite3')
        migrated=self.store.get_session(session['id'])
        self.assertNotEqual(migrated['workspace'],agent['workspace'])
        self.assertEqual(migrated['native_session_id'],'owned-native')
        self.assertEqual((Path(migrated['workspace'])/'keep.txt').read_text(),'existing session work')

    def test_delete_removes_only_private_files_and_session_records(self):
        agent=self.store.add_agent(None,'A','codex',workspace=str(self.source))
        first=self.store.add_session(agent['id'],'One'); second=self.store.add_session(agent['id'],'Two')
        directory=self.store.session_directory(first['id']); directory.mkdir(parents=True)
        (directory/'shared-link').symlink_to(self.source, target_is_directory=True)
        (directory/'private.txt').write_text('private')
        (self.source/'keep.txt').write_text('shared')
        runtime=Runtime(self.store,{'execution_enabled':False})
        try: self.assertEqual(runtime.delete_session(first['id']), {'ok':True})
        finally: runtime.close()
        self.assertFalse(directory.exists())
        self.assertEqual((self.source/'keep.txt').read_text(),'shared')
        self.assertEqual(self.store.get_session(second['id'])['id'],second['id'])

    def test_active_session_and_failed_remote_cleanup_keep_records(self):
        agent=self.store.add_agent(None,'A','codex')
        session=self.store.add_session(agent['id'],'Active')
        self.store.enqueue_run(session['id'],'pending')
        cleanup=Mock()
        with self.assertRaises(Conflict): self.store.delete_session(session['id'],cleanup)
        cleanup.assert_not_called()
        env=self.store.add_environment('remote','fixture')
        remote=self.store.add_agent(None,'B','codex',environment_id=env['id'])
        session=self.store.add_session(remote['id'],'Remote')
        runtime=Runtime(self.store,{'execution_enabled':True})
        runtime.remote.rpc=Mock(side_effect=OSError('offline'))
        try:
            with self.assertRaises(OSError): runtime.delete_session(session['id'])
            self.assertEqual(self.store.get_session(session['id'])['id'],session['id'])
        finally: runtime.close()

    def test_deletion_rejects_traversal_and_symlinked_session_roots(self):
        root=self.root/'sessions'; root.mkdir()
        identifier=str(uuid.uuid4()); (root/identifier).symlink_to(self.source, target_is_directory=True)
        for value in ('../original', identifier):
            with self.assertRaises(ValueError): remove_session_directory(root,value)
        self.assertTrue(self.source.is_dir())
