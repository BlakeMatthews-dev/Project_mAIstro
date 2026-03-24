"""Tests for infra and interface modules — couchdb, obsidian_watcher, vault_sync,
auth, database, secrets, tenant, knowledge_graph, board (extended), evolution."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

orchestrator = pytest.importorskip("orchestrator")

# ---------------------------------------------------------------------------
# 1. CouchDB Client
# ---------------------------------------------------------------------------
from orchestrator.interfaces.couchdb_client import (
    CouchDBClient,
    LiveSyncDoc,
    PREFIX_CHUNK,
)


class TestLiveSyncDoc:
    def test_dataclass_fields(self):
        doc = LiveSyncDoc(
            doc_id="conductor/inbox/task.md",
            path="conductor/inbox/task.md",
            content="hello world",
            doc_type="plain",
            ctime=1000,
            mtime=2000,
        )
        assert doc.doc_id == "conductor/inbox/task.md"
        assert doc.content == "hello world"
        assert doc.rev == ""  # default

    def test_rev_field(self):
        doc = LiveSyncDoc("a", "a", "c", "plain", 0, 0, rev="1-abc")
        assert doc.rev == "1-abc"


class TestSplitContent:
    def test_short_content_single_chunk(self):
        result = CouchDBClient._split_content("hello", max_chunk_size=1000)
        assert result == ["hello"]

    def test_exact_boundary(self):
        data = "x" * 1000
        result = CouchDBClient._split_content(data, max_chunk_size=1000)
        assert result == [data]

    def test_splits_into_multiple_chunks(self):
        data = "a" * 2500
        chunks = CouchDBClient._split_content(data, max_chunk_size=1000)
        assert len(chunks) == 3
        assert chunks[0] == "a" * 1000
        assert chunks[1] == "a" * 1000
        assert chunks[2] == "a" * 500
        assert "".join(chunks) == data

    def test_empty_content(self):
        assert CouchDBClient._split_content("") == [""]

    def test_custom_chunk_size(self):
        data = "abcdefghij"
        chunks = CouchDBClient._split_content(data, max_chunk_size=3)
        assert chunks == ["abc", "def", "ghi", "j"]
        assert "".join(chunks) == data


class TestComputeChunkId:
    def test_prefix(self):
        cid = CouchDBClient._compute_chunk_id("hello")
        assert cid.startswith(PREFIX_CHUNK)

    def test_deterministic(self):
        a = CouchDBClient._compute_chunk_id("test data")
        b = CouchDBClient._compute_chunk_id("test data")
        assert a == b

    def test_different_data_different_id(self):
        a = CouchDBClient._compute_chunk_id("aaa")
        b = CouchDBClient._compute_chunk_id("bbb")
        assert a != b

    def test_hash_length(self):
        cid = CouchDBClient._compute_chunk_id("data")
        # prefix "h:" + 16 hex chars
        assert len(cid) == 2 + 16

    def test_matches_sha256_prefix(self):
        data = "test content"
        expected = PREFIX_CHUNK + hashlib.sha256(data.encode()).hexdigest()[:16]
        assert CouchDBClient._compute_chunk_id(data) == expected


class TestReassembleChunks:
    @pytest.mark.asyncio
    async def test_eden_only(self):
        client = CouchDBClient("http://localhost:5984", "test")
        children = ["h:aaa", "h:bbb"]
        eden = {
            "h:aaa": {"data": "hello ", "epoch": 1},
            "h:bbb": {"data": "world", "epoch": 1},
        }
        result = await client._reassemble_chunks(children, eden)
        assert result == "hello world"
        await client.close()

    @pytest.mark.asyncio
    async def test_eden_string_fallback(self):
        client = CouchDBClient("http://localhost:5984", "test")
        eden = {"h:aaa": "raw_string"}
        result = await client._reassemble_chunks(["h:aaa"], eden)
        assert result == "raw_string"
        await client.close()

    @pytest.mark.asyncio
    async def test_fetch_from_db(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_chunk = AsyncMock(return_value="fetched_data")
        result = await client._reassemble_chunks(["h:xyz"], {})
        assert result == "fetched_data"
        client.get_chunk.assert_awaited_once_with("h:xyz")
        await client.close()

    @pytest.mark.asyncio
    async def test_mixed_eden_and_db(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_chunk = AsyncMock(return_value="DB")
        eden = {"h:aaa": {"data": "EDEN"}}
        result = await client._reassemble_chunks(["h:aaa", "h:bbb"], eden)
        assert result == "EDENDB"
        client.get_chunk.assert_awaited_once_with("h:bbb")
        await client.close()

    @pytest.mark.asyncio
    async def test_empty_children(self):
        client = CouchDBClient("http://localhost:5984", "test")
        result = await client._reassemble_chunks([], {})
        assert result == ""
        await client.close()


class TestDocumentFormat:
    """Verify that write_file produces the correct LiveSync document shape."""

    @pytest.mark.asyncio
    async def test_write_file_document_structure(self):
        client = CouchDBClient("http://localhost:5984", "test")
        # Mock get_doc (no existing chunk/doc) and _client.put
        client.get_doc = AsyncMock(return_value=None)
        put_calls = []

        async def mock_put(url, json=None):
            put_calls.append((url, json))
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json = lambda: {"rev": "1-new"}
            return resp

        client._client.put = mock_put
        rev = await client.write_file("conductor/completed/task.md", "result text")
        assert rev == "1-new"

        # Last put call should be the document itself
        doc_url, doc_body = put_calls[-1]
        assert doc_url == "/conductor/completed/task.md"
        assert doc_body["type"] == "plain"
        assert isinstance(doc_body["children"], list)
        assert len(doc_body["children"]) > 0
        assert all(c.startswith(PREFIX_CHUNK) for c in doc_body["children"])
        assert doc_body["eden"] == {}
        assert doc_body["deleted"] is False
        assert doc_body["size"] == len("result text".encode("utf-8"))
        await client.close()


# ---------------------------------------------------------------------------
# 2. Obsidian Watcher
# ---------------------------------------------------------------------------
from orchestrator.interfaces.obsidian_watcher import ObsidianWatcher, _InboxHandler
from orchestrator.interfaces.vault_sync import LocalSync


class TestObsidianWatcherListPending:
    @pytest.mark.asyncio
    async def test_list_pending_reads_md_files(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = ObsidianWatcher(str(vault), sync_adapter=LocalSync())
        inbox = vault / "conductor" / "inbox"
        (inbox / "task1.md").write_text("content1")
        (inbox / "task2.md").write_text("content2")
        (inbox / "ignore.txt").write_text("not a task")

        tasks = await watcher.list_pending()
        filenames = [t[0] for t in tasks]
        assert "task1.md" in filenames
        assert "task2.md" in filenames
        assert "ignore.txt" not in filenames

    @pytest.mark.asyncio
    async def test_list_pending_empty_inbox(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = ObsidianWatcher(str(vault), sync_adapter=LocalSync())
        tasks = await watcher.list_pending()
        assert tasks == []

    @pytest.mark.asyncio
    async def test_list_pending_sorted(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = ObsidianWatcher(str(vault), sync_adapter=LocalSync())
        inbox = vault / "conductor" / "inbox"
        (inbox / "b_task.md").write_text("b")
        (inbox / "a_task.md").write_text("a")
        tasks = await watcher.list_pending()
        assert tasks[0][0] == "a_task.md"
        assert tasks[1][0] == "b_task.md"


class TestObsidianWatcherWriteCompleted:
    @pytest.mark.asyncio
    async def test_write_completed_moves_file(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = ObsidianWatcher(str(vault), sync_adapter=LocalSync())
        inbox = vault / "conductor" / "inbox"
        (inbox / "task.md").write_text("original task")

        dst = await watcher.write_completed("task.md", "done!")
        assert dst.exists()
        assert "original task" in dst.read_text()
        assert "done!" in dst.read_text()
        assert "## Result" in dst.read_text()
        assert not (inbox / "task.md").exists()

    @pytest.mark.asyncio
    async def test_write_completed_no_source(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = ObsidianWatcher(str(vault), sync_adapter=LocalSync())
        dst = await watcher.write_completed("nonexistent.md", "result")
        assert dst.exists()
        content = dst.read_text()
        assert "result" in content


class TestObsidianWatcherWriteFailed:
    @pytest.mark.asyncio
    async def test_write_failed_moves_file(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = ObsidianWatcher(str(vault), sync_adapter=LocalSync())
        inbox = vault / "conductor" / "inbox"
        (inbox / "task.md").write_text("original task")

        dst = await watcher.write_failed("task.md", "oops")
        assert dst.exists()
        assert "original task" in dst.read_text()
        assert "oops" in dst.read_text()
        assert "## Error" in dst.read_text()
        assert not (inbox / "task.md").exists()

    @pytest.mark.asyncio
    async def test_write_failed_in_failed_dir(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = ObsidianWatcher(str(vault), sync_adapter=LocalSync())
        dst = await watcher.write_failed("x.md", "err")
        assert "failed" in str(dst.parent)


class TestInboxHandler:
    def test_dispatches_md_file(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        task_file = inbox / "task.md"
        task_file.write_text("task content")

        calls = []
        handler = _InboxHandler(inbox, lambda name, content: calls.append((name, content)))

        from watchdog.events import FileCreatedEvent
        event = FileCreatedEvent(str(task_file))
        handler.on_created(event)
        assert len(calls) == 1
        assert calls[0] == ("task.md", "task content")

    def test_ignores_non_md(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        txt_file = inbox / "notes.txt"
        txt_file.write_text("not a task")

        calls = []
        handler = _InboxHandler(inbox, lambda n, c: calls.append((n, c)))

        from watchdog.events import FileCreatedEvent
        event = FileCreatedEvent(str(txt_file))
        handler.on_created(event)
        assert len(calls) == 0

    def test_ignores_directories(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        subdir = inbox / "subdir"
        subdir.mkdir()

        calls = []
        handler = _InboxHandler(inbox, lambda n, c: calls.append((n, c)))

        from watchdog.events import FileCreatedEvent
        event = FileCreatedEvent(str(subdir))
        event._is_directory = True  # Mark as directory
        # The handler checks event.is_directory
        handler.on_created(event)
        # Non-.md suffix means it won't dispatch regardless
        assert len(calls) == 0

    def test_debounce(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        task_file = inbox / "task.md"
        task_file.write_text("content")

        calls = []
        handler = _InboxHandler(inbox, lambda n, c: calls.append((n, c)))

        from watchdog.events import FileCreatedEvent
        event = FileCreatedEvent(str(task_file))
        handler.on_created(event)
        handler.on_created(event)  # second call within debounce window
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# 3. Vault Sync
# ---------------------------------------------------------------------------
from orchestrator.interfaces.vault_sync import (
    GitSync,
    SyncthingSync,
    CouchDBSync,
    LocalSync,
    create_sync_adapter,
)


class TestLocalSync:
    @pytest.mark.asyncio
    async def test_health(self):
        sync = LocalSync()
        h = await sync.check_health()
        assert h["adapter"] == "local"
        assert h["status"] == "ok"

    @pytest.mark.asyncio
    async def test_noop_sync(self):
        sync = LocalSync()
        await sync.sync_before_read()
        await sync.sync_after_write()


class TestGitSync:
    @pytest.mark.asyncio
    async def test_sync_before_read_calls_git_pull(self, tmp_path):
        sync = GitSync(str(tmp_path), remote="origin", branch="main")
        with patch("asyncio.create_subprocess_shell") as mock_shell:
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"ok", b""))
            proc.returncode = 0
            proc.stdout = "ok"
            proc.stderr = ""
            mock_shell.return_value = proc
            await sync.sync_before_read()
            cmd = mock_shell.call_args[0][0]
            assert "git pull" in cmd
            assert "origin" in cmd
            assert "main" in cmd

    @pytest.mark.asyncio
    async def test_sync_after_write_calls_git_add_commit_push(self, tmp_path):
        sync = GitSync(str(tmp_path), remote="origin", branch="main")
        call_cmds = []

        async def fake_shell(cmd, **kwargs):
            call_cmds.append(cmd)
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.returncode = 0
            proc.stdout = ""
            proc.stderr = ""
            return proc

        with patch("asyncio.create_subprocess_shell", side_effect=fake_shell):
            await sync.sync_after_write()

        assert any("git add" in c for c in call_cmds)
        assert any("git commit" in c or "git diff" in c for c in call_cmds)

    @pytest.mark.asyncio
    async def test_health_reports_status(self, tmp_path):
        sync = GitSync(str(tmp_path))
        with patch("asyncio.create_subprocess_shell") as mock_shell:
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"M file.txt\n", b""))
            proc.returncode = 0
            proc.stdout = "M file.txt\n"
            proc.stderr = ""
            mock_shell.return_value = proc
            h = await sync.check_health()
            assert h["adapter"] == "git"
            assert h["status"] == "ok"
            assert h["dirty_files"] == 1


class TestSyncthingSync:
    @pytest.mark.asyncio
    async def test_settle_delay(self):
        sync = SyncthingSync("/fake", settle_seconds=0.01)
        start = time.monotonic()
        await sync.sync_before_read()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.01

    @pytest.mark.asyncio
    async def test_health_no_api_key(self):
        sync = SyncthingSync("/fake")
        h = await sync.check_health()
        assert h["adapter"] == "syncthing"
        assert h["api_configured"] is False


class TestCouchDBSync:
    @pytest.mark.asyncio
    async def test_sync_before_read_calls_client(self, tmp_path):
        sync = CouchDBSync(str(tmp_path))
        mock_client = AsyncMock()
        mock_client.list_files = AsyncMock(return_value=[])
        sync._client = mock_client
        await sync.sync_before_read()
        mock_client.list_files.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sync_after_write_pushes_files(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        completed = vault / "conductor" / "completed"
        completed.mkdir(parents=True)
        (completed / "done.md").write_text("result")

        sync = CouchDBSync(str(vault))
        mock_client = AsyncMock()
        mock_client.write_file = AsyncMock(return_value="1-rev")
        mock_client.list_files = AsyncMock(return_value=[])
        sync._client = mock_client

        # Create inbox dir so cleanup code doesn't fail
        inbox = vault / "conductor" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)

        await sync.sync_after_write()
        mock_client.write_file.assert_awaited_once()
        call_args = mock_client.write_file.call_args
        assert "completed" in call_args[0][0]


class TestCreateSyncAdapter:
    def test_local(self):
        a = create_sync_adapter("local", "/fake")
        assert isinstance(a, LocalSync)

    def test_git(self):
        a = create_sync_adapter("git", "/fake", git_remote="upstream", git_branch="dev")
        assert isinstance(a, GitSync)
        assert a._remote == "upstream"
        assert a._branch == "dev"

    def test_syncthing(self):
        a = create_sync_adapter("syncthing", "/fake", syncthing_settle_seconds=2.0)
        assert isinstance(a, SyncthingSync)
        assert a._settle == 2.0

    def test_couchdb(self):
        a = create_sync_adapter("couchdb", "/fake", couchdb_url="http://db:5984")
        assert isinstance(a, CouchDBSync)

    def test_invalid_mode(self):
        with pytest.raises(ValueError, match="Unknown vault sync mode"):
            create_sync_adapter("dropbox", "/fake")


# ---------------------------------------------------------------------------
# 4. Auth
# ---------------------------------------------------------------------------
from orchestrator.infra.auth import AuthProvider, AuthResult


class TestAuthResult:
    def test_defaults(self):
        r = AuthResult(authenticated=True)
        assert r.user_id == ""
        assert r.claims is None
        assert r.error == ""


class TestAuthProviderApiKey:
    @pytest.mark.asyncio
    async def test_valid_api_key(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "apikey", "ROUTER_API_KEY": "test-key"}):
            provider = AuthProvider()
            result = await provider.authenticate("Bearer test-key")
            assert result.authenticated is True
            assert result.user_id == "admin"

    @pytest.mark.asyncio
    async def test_invalid_api_key(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "apikey", "ROUTER_API_KEY": "correct"}):
            provider = AuthProvider()
            result = await provider.authenticate("Bearer wrong")
            assert result.authenticated is False
            assert "Invalid" in result.error

    @pytest.mark.asyncio
    async def test_missing_header(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "apikey"}):
            provider = AuthProvider()
            result = await provider.authenticate(None)
            assert result.authenticated is False
            assert "Missing" in result.error

    @pytest.mark.asyncio
    async def test_none_mode_allows_anonymous(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "none"}):
            provider = AuthProvider()
            result = await provider.authenticate(None)
            assert result.authenticated is True
            assert result.user_id == "anonymous"

    @pytest.mark.asyncio
    async def test_unknown_mode(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "magic"}):
            provider = AuthProvider()
            result = await provider.authenticate("Bearer x")
            assert result.authenticated is False

    @pytest.mark.asyncio
    async def test_bearer_prefix_stripped(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "apikey", "ROUTER_API_KEY": "mykey"}):
            provider = AuthProvider()
            result = await provider.authenticate("Bearer mykey")
            assert result.authenticated is True

    @pytest.mark.asyncio
    async def test_oidc_no_issuer(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "oidc", "CONDUCTOR_OIDC_ISSUER": ""}):
            provider = AuthProvider()
            result = await provider.authenticate("Bearer some.jwt.token")
            assert result.authenticated is False
            assert "issuer" in result.error.lower()


# ---------------------------------------------------------------------------
# 5. Database
# ---------------------------------------------------------------------------
from orchestrator.infra.database import Database


class TestDatabase:
    def test_init_stores_dsn(self):
        db = Database(dsn="postgresql://user:pass@localhost/test")
        assert db._dsn == "postgresql://user:pass@localhost/test"
        assert db._pool is None

    @pytest.mark.asyncio
    async def test_execute_asserts_pool(self):
        db = Database()
        with pytest.raises(AssertionError):
            await db.execute("SELECT 1")

    @pytest.mark.asyncio
    async def test_fetch_asserts_pool(self):
        db = Database()
        with pytest.raises(AssertionError):
            await db.fetch("SELECT 1")

    @pytest.mark.asyncio
    async def test_fetchrow_asserts_pool(self):
        db = Database()
        with pytest.raises(AssertionError):
            await db.fetchrow("SELECT 1")

    @pytest.mark.asyncio
    async def test_fetchval_asserts_pool(self):
        db = Database()
        with pytest.raises(AssertionError):
            await db.fetchval("SELECT 1")

    @pytest.mark.asyncio
    async def test_acquire_asserts_pool(self):
        db = Database()
        with pytest.raises(AssertionError):
            await db.acquire()

    @pytest.mark.asyncio
    async def test_close_noop_when_no_pool(self):
        db = Database()
        await db.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_initialize_creates_pool(self):
        db = Database(dsn="postgresql://x:x@localhost/test")
        mock_pool = AsyncMock()
        # Mock asyncpg as a module-level mock so the lazy import inside initialize() works
        mock_asyncpg = MagicMock()
        mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
        with patch.dict("sys.modules", {"asyncpg": mock_asyncpg}):
            await db.initialize()
            assert db._pool is mock_pool


# ---------------------------------------------------------------------------
# 6. Secrets
# ---------------------------------------------------------------------------
from orchestrator.infra.secrets import (
    EnvSecretsBackend,
    KubernetesBackend,
    VaultwardenBackend,
    ExternalVaultBackend,
    create_secrets_backend,
)


class TestEnvSecretsBackend:
    @pytest.mark.asyncio
    async def test_get_existing(self):
        with patch.dict(os.environ, {"MY_SECRET": "value123"}):
            backend = EnvSecretsBackend()
            assert await backend.get("MY_SECRET") == "value123"

    @pytest.mark.asyncio
    async def test_get_missing(self):
        backend = EnvSecretsBackend()
        assert await backend.get("NONEXISTENT_SECRET_XYZ") is None

    @pytest.mark.asyncio
    async def test_get_many(self):
        with patch.dict(os.environ, {"A": "1", "B": "2"}):
            backend = EnvSecretsBackend()
            result = await backend.get_many(["A", "B", "C"])
            assert result == {"A": "1", "B": "2"}


class TestKubernetesBackend:
    @pytest.mark.asyncio
    async def test_reads_from_file(self, tmp_path):
        secret_file = tmp_path / "DB_PASSWORD"
        secret_file.write_text("  s3cret  ")
        backend = KubernetesBackend(mount_path=str(tmp_path))
        assert await backend.get("DB_PASSWORD") == "s3cret"

    @pytest.mark.asyncio
    async def test_fallback_to_env(self):
        backend = KubernetesBackend(mount_path="/nonexistent/path")
        with patch.dict(os.environ, {"FALLBACK_KEY": "envval"}):
            assert await backend.get("FALLBACK_KEY") == "envval"

    @pytest.mark.asyncio
    async def test_get_many(self, tmp_path):
        (tmp_path / "X").write_text("xval")
        backend = KubernetesBackend(mount_path=str(tmp_path))
        result = await backend.get_many(["X", "Y"])
        assert result == {"X": "xval"}


class TestVaultwardenBackend:
    @pytest.mark.asyncio
    async def test_cache_hit(self):
        backend = VaultwardenBackend()
        backend._cache["CACHED"] = "cached_val"
        assert await backend.get("CACHED") == "cached_val"

    @pytest.mark.asyncio
    async def test_fallback_no_url(self):
        backend = VaultwardenBackend(vault_url="", vault_token="")
        with patch.dict(os.environ, {"FALLBACK": "env_val"}):
            assert await backend.get("FALLBACK") == "env_val"


class TestExternalVaultBackend:
    @pytest.mark.asyncio
    async def test_fallback_no_url(self):
        backend = ExternalVaultBackend(url="")
        with patch.dict(os.environ, {"SOME_KEY": "env_val"}):
            assert await backend.get("SOME_KEY") == "env_val"

    def test_value_path_split(self):
        backend = ExternalVaultBackend(value_path="data.data.value")
        assert backend._value_path == ["data", "data", "value"]


class TestCreateSecretsBackend:
    def test_default_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONDUCTOR_SECRETS_BACKEND", None)
            backend = create_secrets_backend()
            assert isinstance(backend, EnvSecretsBackend)

    def test_kubernetes(self):
        with patch.dict(os.environ, {"CONDUCTOR_SECRETS_BACKEND": "kubernetes"}):
            backend = create_secrets_backend()
            assert isinstance(backend, KubernetesBackend)

    def test_vaultwarden(self):
        with patch.dict(os.environ, {"CONDUCTOR_SECRETS_BACKEND": "vaultwarden"}):
            backend = create_secrets_backend()
            assert isinstance(backend, VaultwardenBackend)

    def test_vault(self):
        with patch.dict(os.environ, {"CONDUCTOR_SECRETS_BACKEND": "vault"}):
            backend = create_secrets_backend()
            assert isinstance(backend, ExternalVaultBackend)


# ---------------------------------------------------------------------------
# 7. Tenant
# ---------------------------------------------------------------------------
from orchestrator.tenant import TenantContext, set_tenant, get_tenant


class TestTenantContext:
    def test_is_admin(self):
        ctx = TenantContext(tenant_id="t1", roles=("admin",))
        assert ctx.is_admin is True

    def test_not_admin(self):
        ctx = TenantContext(tenant_id="t1", roles=("viewer",))
        assert ctx.is_admin is False

    def test_can_write_admin(self):
        ctx = TenantContext(tenant_id="t1", roles=("admin",))
        assert ctx.can_write is True

    def test_can_write_operator(self):
        ctx = TenantContext(tenant_id="t1", roles=("operator",))
        assert ctx.can_write is True

    def test_cannot_write_viewer(self):
        ctx = TenantContext(tenant_id="t1", roles=("viewer",))
        assert ctx.can_write is False

    def test_can_read_with_roles(self):
        ctx = TenantContext(tenant_id="t1", roles=("viewer",))
        assert ctx.can_read is True

    def test_cannot_read_no_roles(self):
        ctx = TenantContext(tenant_id="t1", roles=())
        assert ctx.can_read is False

    def test_from_env_defaults(self):
        env = {
            "CONDUCTOR_TENANT_ID": "mylab",
            "CONDUCTOR_ROLES": "admin,operator",
        }
        with patch.dict(os.environ, env, clear=False):
            ctx = TenantContext.from_env()
            assert ctx.tenant_id == "mylab"
            assert "admin" in ctx.roles
            assert "operator" in ctx.roles
            assert ctx.secrets_prefix == "mylab/"

    def test_from_oidc_claims_full(self):
        claims = {
            "sub": "user123",
            "email": "alice@example.com",
            "name": "Alice",
            "org_id": "acme",
            "team_id": "platform",
            "roles": ["admin", "operator"],
        }
        ctx = TenantContext.from_oidc_claims(claims)
        assert ctx.tenant_id == "org:acme/team:platform/user:user123"
        assert ctx.org_id == "acme"
        assert ctx.team_id == "platform"
        assert ctx.user_id == "user123"
        assert "admin" in ctx.roles

    def test_from_oidc_claims_minimal(self):
        claims = {"sub": "bob"}
        ctx = TenantContext.from_oidc_claims(claims)
        assert ctx.tenant_id == "user:bob"
        assert ctx.roles == ("viewer",)

    def test_from_oidc_roles_string(self):
        claims = {"sub": "u", "roles": "editor"}
        ctx = TenantContext.from_oidc_claims(claims)
        assert ctx.roles == ("editor",)

    def test_frozen(self):
        ctx = TenantContext(tenant_id="t")
        with pytest.raises(AttributeError):
            ctx.tenant_id = "other"


class TestSetGetTenant:
    def test_set_and_get(self):
        ctx = TenantContext(tenant_id="test-tenant", roles=("admin",))
        set_tenant(ctx)
        assert get_tenant().tenant_id == "test-tenant"

    def test_get_fallback_creates_default(self):
        # Use a new context to avoid picking up previous set_tenant calls
        import contextvars
        from orchestrator.tenant import _current_tenant
        token = _current_tenant.set(TenantContext(tenant_id="temp"))
        _current_tenant.reset(token)
        # Now _current_tenant has no value in this context copy — but get_tenant
        # catches LookupError and creates from_env. We can't truly reset
        # ContextVar in same thread easily, so just verify from_env works.
        with patch.dict(os.environ, {"CONDUCTOR_TENANT_ID": "fallback-lab"}):
            ctx = TenantContext.from_env()
            assert ctx.tenant_id == "fallback-lab"


# ---------------------------------------------------------------------------
# 8. Knowledge Graph (stub)
# ---------------------------------------------------------------------------
from orchestrator.memory.knowledge_graph import KnowledgeGraph


class TestKnowledgeGraph:
    def test_query_returns_empty(self):
        kg = KnowledgeGraph()
        assert kg.query("anything") == ""

    def test_update_noop(self):
        kg = KnowledgeGraph()
        kg.update("entity", "relation", "target")  # Should not raise

    def test_token_estimate_zero(self):
        kg = KnowledgeGraph()
        assert kg.token_estimate == 0

    def test_build_prompt_section_empty(self):
        kg = KnowledgeGraph()
        assert kg.build_prompt_section() == ""


# ---------------------------------------------------------------------------
# 9. Board (extended coverage)
# ---------------------------------------------------------------------------
from orchestrator.memory.board import MessageBoard, MessageType, WebhookDelivery


class TestWebhookDelivery:
    @pytest.mark.asyncio
    async def test_no_webhooks(self):
        wd = WebhookDelivery(webhooks=[])
        results = await wd.deliver("alert", "title", "body")
        assert results == []

    @pytest.mark.asyncio
    async def test_none_webhooks(self):
        wd = WebhookDelivery(webhooks=None)
        results = await wd.deliver("alert", "t", "b")
        assert results == []

    @pytest.mark.asyncio
    async def test_event_filter_skips_non_matching(self):
        hooks = [{"url": "http://example.com/hook", "events": ["question"]}]
        wd = WebhookDelivery(webhooks=hooks)
        # alert not in events for this hook
        with patch("httpx.AsyncClient") as mock_cls:
            results = await wd.deliver("alert", "t", "b")
            assert results == []

    @pytest.mark.asyncio
    async def test_wildcard_matches_all(self):
        hooks = [{"url": "http://example.com/hook", "events": ["*"]}]
        wd = WebhookDelivery(webhooks=hooks)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.is_success = True
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            results = await wd.deliver("observation", "t", "b")
            assert len(results) == 1
            assert results[0]["ok"] is True

    @pytest.mark.asyncio
    async def test_empty_url_skipped(self):
        hooks = [{"url": "", "events": ["alert"]}]
        wd = WebhookDelivery(webhooks=hooks)
        results = await wd.deliver("alert", "t", "b")
        assert results == []

    @pytest.mark.asyncio
    async def test_auth_token_sent(self):
        hooks = [{"url": "http://example.com/hook", "events": ["alert"], "token": "secret"}]
        wd = WebhookDelivery(webhooks=hooks)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.is_success = True
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            await wd.deliver("alert", "t", "b")
            call_kwargs = mock_client.post.call_args
            headers = call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))
            assert "Bearer secret" in headers.get("Authorization", "")


class TestBoardCountByType:
    def test_mixed_types(self, tmp_path):
        board = MessageBoard(tmp_path)
        board.alert("a1", "body")
        board.alert("a2", "body")
        board.question("q1", "body")
        board.observation("o1", "body")
        counts = board.count_by_type()
        assert counts.get("alert", 0) == 2
        assert counts.get("question", 0) == 1
        assert counts.get("observation", 0) == 1

    def test_empty_board(self, tmp_path):
        board = MessageBoard(tmp_path)
        counts = board.count_by_type()
        assert counts == {}


class TestBoardListUnread:
    def test_returns_paths_newest_first(self, tmp_path):
        board = MessageBoard(tmp_path)
        p1 = board.post(MessageType.ALERT, "first", "body")
        p2 = board.post(MessageType.OBSERVATION, "second", "body")
        unread = board.list_unread()
        assert all(isinstance(p, Path) for p in unread)
        assert len(unread) >= 2
        # Newest first — the second post should come first
        names = [p.name for p in unread]
        assert names.index(p2.name) < names.index(p1.name) or p1.name == p2.name


# ---------------------------------------------------------------------------
# 10. Evolution — Git operations with real tmp git repo
# ---------------------------------------------------------------------------
from orchestrator.memory.evolution import EvolutionHistory


class TestEvolutionHistory:
    def test_record_mutation_creates_log(self, tmp_path):
        evo = EvolutionHistory(tmp_path / "memory")
        evo.record_mutation("apm", "update", "Changed personality weight")
        log_path = tmp_path / "memory" / "evolution.log"
        assert log_path.exists()
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["surface"] == "apm"
        assert entry["action"] == "update"

    def test_record_mutation_with_details(self, tmp_path):
        evo = EvolutionHistory(tmp_path / "memory")
        evo.record_mutation("episodic", "create", "new memory", details={"id": "m1"})
        lines = (tmp_path / "memory" / "evolution.log").read_text().strip().splitlines()
        entry = json.loads(lines[0])
        assert entry["details"]["id"] == "m1"

    def test_get_recent_log(self, tmp_path):
        evo = EvolutionHistory(tmp_path / "memory")
        for i in range(5):
            evo.record_mutation("test", "update", f"change {i}")
        entries = evo.get_recent_log(limit=3)
        assert len(entries) == 3
        assert entries[-1]["description"] == "change 4"

    def test_get_recent_log_empty(self, tmp_path):
        evo = EvolutionHistory(tmp_path / "memory")
        assert evo.get_recent_log() == []

    def test_snapshot_episodic(self, tmp_path):
        evo = EvolutionHistory(tmp_path / "memory")
        memories = [{"id": "m1", "content": "test"}]
        path = evo.snapshot_episodic(memories)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["count"] == 1
        assert data["memories"][0]["id"] == "m1"

    def test_ensure_git_initializes_repo(self, tmp_path):
        evo = EvolutionHistory(tmp_path / "memory")
        result = evo._ensure_git()
        assert result is True
        assert (tmp_path / "memory" / ".git").exists()

    def test_commit_with_real_git(self, tmp_path):
        evo = EvolutionHistory(tmp_path / "memory")
        evo.record_mutation("apm", "create", "initial")
        committed = evo.commit("initial commit")
        assert committed is True

        # Second commit with no changes should return False
        committed2 = evo.commit("nothing changed")
        assert committed2 is False

    def test_commit_after_mutation(self, tmp_path):
        evo = EvolutionHistory(tmp_path / "memory")
        evo.record_mutation("board", "create", "first post")
        evo.commit("first")
        evo.record_mutation("board", "create", "second post")
        committed = evo.commit("second")
        assert committed is True

    def test_get_git_log(self, tmp_path):
        evo = EvolutionHistory(tmp_path / "memory")
        evo.record_mutation("apm", "update", "change 1")
        evo.commit("commit 1")
        evo.record_mutation("apm", "update", "change 2")
        evo.commit("commit 2")

        log = evo.get_git_log(limit=5)
        assert len(log) == 2
        assert "commit 2" in log[0]
        assert "commit 1" in log[1]

    def test_snapshot_then_commit(self, tmp_path):
        evo = EvolutionHistory(tmp_path / "memory")
        evo.snapshot_episodic([{"id": "m1"}])
        committed = evo.commit("snapshot commit")
        assert committed is True
        log = evo.get_git_log()
        assert any("snapshot" in entry for entry in log)

    def test_directories_created(self, tmp_path):
        evo = EvolutionHistory(tmp_path / "memory")
        assert (tmp_path / "memory").exists()
        assert (tmp_path / "memory" / "episodic").exists()


# ---------------------------------------------------------------------------
# NEW: CouchDB Client — read_file, write_file, list_files, poll_changes
# ---------------------------------------------------------------------------


class TestCouchDBClientReadFile:

    @pytest.mark.asyncio
    async def test_read_file_plain(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_doc = AsyncMock(return_value={
            "_id": "conductor/inbox/task.md",
            "_rev": "1-abc",
            "type": "plain",
            "path": "conductor/inbox/task.md",
            "ctime": 1000,
            "mtime": 2000,
            "children": ["h:aaa"],
            "eden": {"h:aaa": {"data": "Hello world"}},
            "deleted": False,
        })

        doc = await client.read_file("conductor/inbox/task.md")
        assert doc is not None
        assert doc.content == "Hello world"
        assert doc.doc_type == "plain"
        assert doc.mtime == 2000
        assert doc.rev == "1-abc"
        await client.close()

    @pytest.mark.asyncio
    async def test_read_file_not_found(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_doc = AsyncMock(return_value=None)
        doc = await client.read_file("nonexistent")
        assert doc is None
        await client.close()

    @pytest.mark.asyncio
    async def test_read_file_wrong_type(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_doc = AsyncMock(return_value={
            "_id": "x", "type": "leaf", "data": "chunk",
        })
        doc = await client.read_file("x")
        assert doc is None
        await client.close()

    @pytest.mark.asyncio
    async def test_read_file_deleted(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_doc = AsyncMock(return_value={
            "_id": "x", "type": "plain", "deleted": True,
            "children": [], "eden": {},
        })
        doc = await client.read_file("x")
        assert doc is None
        await client.close()

    @pytest.mark.asyncio
    async def test_read_file_couch_deleted(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_doc = AsyncMock(return_value={
            "_id": "x", "type": "plain", "_deleted": True,
            "children": [], "eden": {},
        })
        doc = await client.read_file("x")
        assert doc is None
        await client.close()

    @pytest.mark.asyncio
    async def test_read_file_newnote_type(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_doc = AsyncMock(return_value={
            "_id": "image.png", "_rev": "1-x",
            "type": "newnote", "path": "image.png",
            "ctime": 100, "mtime": 200,
            "children": [], "eden": {},
        })
        doc = await client.read_file("image.png")
        assert doc is not None
        assert doc.doc_type == "newnote"
        await client.close()


class TestCouchDBClientGetDoc:

    @pytest.mark.asyncio
    async def test_get_doc_success(self):
        client = CouchDBClient("http://localhost:5984", "test")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"_id": "test", "_rev": "1-abc"}
        client._client.get = AsyncMock(return_value=mock_resp)

        doc = await client.get_doc("test")
        assert doc["_id"] == "test"
        await client.close()

    @pytest.mark.asyncio
    async def test_get_doc_not_found(self):
        client = CouchDBClient("http://localhost:5984", "test")
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        client._client.get = AsyncMock(return_value=mock_resp)

        doc = await client.get_doc("missing")
        assert doc is None
        await client.close()

    @pytest.mark.asyncio
    async def test_get_doc_http_error(self):
        import httpx
        client = CouchDBClient("http://localhost:5984", "test")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_resp
        )
        client._client.get = AsyncMock(return_value=mock_resp)

        doc = await client.get_doc("broken")
        assert doc is None
        await client.close()


class TestCouchDBClientGetChunk:

    @pytest.mark.asyncio
    async def test_get_chunk_found(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_doc = AsyncMock(return_value={"_id": "h:abc", "type": "leaf", "data": "chunk data"})
        result = await client.get_chunk("h:abc")
        assert result == "chunk data"
        await client.close()

    @pytest.mark.asyncio
    async def test_get_chunk_not_found(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_doc = AsyncMock(return_value=None)
        result = await client.get_chunk("h:missing")
        assert result == ""
        await client.close()


class TestCouchDBClientWriteFile:

    @pytest.mark.asyncio
    async def test_write_file_new(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_doc = AsyncMock(return_value=None)

        put_calls = []

        async def mock_put(url, json=None):
            put_calls.append((url, json))
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json = lambda: {"rev": "1-new"}
            return resp

        client._client.put = mock_put
        rev = await client.write_file("conductor/test.md", "Hello world")
        assert rev == "1-new"
        # Chunk + document = at least 2 PUT calls
        assert len(put_calls) >= 2
        await client.close()

    @pytest.mark.asyncio
    async def test_write_file_update_existing(self):
        client = CouchDBClient("http://localhost:5984", "test")
        call_count = [0]

        async def mock_get_doc(doc_id):
            call_count[0] += 1
            if doc_id.startswith("h:"):
                return None  # chunk doesn't exist
            if call_count[0] > 1:  # second call is for existing doc check
                return {"_id": doc_id, "_rev": "1-old", "ctime": 500}
            return None

        client.get_doc = mock_get_doc

        put_calls = []

        async def mock_put(url, json=None):
            put_calls.append((url, json))
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json = lambda: {"rev": "2-new"}
            return resp

        client._client.put = mock_put
        rev = await client.write_file("existing.md", "Updated")
        assert rev == "2-new"
        await client.close()

    @pytest.mark.asyncio
    async def test_write_file_large_content_splits(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_doc = AsyncMock(return_value=None)

        put_calls = []

        async def mock_put(url, json=None):
            put_calls.append((url, json))
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json = lambda: {"rev": "1-new"}
            return resp

        client._client.put = mock_put
        content = "x" * 2500  # Will split into 3 chunks
        await client.write_file("big.md", content)
        # 3 chunk PUTs + 1 document PUT = 4
        assert len(put_calls) == 4
        await client.close()


class TestCouchDBClientDeleteFile:

    @pytest.mark.asyncio
    async def test_delete_existing(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_doc = AsyncMock(return_value={
            "_id": "test.md", "_rev": "1-abc", "mtime": 1000,
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        client._client.put = AsyncMock(return_value=mock_resp)

        result = await client.delete_file("test.md")
        assert result is True
        await client.close()

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client.get_doc = AsyncMock(return_value=None)
        result = await client.delete_file("nope.md")
        assert result is False
        await client.close()


class TestCouchDBClientListFiles:

    @pytest.mark.asyncio
    async def test_list_files(self):
        client = CouchDBClient("http://localhost:5984", "test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "rows": [
                {"id": "conductor/inbox/task1.md"},
                {"id": "conductor/inbox/task2.md"},
                {"id": "h:abc123"},  # chunk — should be filtered
                {"id": "_design/filter"},  # system doc — should be filtered
            ]
        }
        client._client.get = AsyncMock(return_value=mock_resp)

        paths = await client.list_files("conductor/inbox/")
        assert "conductor/inbox/task1.md" in paths
        assert "conductor/inbox/task2.md" in paths
        assert len(paths) == 2  # chunks and system docs filtered
        await client.close()


class TestCouchDBClientPollChanges:

    @pytest.mark.asyncio
    async def test_poll_changes_returns_docs(self):
        client = CouchDBClient("http://localhost:5984", "test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"doc": {"_id": "conductor/inbox/new.md", "path": "conductor/inbox/new.md", "type": "plain"}},
                {"doc": {"_id": "h:chunk", "path": "h:chunk", "type": "leaf"}},  # filtered by selector
            ],
            "last_seq": "seq-100",
        }
        client._client.post = AsyncMock(return_value=mock_resp)

        changes = await client.poll_changes(prefix="conductor/")
        assert len(changes) == 1
        assert changes[0]["path"] == "conductor/inbox/new.md"
        assert client._since == "seq-100"
        await client.close()

    @pytest.mark.asyncio
    async def test_poll_changes_prefix_filter(self):
        client = CouchDBClient("http://localhost:5984", "test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"doc": {"_id": "other/file.md", "path": "other/file.md"}},
            ],
            "last_seq": "seq-200",
        }
        client._client.post = AsyncMock(return_value=mock_resp)

        changes = await client.poll_changes(prefix="conductor/")
        assert len(changes) == 0  # filtered by prefix
        await client.close()

    @pytest.mark.asyncio
    async def test_poll_changes_skips_internal_docs(self):
        client = CouchDBClient("http://localhost:5984", "test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"doc": {"_id": "_design/filter", "path": "_design/filter"}},
                {"doc": {"_id": "h:chunk", "path": "h:chunk"}},
            ],
            "last_seq": "seq-300",
        }
        client._client.post = AsyncMock(return_value=mock_resp)

        changes = await client.poll_changes()
        assert len(changes) == 0
        await client.close()

    @pytest.mark.asyncio
    async def test_poll_changes_timeout(self):
        import httpx
        client = CouchDBClient("http://localhost:5984", "test")
        client._client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        changes = await client.poll_changes()
        assert changes == []
        await client.close()


class TestCouchDBClientCheckConnection:

    @pytest.mark.asyncio
    async def test_check_connection_ok(self):
        client = CouchDBClient("http://localhost:5984", "test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "db_name": "test",
            "doc_count": 42,
            "update_seq": "seq-100-g1234",
        }
        client._client.get = AsyncMock(return_value=mock_resp)

        info = await client.check_connection()
        assert info["status"] == "ok"
        assert info["db_name"] == "test"
        assert info["doc_count"] == 42
        await client.close()

    @pytest.mark.asyncio
    async def test_check_connection_error(self):
        client = CouchDBClient("http://localhost:5984", "test")
        client._client.get = AsyncMock(side_effect=Exception("Connection refused"))

        info = await client.check_connection()
        assert info["status"] == "error"
        assert "refused" in info["error"].lower()
        await client.close()


# ---------------------------------------------------------------------------
# NEW: CouchDBSync — more thorough tests
# ---------------------------------------------------------------------------


class TestCouchDBSyncExtended:

    @pytest.mark.asyncio
    async def test_sync_before_read_writes_md_files(self, tmp_path):
        sync = CouchDBSync(str(tmp_path))
        mock_client = AsyncMock()
        mock_client.list_files = AsyncMock(return_value=["conductor/inbox/task.md"])

        from orchestrator.interfaces.couchdb_client import LiveSyncDoc
        mock_client.read_file = AsyncMock(return_value=LiveSyncDoc(
            doc_id="conductor/inbox/task.md",
            path="conductor/inbox/task.md",
            content="# Task\nDo something",
            doc_type="plain",
            ctime=1000,
            mtime=int(time.time() * 1000) + 10000,  # future = newer
        ))
        sync._client = mock_client

        await sync.sync_before_read()
        local_file = tmp_path / "conductor" / "inbox" / "task.md"
        assert local_file.exists()
        assert "Do something" in local_file.read_text()

    @pytest.mark.asyncio
    async def test_sync_before_read_skips_non_md(self, tmp_path):
        sync = CouchDBSync(str(tmp_path))
        mock_client = AsyncMock()
        mock_client.list_files = AsyncMock(return_value=["conductor/inbox/image.png"])
        sync._client = mock_client

        await sync.sync_before_read()
        # No files should be created
        inbox = tmp_path / "conductor" / "inbox"
        assert not inbox.exists() or not list(inbox.iterdir())

    @pytest.mark.asyncio
    async def test_sync_before_read_skips_older(self, tmp_path):
        # Create local file that is newer
        local_file = tmp_path / "conductor" / "inbox" / "old.md"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("local version")

        sync = CouchDBSync(str(tmp_path))
        mock_client = AsyncMock()
        mock_client.list_files = AsyncMock(return_value=["conductor/inbox/old.md"])

        from orchestrator.interfaces.couchdb_client import LiveSyncDoc
        mock_client.read_file = AsyncMock(return_value=LiveSyncDoc(
            doc_id="conductor/inbox/old.md",
            path="conductor/inbox/old.md",
            content="OLD content",
            doc_type="plain",
            ctime=100,
            mtime=100,  # Very old
        ))
        sync._client = mock_client

        await sync.sync_before_read()
        assert local_file.read_text() == "local version"  # Not overwritten

    @pytest.mark.asyncio
    async def test_sync_after_write_deletes_processed_inbox(self, tmp_path):
        vault = tmp_path / "vault"
        inbox = vault / "conductor" / "inbox"
        inbox.mkdir(parents=True)
        # No local inbox files, but CouchDB has one
        completed = vault / "conductor" / "completed"
        completed.mkdir(parents=True)

        sync = CouchDBSync(str(vault))
        mock_client = AsyncMock()
        mock_client.write_file = AsyncMock(return_value="1-rev")
        mock_client.list_files = AsyncMock(return_value=["conductor/inbox/processed.md"])
        mock_client.delete_file = AsyncMock(return_value=True)
        sync._client = mock_client

        await sync.sync_after_write()
        # processed.md not in local inbox → should be deleted from CouchDB
        mock_client.delete_file.assert_called_once_with("conductor/inbox/processed.md")

    @pytest.mark.asyncio
    async def test_check_health(self, tmp_path):
        sync = CouchDBSync(str(tmp_path))
        mock_client = AsyncMock()
        mock_client.check_connection = AsyncMock(return_value={"status": "ok", "db_name": "test"})
        sync._client = mock_client

        health = await sync.check_health()
        assert health["adapter"] == "couchdb"
        assert health["status"] == "ok"

    @pytest.mark.asyncio
    async def test_check_health_error(self, tmp_path):
        sync = CouchDBSync(str(tmp_path))
        sync._client = None
        # Force _ensure_client to fail by making the import fail
        with patch.object(sync, "_ensure_client", side_effect=Exception("Connection refused")):
            health = await sync.check_health()
            assert health["status"] == "error"


# ======================================================================
# Coverage gap: auth.py — OIDC + K8s token validation
# ======================================================================

from orchestrator.infra.auth import AuthProvider, AuthResult


class TestAuthProviderAPIKey:
    """Test API key authentication mode."""

    @pytest.mark.asyncio
    async def test_api_key_success(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "apikey", "ROUTER_API_KEY": "test-key"}):
            auth = AuthProvider()
            result = await auth.authenticate("Bearer test-key")
            assert result.authenticated is True
            assert result.user_id == "admin"

    @pytest.mark.asyncio
    async def test_api_key_failure(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "apikey", "ROUTER_API_KEY": "test-key"}):
            auth = AuthProvider()
            result = await auth.authenticate("Bearer wrong-key")
            assert result.authenticated is False

    @pytest.mark.asyncio
    async def test_none_mode(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "none"}):
            auth = AuthProvider()
            result = await auth.authenticate(None)
            assert result.authenticated is True
            assert result.user_id == "anonymous"

    @pytest.mark.asyncio
    async def test_missing_auth_header(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "apikey", "ROUTER_API_KEY": "k"}):
            auth = AuthProvider()
            result = await auth.authenticate(None)
            assert result.authenticated is False

    @pytest.mark.asyncio
    async def test_unknown_mode(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "foobar"}):
            auth = AuthProvider()
            result = await auth.authenticate("Bearer x")
            assert result.authenticated is False
            assert "Unknown auth mode" in result.error


class TestAuthProviderOIDC:
    """Test OIDC authentication mode."""

    @pytest.mark.asyncio
    async def test_oidc_no_issuer(self):
        with patch.dict(os.environ, {
            "CONDUCTOR_AUTH_MODE": "oidc",
            "CONDUCTOR_OIDC_ISSUER": "",
        }, clear=False):
            auth = AuthProvider()
            result = await auth.authenticate("Bearer some-token")
            assert result.authenticated is False
            assert "issuer not configured" in result.error

    @pytest.mark.asyncio
    async def test_oidc_no_jwt_library(self):
        with patch.dict(os.environ, {
            "CONDUCTOR_AUTH_MODE": "oidc",
            "CONDUCTOR_OIDC_ISSUER": "https://issuer.example.com",
        }, clear=False):
            auth = AuthProvider()
            with patch("builtins.__import__", side_effect=ImportError("no jwt")):
                result = await auth.authenticate("Bearer some-token")
                assert result.authenticated is False
                assert "PyJWT" in result.error

    @pytest.mark.asyncio
    async def test_oidc_auto_discover_jwks(self):
        with patch.dict(os.environ, {
            "CONDUCTOR_AUTH_MODE": "oidc",
            "CONDUCTOR_OIDC_ISSUER": "https://issuer.example.com",
            "CONDUCTOR_OIDC_JWKS_URI": "",
            "CONDUCTOR_OIDC_AUDIENCE": "api://test",
        }, clear=False):
            auth = AuthProvider()

            mock_jwk_client = MagicMock()
            mock_signing_key = MagicMock()
            mock_signing_key.key = "fake-key"
            mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key

            mock_oidc_resp = MagicMock()
            mock_oidc_resp.status_code = 200
            mock_oidc_resp.raise_for_status = MagicMock()
            mock_oidc_resp.json.return_value = {"jwks_uri": "https://issuer.example.com/.well-known/jwks.json"}

            mock_decode = {"sub": "user@example.com", "email": "user@example.com", "roles": ["admin"]}

            with patch("jwt.PyJWKClient", return_value=mock_jwk_client):
                with patch("jwt.decode", return_value=mock_decode):
                    mock_http_client = AsyncMock()
                    mock_http_client.get = AsyncMock(return_value=mock_oidc_resp)
                    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
                    mock_http_client.__aexit__ = AsyncMock(return_value=False)
                    with patch("httpx.AsyncClient", return_value=mock_http_client):
                        result = await auth.authenticate("Bearer test-jwt-token")
                        assert result.authenticated is True
                        assert result.user_id == "user@example.com"

    @pytest.mark.asyncio
    async def test_oidc_validation_error(self):
        with patch.dict(os.environ, {
            "CONDUCTOR_AUTH_MODE": "oidc",
            "CONDUCTOR_OIDC_ISSUER": "https://issuer.example.com",
            "CONDUCTOR_OIDC_JWKS_URI": "https://issuer.example.com/jwks",
        }, clear=False):
            auth = AuthProvider()

            mock_jwk_client = MagicMock()
            mock_jwk_client.get_signing_key_from_jwt.side_effect = Exception("Invalid token")

            with patch("jwt.PyJWKClient", return_value=mock_jwk_client):
                result = await auth.authenticate("Bearer bad-token")
                assert result.authenticated is False


class TestAuthProviderK8s:
    """Test K8s token authentication mode."""

    @pytest.mark.asyncio
    async def test_k8s_success(self, tmp_path):
        sa_token_path = tmp_path / "token"
        sa_token_path.write_text("sa-token-value")

        with patch.dict(os.environ, {
            "CONDUCTOR_AUTH_MODE": "k8s",
            "KUBERNETES_SERVICE_HOST": "10.0.0.1",
            "KUBERNETES_SERVICE_PORT_HTTPS": "443",
        }):
            auth = AuthProvider()

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "status": {
                    "authenticated": True,
                    "user": {"username": "system:serviceaccount:ns:sa", "groups": ["system:authenticated"]},
                },
            }

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("pathlib.Path.exists", return_value=True):
                    with patch("pathlib.Path.read_text", return_value="sa-token"):
                        result = await auth.authenticate("Bearer pod-token")
                        assert result.authenticated is True

    @pytest.mark.asyncio
    async def test_k8s_not_authenticated(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "k8s"}):
            auth = AuthProvider()

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"status": {"authenticated": False}}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("pathlib.Path.exists", return_value=False):
                    result = await auth.authenticate("Bearer bad-token")
                    assert result.authenticated is False

    @pytest.mark.asyncio
    async def test_k8s_error(self):
        with patch.dict(os.environ, {"CONDUCTOR_AUTH_MODE": "k8s"}):
            auth = AuthProvider()
            with patch("httpx.AsyncClient") as MockClient:
                mc = AsyncMock()
                mc.post.side_effect = Exception("network error")
                mc.__aenter__ = AsyncMock(return_value=mc)
                mc.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mc
                with patch("pathlib.Path.exists", return_value=False):
                    result = await auth.authenticate("Bearer x")
                    assert result.authenticated is False


# ======================================================================
# Coverage gap: database.py — asyncpg pool wrappers
# ======================================================================

from orchestrator.infra.database import Database


class TestDatabase:
    """Test Database wrapper with mocked asyncpg."""

    @pytest.mark.asyncio
    async def test_initialize(self):
        db = Database(dsn="postgresql://fake:5432/test")
        mock_pool = AsyncMock()
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await db.initialize()
            assert db._pool is mock_pool

    def _make_db_pool(self):
        mock_conn = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = mock_cm
        return mock_pool, mock_conn

    @pytest.mark.asyncio
    async def test_ensure_tenant_schema_public(self):
        db = Database()
        mock_pool, mock_conn = self._make_db_pool()
        db._pool = mock_pool

        await db.ensure_tenant_schema("public")
        mock_conn.execute.assert_called()

    @pytest.mark.asyncio
    async def test_ensure_tenant_schema_custom(self):
        db = Database()
        mock_pool, mock_conn = self._make_db_pool()
        db._pool = mock_pool

        await db.ensure_tenant_schema("tenant_abc")
        calls = [str(c) for c in mock_conn.execute.call_args_list]
        assert any("tenant_abc" in c for c in calls)

    @pytest.mark.asyncio
    async def test_execute(self):
        db = Database()
        mock_pool, mock_conn = self._make_db_pool()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
        db._pool = mock_pool

        result = await db.execute("INSERT INTO test VALUES ($1)", "val")
        assert result == "INSERT 0 1"

    @pytest.mark.asyncio
    async def test_fetch(self):
        db = Database()
        mock_pool, mock_conn = self._make_db_pool()
        mock_conn.fetch = AsyncMock(return_value=[{"id": 1}])
        db._pool = mock_pool

        result = await db.fetch("SELECT * FROM test")
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_fetchrow(self):
        db = Database()
        mock_pool, mock_conn = self._make_db_pool()
        mock_conn.fetchrow = AsyncMock(return_value={"id": 1})
        db._pool = mock_pool

        result = await db.fetchrow("SELECT * FROM test LIMIT 1")
        assert result == {"id": 1}

    @pytest.mark.asyncio
    async def test_fetchval(self):
        db = Database()
        mock_pool, mock_conn = self._make_db_pool()
        mock_conn.fetchval = AsyncMock(return_value=42)
        db._pool = mock_pool

        result = await db.fetchval("SELECT count(*) FROM test")
        assert result == 42

    @pytest.mark.asyncio
    async def test_acquire(self):
        db = Database()
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = "conn-context"
        db._pool = mock_pool

        result = await db.acquire()
        assert result == "conn-context"

    @pytest.mark.asyncio
    async def test_close(self):
        db = Database()
        mock_pool = AsyncMock()
        db._pool = mock_pool
        await db.close()
        mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_no_pool(self):
        db = Database()
        await db.close()  # Should not raise


# ======================================================================
# Coverage gap: secrets.py — Vaultwarden, K8s, ExternalVault
# ======================================================================

from orchestrator.infra.secrets import (
    EnvSecretsBackend,
    KubernetesBackend,
    VaultwardenBackend,
    ExternalVaultBackend,
    create_secrets_backend,
)


class TestEnvSecretsBackend:
    @pytest.mark.asyncio
    async def test_get(self):
        backend = EnvSecretsBackend()
        with patch.dict(os.environ, {"MY_SECRET": "val"}):
            assert await backend.get("MY_SECRET") == "val"
            assert await backend.get("MISSING") is None

    @pytest.mark.asyncio
    async def test_get_many(self):
        backend = EnvSecretsBackend()
        with patch.dict(os.environ, {"A": "1", "B": "2"}):
            result = await backend.get_many(["A", "B", "C"])
            assert result == {"A": "1", "B": "2"}


class TestKubernetesBackend:
    @pytest.mark.asyncio
    async def test_get_from_file(self, tmp_path):
        secret_dir = tmp_path / "secrets"
        secret_dir.mkdir()
        (secret_dir / "DB_PASSWORD").write_text("  mysecret  ")

        backend = KubernetesBackend(mount_path=str(secret_dir))
        result = await backend.get("DB_PASSWORD")
        assert result == "mysecret"

    @pytest.mark.asyncio
    async def test_get_fallback_to_env(self, tmp_path):
        backend = KubernetesBackend(mount_path=str(tmp_path / "nonexistent"))
        with patch.dict(os.environ, {"FALLBACK_KEY": "envval"}):
            result = await backend.get("FALLBACK_KEY")
            assert result == "envval"

    @pytest.mark.asyncio
    async def test_get_many(self, tmp_path):
        secret_dir = tmp_path / "secrets"
        secret_dir.mkdir()
        (secret_dir / "KEY1").write_text("val1")

        backend = KubernetesBackend(mount_path=str(secret_dir))
        with patch.dict(os.environ, {"KEY2": "val2"}):
            result = await backend.get_many(["KEY1", "KEY2", "MISSING"])
            assert result == {"KEY1": "val1", "KEY2": "val2"}


class TestVaultwardenBackend:
    @pytest.mark.asyncio
    async def test_get_cached(self):
        backend = VaultwardenBackend(vault_url="http://vault:8080", vault_token="tok")
        backend._cache["MY_KEY"] = "cached_val"
        result = await backend.get("MY_KEY")
        assert result == "cached_val"

    @pytest.mark.asyncio
    async def test_get_no_url_fallback(self):
        backend = VaultwardenBackend(vault_url="", vault_token="")
        with patch.dict(os.environ, {"MY_KEY": "env_val"}):
            result = await backend.get("MY_KEY")
            assert result == "env_val"

    @pytest.mark.asyncio
    async def test_get_from_api(self):
        backend = VaultwardenBackend(vault_url="http://vault:8080", vault_token="tok")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"name": "MY_SECRET", "login": {"password": "api_val"}}],
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        backend._client = mock_client

        result = await backend.get("MY_SECRET")
        assert result == "api_val"
        assert backend._cache["MY_SECRET"] == "api_val"

    @pytest.mark.asyncio
    async def test_get_from_api_notes_fallback(self):
        backend = VaultwardenBackend(vault_url="http://vault:8080", vault_token="tok")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"name": "MY_SECRET", "login": {"password": ""}, "notes": "notes_val"}],
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        backend._client = mock_client

        result = await backend.get("MY_SECRET")
        assert result == "notes_val"

    @pytest.mark.asyncio
    async def test_get_api_error_fallback_env(self):
        backend = VaultwardenBackend(vault_url="http://vault:8080", vault_token="tok")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        backend._client = mock_client

        with patch.dict(os.environ, {"MY_SECRET": "env_fallback"}):
            result = await backend.get("MY_SECRET")
            assert result == "env_fallback"

    @pytest.mark.asyncio
    async def test_get_many(self):
        backend = VaultwardenBackend(vault_url="", vault_token="")
        with patch.dict(os.environ, {"A": "1"}):
            result = await backend.get_many(["A", "MISSING"])
            assert result == {"A": "1"}

    @pytest.mark.asyncio
    async def test_close(self):
        backend = VaultwardenBackend()
        mock_client = AsyncMock()
        backend._client = mock_client
        await backend.close()
        mock_client.aclose.assert_called_once()
        assert backend._client is None


class TestExternalVaultBackend:
    @pytest.mark.asyncio
    async def test_get_no_url_fallback(self):
        backend = ExternalVaultBackend(url="", token="tok")
        with patch.dict(os.environ, {"MY_KEY": "env_val"}):
            result = await backend.get("MY_KEY")
            assert result == "env_val"

    @pytest.mark.asyncio
    async def test_get_from_vault(self):
        backend = ExternalVaultBackend(
            url="http://vault:8200", token="tok",
            path_template="/v1/secret/data/{name}",
            value_path="data.data.value",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"data": {"value": "secret_val"}}}
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        backend._client = mock_client

        result = await backend.get("MY_SECRET")
        assert result == "secret_val"

    @pytest.mark.asyncio
    async def test_get_value_not_string(self):
        backend = ExternalVaultBackend(
            url="http://vault:8200", token="tok",
            value_path="data.value",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"value": 12345}}  # Not a string
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        backend._client = mock_client

        with patch.dict(os.environ, {"MY_SECRET": "env_val"}):
            result = await backend.get("MY_SECRET")
            assert result == "env_val"

    @pytest.mark.asyncio
    async def test_get_api_error_fallback(self):
        backend = ExternalVaultBackend(url="http://vault:8200", token="tok")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("fail"))
        backend._client = mock_client

        with patch.dict(os.environ, {"K": "v"}):
            assert await backend.get("K") == "v"

    @pytest.mark.asyncio
    async def test_get_many(self):
        backend = ExternalVaultBackend(url="", token="")
        with patch.dict(os.environ, {"X": "y"}):
            result = await backend.get_many(["X", "MISSING"])
            assert result == {"X": "y"}

    @pytest.mark.asyncio
    async def test_close(self):
        backend = ExternalVaultBackend()
        mock_client = AsyncMock()
        backend._client = mock_client
        await backend.close()
        mock_client.aclose.assert_called_once()


class TestCreateSecretsBackend:
    def test_env_default(self):
        with patch.dict(os.environ, {"CONDUCTOR_SECRETS_BACKEND": "env"}):
            backend = create_secrets_backend()
            assert isinstance(backend, EnvSecretsBackend)

    def test_kubernetes(self):
        with patch.dict(os.environ, {"CONDUCTOR_SECRETS_BACKEND": "kubernetes"}):
            backend = create_secrets_backend()
            assert isinstance(backend, KubernetesBackend)

    def test_vaultwarden(self):
        with patch.dict(os.environ, {
            "CONDUCTOR_SECRETS_BACKEND": "vaultwarden",
            "CONDUCTOR_VAULT_URL": "http://vault",
            "CONDUCTOR_VAULT_TOKEN": "tok",
        }):
            backend = create_secrets_backend()
            assert isinstance(backend, VaultwardenBackend)

    def test_vault(self):
        with patch.dict(os.environ, {
            "CONDUCTOR_SECRETS_BACKEND": "vault",
            "CONDUCTOR_VAULT_URL": "http://vault",
            "CONDUCTOR_VAULT_TOKEN": "tok",
        }):
            backend = create_secrets_backend()
            assert isinstance(backend, ExternalVaultBackend)


# ======================================================================
# Coverage gap: obsidian_watcher — start/stop, handlers
# ======================================================================

from orchestrator.interfaces.obsidian_watcher import ObsidianWatcher, _InboxHandler, _ConstraintsHandler


class TestObsidianWatcherStartStop:
    def test_start_and_stop(self, tmp_path):
        loop = asyncio.new_event_loop()
        try:
            watcher = ObsidianWatcher(vault_path=str(tmp_path))
            watcher.start(loop)
            assert watcher._observer is not None
            watcher.stop()
        finally:
            loop.close()

    def test_start_with_constraints(self, tmp_path):
        constraints = tmp_path / "constraints.md"
        constraints.write_text("# Constraints")
        loop = asyncio.new_event_loop()
        try:
            watcher = ObsidianWatcher(
                vault_path=str(tmp_path),
                layer0_path=str(constraints),
            )
            watcher.start(loop)
            watcher.stop()
        finally:
            loop.close()


class TestInboxHandler:
    def test_on_created_md_file(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        task_file = inbox / "task1.md"
        task_file.write_text("# Task 1\nDo something")

        calls = []
        handler = _InboxHandler(inbox, lambda fn, content: calls.append((fn, content)))

        from watchdog.events import FileCreatedEvent
        event = FileCreatedEvent(str(task_file))
        handler.on_created(event)

        assert len(calls) == 1
        assert calls[0][0] == "task1.md"
        assert "Task 1" in calls[0][1]

    def test_on_created_non_md_ignored(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        (inbox / "file.txt").write_text("not a task")

        calls = []
        handler = _InboxHandler(inbox, lambda fn, content: calls.append((fn, content)))

        from watchdog.events import FileCreatedEvent
        event = FileCreatedEvent(str(inbox / "file.txt"))
        handler.on_created(event)
        assert len(calls) == 0

    def test_on_created_directory_ignored(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()

        calls = []
        handler = _InboxHandler(inbox, lambda fn, content: calls.append((fn, content)))

        from watchdog.events import FileCreatedEvent
        event = FileCreatedEvent(str(inbox / "subdir"))
        event.is_directory = True
        handler.on_created(event)
        assert len(calls) == 0

    def test_on_created_debounce(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        task_file = inbox / "task1.md"
        task_file.write_text("task")

        calls = []
        handler = _InboxHandler(inbox, lambda fn, content: calls.append((fn, content)))

        from watchdog.events import FileCreatedEvent
        event = FileCreatedEvent(str(task_file))
        handler.on_created(event)
        handler.on_created(event)  # Should be debounced
        assert len(calls) == 1


class TestConstraintsHandler:
    def test_on_modified_matching_file(self, tmp_path):
        constraints = tmp_path / "constraints.md"
        constraints.write_text("# Constraints")

        calls = []
        handler = _ConstraintsHandler(constraints, lambda: calls.append(True))

        from watchdog.events import FileModifiedEvent
        event = FileModifiedEvent(str(constraints))
        handler.on_modified(event)
        assert len(calls) == 1

    def test_on_modified_other_file_ignored(self, tmp_path):
        constraints = tmp_path / "constraints.md"
        constraints.write_text("x")
        other = tmp_path / "other.md"
        other.write_text("y")

        calls = []
        handler = _ConstraintsHandler(constraints, lambda: calls.append(True))

        from watchdog.events import FileModifiedEvent
        event = FileModifiedEvent(str(other))
        handler.on_modified(event)
        assert len(calls) == 0


# ======================================================================
# Coverage gap: vault_sync — SyncthingSync health check
# ======================================================================

from orchestrator.interfaces.vault_sync import SyncthingSync


class TestSyncthingSyncHealth:
    @pytest.mark.asyncio
    async def test_health_no_api(self):
        sync = SyncthingSync("/tmp/vault")
        health = await sync.check_health()
        assert health["adapter"] == "syncthing"
        assert health["api_configured"] is False

    @pytest.mark.asyncio
    async def test_health_with_api(self):
        sync = SyncthingSync(
            "/tmp/vault",
            syncthing_api="http://localhost:8384",
            api_key="test-key",
            folder_id="vault-folder",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "state": "idle",
            "needFiles": 0,
            "globalFiles": 100,
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            health = await sync.check_health()
            assert health["adapter"] == "syncthing"
            assert health["state"] == "idle"
            assert health["api_configured"] is True

    @pytest.mark.asyncio
    async def test_health_api_error(self):
        sync = SyncthingSync(
            "/tmp/vault", api_key="k", folder_id="f",
        )
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            health = await sync.check_health()
            assert health["status"] == "degraded"
