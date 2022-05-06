from __future__ import annotations

import time

import pytest

from coredis.exceptions import LockError, ResponseError
from coredis.lock import Lock, LuaLock
from tests.conftest import targets

pytestmark = pytest.mark.flaky


@pytest.mark.asyncio()
@targets("redis_basic", "redis_basic_resp3")
@pytest.mark.parametrize("thread_local", ((True,), (False,)))
class TestLock:
    lock_class = LuaLock

    def get_lock(self, redis, *args, **kwargs):
        kwargs["lock_class"] = self.lock_class

        return redis.lock(*args, **kwargs)

    async def test_lock(self, client, thread_local):
        lock = self.get_lock(client, "foo", thread_local=thread_local)
        assert await lock.acquire(blocking=False)
        assert await client.get("foo") == lock.local.get()
        assert await client.ttl("foo") == -1
        await lock.release()
        assert await client.get("foo") is None

    async def test_competing_locks(self, client, thread_local):
        lock1 = self.get_lock(client, "foo", thread_local=thread_local)
        lock2 = self.get_lock(client, "foo", thread_local=thread_local)
        assert await lock1.acquire(blocking=False)
        assert not await lock2.acquire(blocking=False)
        await lock1.release()
        assert await lock2.acquire(blocking=False)
        assert not await lock1.acquire(blocking=False)
        await lock2.release()

    async def test_timeout(self, client, thread_local):
        lock = self.get_lock(client, "foo", timeout=10, thread_local=thread_local)
        assert await lock.acquire(blocking=False)
        assert 8 < await client.ttl("foo") <= 10
        await lock.release()

    async def test_float_timeout(self, client, thread_local):
        lock = self.get_lock(client, "foo", timeout=9.5, thread_local=thread_local)
        assert await lock.acquire(blocking=False)
        assert 8 < await client.pttl("foo") <= 9500
        await lock.release()

    async def test_blocking_timeout(self, client, thread_local):
        lock1 = self.get_lock(client, "foo", thread_local=thread_local)
        assert await lock1.acquire(blocking=False)
        lock2 = self.get_lock(
            client, "foo", blocking_timeout=0.2, thread_local=thread_local
        )
        start = time.time()
        assert not await lock2.acquire()
        assert (time.time() - start) > 0.2
        await lock1.release()

    async def test_context_manager(self, client, thread_local):
        # blocking_timeout prevents a deadlock if the lock can't be acquired
        # for some reason
        async with self.get_lock(
            client, "foo", blocking_timeout=0.2, thread_local=thread_local
        ) as lock:
            assert await client.get("foo") == lock.local.get()
        assert await client.get("foo") is None

    async def test_high_sleep_raises_error(self, client, thread_local):
        "If sleep is higher than timeout, it should raise an error"
        with pytest.raises(LockError):
            self.get_lock(client, "foo", timeout=1, sleep=2, thread_local=thread_local)

    async def test_releasing_unlocked_lock_raises_error(self, client, thread_local):
        lock = self.get_lock(client, "foo", thread_local=thread_local)
        with pytest.raises(LockError):
            await lock.release()

    async def test_releasing_lock_no_longer_owned_raises_error(
        self, client, thread_local
    ):
        lock = self.get_lock(client, "foo", thread_local=thread_local)
        await lock.acquire(blocking=False)
        # manually change the token
        await client.set("foo", "a")
        with pytest.raises(LockError):
            await lock.release()
        # even though we errored, the token is still cleared
        assert lock.local.get() is None

    async def test_extend_lock(self, client, thread_local):
        lock = self.get_lock(client, "foo", timeout=10, thread_local=thread_local)
        assert await lock.acquire(blocking=False)
        assert 8000 < await client.pttl("foo") <= 10000
        assert await lock.extend(10)
        assert 16000 < await client.pttl("foo") <= 20000
        await lock.release()

    async def test_extend_lock_float(self, client, thread_local):
        lock = self.get_lock(client, "foo", timeout=10.0, thread_local=thread_local)
        assert await lock.acquire(blocking=False)
        assert 8000 < await client.pttl("foo") <= 10000
        assert await lock.extend(10.0)
        assert 16000 < await client.pttl("foo") <= 20000
        await lock.release()

    async def test_extending_unlocked_lock_raises_error(self, client, thread_local):
        lock = self.get_lock(client, "foo", timeout=10, thread_local=thread_local)
        with pytest.raises(LockError):
            await lock.extend(10)

    async def test_extending_lock_with_no_timeout_raises_error(
        self, client, thread_local
    ):
        lock = self.get_lock(client, "foo", thread_local=thread_local)
        await client.flushdb()
        assert await lock.acquire(blocking=False)
        with pytest.raises(LockError):
            await lock.extend(10)
        await lock.release()

    async def test_extending_lock_no_longer_owned_raises_error(
        self, client, thread_local
    ):
        lock = self.get_lock(client, "foo", thread_local=thread_local)
        await client.flushdb()
        assert await lock.acquire(blocking=False)
        await client.set("foo", "a")
        with pytest.raises(LockError):
            await lock.extend(10)


@pytest.mark.asyncio()
@targets("redis_basic")
class TestLockClassSelection:
    async def test_lock_class_argument(self, client):
        lock = client.lock("foo", lock_class=Lock)
        assert type(lock) == Lock
        lock = client.lock("foo", lock_class=LuaLock)
        assert type(lock) == LuaLock

    async def test_cached_lualock_flag(self, client):
        try:
            client._use_lua_lock = True
            lock = client.lock("foo")
            assert type(lock) == LuaLock
        finally:
            client._use_lua_lock = None

    async def test_cached_lock_flag(self, client):
        try:
            client._use_lua_lock = False
            lock = client.lock("foo")
            assert type(lock) == Lock
        finally:
            client._use_lua_lock = None

    async def test_lua_compatible_server(self, client, monkeypatch):
        @classmethod
        def mock_register(cls, redis):
            return

        monkeypatch.setattr(LuaLock, "register_scripts", mock_register)
        try:
            lock = client.lock("foo")
            assert type(lock) == LuaLock
            assert client._use_lua_lock is True
        finally:
            client._use_lua_lock = None

    async def test_lua_unavailable(self, client, monkeypatch):
        @classmethod
        def mock_register(cls, redis):
            raise ResponseError()

        monkeypatch.setattr(LuaLock, "register_scripts", mock_register)
        try:
            lock = client.lock("foo")
            assert type(lock) == Lock
            assert client._use_lua_lock is False
        finally:
            client._use_lua_lock = None
