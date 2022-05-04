from __future__ import annotations

import asyncio

import pytest

from tests.conftest import targets


@targets("redis_cluster", "redis_cluster_resp3")
@pytest.mark.asyncio()
class TestCluster:
    async def test_cluster_info(self, client, _s):
        info = await client.cluster_info()
        assert info["cluster_state"] == _s("ok")

        info = await list(client.replicas)[0].cluster_info()
        assert info["cluster_state"] == _s("ok")

        info = await list(client.primaries)[0].cluster_info()
        assert info["cluster_state"] == _s("ok")

    async def test_cluster_keyslot(self, client, _s):
        slot = await client.cluster_keyslot("a")
        assert slot is not None
        await client.set("a", "1")
        assert await client.cluster_countkeysinslot(slot) == 1
        assert await client.cluster_getkeysinslot(slot, 1) == (_s("a"),)

    async def test_cluster_nodes(self, client, _s):
        nodes = await client.cluster_nodes()
        assert len(nodes) == 6
        replicas = await client.cluster_replicas(
            [n["id"] for n in nodes if "master" in n["flags"]].pop()
        )
        assert len(replicas) == 1

    @pytest.mark.min_server_version("7.0.0")
    async def test_cluster_links(self, client, _s):
        links = []
        for node in client.primaries:
            links.append(await node.cluster_links())
        for node in client.replicas:
            links.append(await node.cluster_links())
        assert len(links) == 6

    @pytest.mark.min_server_version("7.0.0")
    async def test_cluster_my_id(self, client, _s):
        ids = []
        for node in client.primaries:
            ids.append(node.cluster_myid())
        for node in client.replicas:
            ids.append(node.cluster_myid())
        ids = await asyncio.gather(*ids)
        known_nodes = (
            node["node_id"] for node in client.connection_pool.nodes.all_nodes()
        )
        assert set(ids) == set(known_nodes)

    @pytest.mark.min_server_version("7.0.0")
    async def test_cluster_shards(self, client, _s):
        await client
        known_nodes = {
            node["node_id"] for node in client.connection_pool.nodes.all_nodes()
        }
        shards = await client.cluster_shards()

        nodes = []
        [nodes.extend(shard[_s("nodes")]) for shard in shards]
        assert known_nodes == {node[_s("id")] for node in nodes}
