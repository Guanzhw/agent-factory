"""Session coding worktrees and reviewed changes applied to the original checkout."""
import asyncio
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .session_setup import rejected


class AttachRepository(BaseModel):
    model_config = ConfigDict(extra='forbid')
    repositoryPath: str = Field(min_length=1)


class ApplyChanges(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reviewId: str = Field(pattern=r'^[a-f0-9]{64}$')


def git(directory, *arguments, data=None, env=None):
    try:
        result = subprocess.run(['git', '-c', 'core.quotePath=false', '-c', 'color.ui=false',
            '-C', str(directory), *arguments], input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=False)
    except OSError as error:
        raise rejected('RESEARCH_GIT_UNAVAILABLE', str(error)) from error
    if result.returncode:
        raise rejected('RESEARCH_GIT_FAILED', result.stderr.decode('utf-8', errors='replace').strip())
    return result.stdout


def snapshot(workspace, baseline_tree):
    # A temporary index includes new files without staging the Agent's working copy.
    with tempfile.TemporaryDirectory(prefix='factory-git-index-') as directory:
        environment = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / 'index'))
        indexed_tree = git(workspace, 'write-tree').decode().strip()
        git(workspace, 'read-tree', indexed_tree, env=environment)
        git(workspace, 'add', '-A', '--', '.', env=environment)
        tree = git(workspace, 'write-tree', env=environment).decode().strip()
    arguments = ('--full-index', '--no-ext-diff', '--no-textconv', '--no-renames', baseline_tree, tree, '--')
    patch = git(workspace, 'diff', '--binary', *arguments)
    display = git(workspace, 'diff', *arguments)
    raw = git(workspace, 'diff', '--name-status', '-z', '--no-renames', baseline_tree, tree, '--')
    parts = raw.decode('utf-8', errors='surrogateescape').split('\0')
    files = [{'status': parts[index], 'path': parts[index + 1]} for index in range(0, len(parts) - 1, 2)]
    return {'tree': tree, 'patch': patch,
        'reviewId': hashlib.sha256(baseline_tree.encode() + b'\0' + patch).hexdigest(),
        'files': files, 'diff': display.decode('utf-8', errors='replace')}


