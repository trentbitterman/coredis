#!/usr/bin/python
# -*- coding: utf-8 -*-
import asyncio
from unittest.mock import Mock

import pytest
from packaging import version

import coredis

_REDIS_VERSIONS = {}


async def get_version(**kwargs):
    params = {"host": "localhost", "port": 6379, "db": 0}
    params.update(kwargs)
    key = "%s:%s" % (params["host"], params["port"])

    if key not in _REDIS_VERSIONS:
        client = coredis.StrictRedis(**params)
        _REDIS_VERSIONS[key] = (await client.info())["redis_version"]
        client.connection_pool.disconnect()

    return _REDIS_VERSIONS[key]


def skip_if_server_version_lt(min_version):
    loop = asyncio.get_event_loop()
    cur = version.parse(loop.run_until_complete(get_version()))
    check = cur < version.parse(min_version)

    return pytest.mark.skipif(check, reason="")


@pytest.fixture()
async def r(event_loop):
    client = coredis.StrictRedis(loop=event_loop)

    await client.config_set("maxmemory-policy", "noeviction")
    await client.flushdb()
    return client


class AsyncMock(Mock):
    def __init__(self, *args, **kwargs):
        super(AsyncMock, self).__init__(*args, **kwargs)

    def __await__(self):
        future = asyncio.Future(loop=self.loop)
        future.set_result(self)
        result = yield from future

        return result

    @staticmethod
    def pack_response(response, *, loop):
        future = asyncio.Future(loop=loop)
        future.set_result(response)

        return future


def _gen_mock_resp(r, response, *, loop):
    mock_connection_pool = AsyncMock(loop=loop)
    connection = AsyncMock(loop=loop)
    connection.read_response.return_value = AsyncMock.pack_response(response, loop=loop)
    mock_connection_pool.get_connection.return_value = connection
    r.connection_pool = mock_connection_pool

    return r


@pytest.fixture()
def mock_resp_role(event_loop):
    r = coredis.StrictRedis(loop=event_loop)
    response = [b"master", 169, [[b"172.17.0.2", b"7004", b"169"]]]

    return _gen_mock_resp(r, response, loop=event_loop)
