"""Optional per-task/agent Git worktrees. Never resets or cleans user checkouts."""
import json
import os
from pathlib import Path
import subprocess
import uuid
import fcntl


def git(source, *args):
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0')
    result=subprocess.run(['git','-C',str(source),*args],capture_output=True,text=True,timeout=30,env=env)
    if result.returncode: raise ValueError('Could not prepare the task worktree; check the project Git repository')
    return result.stdout.strip()


def prepare(root, task_id, agent_id, source):
    for identifier in (task_id,agent_id):
        if str(uuid.UUID(identifier))!=identifier: raise ValueError('Invalid task workspace identity')
    root=Path(root).absolute()
    if root.is_symlink(): raise ValueError('Invalid task workspace path')
    root=root.resolve()
    parent=root/task_id/agent_id
    for path in (root,root/task_id,parent):
        if path.is_symlink(): raise ValueError('Invalid task workspace path')
        path.mkdir(parents=True,exist_ok=True,mode=0o700)
    destination=parent/'workspace'
    with (parent/'prepare.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        metadata=parent/'workspace.json'
        if metadata.exists():
            value=json.loads(metadata.read_text())
            if value['source']!=str(Path(source).resolve()) or Path(value['path'])!=destination or destination.is_symlink():
                raise ValueError('Task workspace ownership changed')
            if git(destination,'rev-parse','--show-toplevel')!=str(destination): raise ValueError('Task workspace is unavailable')
            return value
        if destination.exists(): raise ValueError('An unregistered task workspace exists; inspect it before retrying')
        source=Path(source).resolve()
        if git(source,'rev-parse','--show-toplevel')!=str(source): raise ValueError('Select the Git repository root')
        if git(source,'status','--porcelain'): raise ValueError('Commit or save project changes before creating an isolated worktree')
        # The first Agent freezes the task base; every teammate starts there.
        with (root/task_id/'base.lock').open('a') as base_lock:
            fcntl.flock(base_lock,fcntl.LOCK_EX)
            base_path=root/task_id/'base.json'
            if base_path.exists():
                base=json.loads(base_path.read_text())
                if base['source']!=str(source): raise ValueError('Task project changed')
            else:
                base={'source':str(source),'commit':git(source,'rev-parse','HEAD')}
                base_path.write_text(json.dumps(base))
            commit=base['commit']
        git(source,'worktree','add','--detach',str(destination),commit)
        value={'path':str(destination),'base_commit':commit,'source':str(source)}
        temporary=parent/'workspace.tmp'
        temporary.write_text(json.dumps(value)); os.replace(temporary,metadata)
        return value