class ResearchSessionGit:
    def __init__(self, sessions):
        self.sessions = sessions

    def _workspace(self, owner, identifier):
        return self.sessions.tools._workspace({'ownerId': owner, 'id': identifier})

    @staticmethod
    def _tree_ref(owner, identifier, name):
        session_key = hashlib.sha256((owner + '\0' + identifier).encode()).hexdigest()
        return f'refs/agent-factory/{session_key}/{name}'

    def _retain_tree(self, workspace, owner, identifier, tree, name='baseline'):
        git(workspace, 'update-ref', self._tree_ref(owner, identifier, name), tree)

    def _idle(self, conn, owner, identifier):
        turns = self.sessions._turns(conn, identifier)
        if turns and not self.sessions._safe(owner, turns[-1]):
            raise rejected('RESEARCH_GIT_SESSION_ACTIVE', '请等待会话停止后再连接仓库或应用修改。')

    @staticmethod
    def _source(workspace, source):
        root = git(source, 'rev-parse', '--show-toplevel').decode('utf-8').strip()
        source_common = git(source, 'rev-parse', '--path-format=absolute', '--git-common-dir').decode('utf-8').strip()
        workspace_common = git(workspace, 'rev-parse', '--path-format=absolute', '--git-common-dir').decode('utf-8').strip()
        if Path(root).resolve() != Path(source).resolve() or Path(source_common).resolve() != Path(workspace_common).resolve():
            raise rejected('RESEARCH_GIT_SOURCE_CHANGED', '原仓库已移动或替换，请检查仓库路径。')

    def _view(self, owner, row):
        metadata = row['body'].get('gitWorkspace')
        if metadata is None:
            return {'configured': False}
        workspace = self._workspace(owner, row['id'])
        changes = snapshot(workspace, metadata['baselineTree'])
        return {'configured': True, 'repositoryPath': metadata['repositoryPath'],
            'workspacePath': str(workspace), 'baseCommit': metadata['baseCommit'],
            'reviewId': changes['reviewId'], 'files': changes['files'], 'diff': changes['diff'],
            'applied': not changes['files'] and bool(metadata.get('lastAppliedReviewId')),
            'appliedReviewId': metadata.get('lastAppliedReviewId'),
            'applicationState': 'unknown' if metadata.get('pendingApply') else 'ready'}

    def read(self, owner, identifier):
        self.sessions.auth.require_member(owner)
        with self.sessions.db.read() as conn:
            return self._view(owner, self.sessions._row(conn, owner, identifier))

    def fork_workspace(self, owner, source_id, identifier, conn):
        source = self.sessions._row(conn, owner, source_id)
        metadata = source['body'].get('gitWorkspace')
        if metadata is None:
            return None
        parent_workspace = self._workspace(owner, source_id)
        changes = snapshot(parent_workspace, metadata['baselineTree'])
        workspace = self._workspace(owner, identifier)
        head = git(parent_workspace, 'rev-parse', 'HEAD').decode().strip()
        git(parent_workspace, 'worktree', 'add', '--detach', str(workspace), head)
        git(workspace, 'read-tree', '--reset', '-u', changes['tree'])
        self._retain_tree(workspace, owner, identifier, metadata['baselineTree'])
        return {key: metadata[key] for key in ('repositoryPath', 'baseCommit', 'baselineTree')}

    def attach(self, owner, identifier, repository_path):
        self.sessions.auth.require_member(owner)
        path = Path(repository_path).expanduser()
        if not path.is_absolute() or '\0' in repository_path:
            raise rejected('RESEARCH_GIT_PATH_INVALID', '请输入本机 Git 仓库的绝对路径。', 422)
        source = Path(git(path, 'rev-parse', '--show-toplevel').decode('utf-8').strip()).resolve()
        with self.sessions._write() as conn:
            row = self.sessions._row(conn, owner, identifier)
            metadata = row['body'].get('gitWorkspace')
            if metadata:
                if Path(metadata['repositoryPath']) != source:
                    raise rejected('RESEARCH_GIT_ALREADY_ATTACHED', '此会话已连接另一个仓库。')
                return self._view(owner, row)
            self._idle(conn, owner, identifier)
            workspace = self._workspace(owner, identifier)
            if any(workspace.iterdir()):
                raise rejected('RESEARCH_GIT_WORKSPACE_NOT_EMPTY', '此会话已有文件，请在新会话中连接仓库。')
            commit = git(source, 'rev-parse', 'HEAD').decode().strip()
            git(source, 'worktree', 'add', '--detach', str(workspace), commit)
            self._retain_tree(workspace, owner, identifier, commit)
            metadata = {'repositoryPath': str(source), 'baseCommit': commit, 'baselineTree': commit}
            body = {**row['body'], 'gitWorkspace': metadata}
            self.sessions._save_session(conn, row, body)
            return self._view(owner, {**row, 'body': body})

    def apply(self, owner, identifier, review_id):
        self.sessions.auth.require_member(owner)
        with self.sessions._write() as conn:
            row = self.sessions._row(conn, owner, identifier)
            metadata = row['body'].get('gitWorkspace')
            if metadata is None:
                raise rejected('RESEARCH_GIT_NOT_ATTACHED', '此会话尚未连接 Git 仓库。')
            if metadata.get('lastAppliedReviewId') == review_id:
                return {**self._view(owner, row), 'repeated': True}
            if metadata.get('pendingApply'):
                raise rejected('RESEARCH_GIT_APPLY_UNKNOWN',
                    '上次应用未确认完成，请检查原仓库；为避免重复修改，本次未再次应用。')
            self._idle(conn, owner, identifier)
            workspace = self._workspace(owner, identifier)
            # Keep the committed baseline reachable before replacing the transition reference.
            self._retain_tree(workspace, owner, identifier, metadata['baselineTree'])
            git(workspace, 'update-ref', '-d', self._tree_ref(owner, identifier, 'pending'))
            changes = snapshot(workspace, metadata['baselineTree'])
            if changes['reviewId'] != review_id:
                raise rejected('RESEARCH_GIT_STALE_REVIEW', '修改已变化，请刷新并重新检查差异。')
            if not changes['files']:
                raise rejected('RESEARCH_GIT_NO_CHANGES', '没有可应用的修改。')
            source = metadata['repositoryPath']
            self._source(workspace, source)
            # Native apply validates all hunks before changing files and preserves the source index.
            git(source, 'apply', '--check', '--binary', '-', data=changes['patch'])
            self._retain_tree(workspace, owner, identifier, changes['tree'], 'pending')
            metadata = {**metadata, 'pendingApply': {'reviewId': review_id, 'tree': changes['tree']}}
            self.sessions._save_session(conn, row, {**row['body'], 'gitWorkspace': metadata})
        # Commit intent before touching user files: an interrupted operation must never be replayed.
        with self.sessions._write() as conn:
            row = self.sessions._row(conn, owner, identifier)
            metadata = row['body']['gitWorkspace']
            failure = None
            try:
                self._idle(conn, owner, identifier)
                self._source(workspace, source)
                git(source, 'apply', '--check', '--binary', '-', data=changes['patch'])
            except HTTPException as error:
                failure = error
            if failure is None:
                git(source, 'apply', '--binary', '-', data=changes['patch'])
                metadata = {**metadata, 'baselineTree': changes['tree'], 'lastAppliedReviewId': review_id}
            metadata = {**metadata, 'pendingApply': None}
            self.sessions._save_session(conn, row, {**row['body'], 'gitWorkspace': metadata})
        if failure is not None:
            raise failure
        return {**self.read(owner, identifier), 'repeated': False}


def git_router(auth, service):
    router = APIRouter(prefix='/api/factory/research/sessions')

    @router.get('/{identifier}/git')
    def read(request: Request, identifier: str):
        return service.read(auth.user(request)['id'], identifier)

    @router.post('/{identifier}/git')
    async def attach(request: Request, identifier: str, body: AttachRepository):
        return await asyncio.to_thread(service.attach, auth.user(request)['id'], identifier, body.repositoryPath)

    @router.post('/{identifier}/git/apply')
    async def apply(request: Request, identifier: str, body: ApplyChanges):
        return await asyncio.to_thread(service.apply, auth.user(request)['id'], identifier, body.reviewId)

    return router
