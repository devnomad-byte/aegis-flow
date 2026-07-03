from ipaddress import ip_address
from uuid import uuid4

import pytest
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
from backend.app.security.egress_policy import EgressPolicy
from backend.app.tool_registry.schemas import (
    EnvironmentCreateRequest,
    McpServerCreateRequest,
)
from backend.app.tool_registry.sqlalchemy_store import SqlAlchemyToolRegistryStore
from backend.app.tool_registry.store import ToolRegistryEgressPolicyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_sqlalchemy_tool_registry_environment_allowlist_controls_mcp_targets() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid4()
    actor_id = uuid4()
    policy = EgressPolicy(resolver=lambda _host, _port: [ip_address("93.184.216.34")])
    async with session_factory() as session:
        session.add(Account(id=actor_id, email="egress@example.com", display_name="Egress"))
        session.add(Project(id=project_id, slug="egress", name="Egress"))
        await session.commit()

        store = SqlAlchemyToolRegistryStore(session)
        environment = await store.create_environment(
            project_id=project_id,
            actor_id=actor_id,
            request=EnvironmentCreateRequest(
                key="prod",
                name="Production",
                egress_allowed_hosts=["mcp.example.com"],
            ),
        )

        with pytest.raises(ToolRegistryEgressPolicyError):
            await store.create_mcp_server(
                project_id=project_id,
                actor_id=actor_id,
                request=McpServerCreateRequest(
                    server_ref="other",
                    name="Other",
                    base_url="https://other.example.com/mcp",
                    environment_key="prod",
                ),
                egress_policy=policy,
            )

        server = await store.create_mcp_server(
            project_id=project_id,
            actor_id=actor_id,
            request=McpServerCreateRequest(
                server_ref="mcp",
                name="MCP",
                base_url="https://mcp.example.com/mcp",
                environment_key="prod",
            ),
            egress_policy=policy,
        )

    await engine.dispose()

    assert environment.egress_allowed_hosts == ["mcp.example.com"]
    assert server.server_ref == "mcp"


@pytest.mark.asyncio
async def test_sqlalchemy_tool_registry_environment_persists_egress_proxy_controls() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid4()
    actor_id = uuid4()
    async with session_factory() as session:
        session.add(Account(id=actor_id, email="proxy@example.com", display_name="Proxy"))
        session.add(Project(id=project_id, slug="proxy", name="Proxy"))
        await session.commit()

        store = SqlAlchemyToolRegistryStore(session)
        environment = await store.create_environment(
            project_id=project_id,
            actor_id=actor_id,
            request=EnvironmentCreateRequest(
                key="prod",
                name="Production",
                egress_allowed_hosts=["api.example.com"],
                egress_allowed_ports=[443, 8443],
                egress_proxy_mode="http_proxy",
                egress_proxy_url="http://egress-proxy.internal:8080",
                egress_dns_pinning_required=True,
            ),
        )

    await engine.dispose()

    assert environment.egress_allowed_ports == [443, 8443]
    assert environment.egress_proxy_mode == "http_proxy"
    assert environment.egress_proxy_url == "http://egress-proxy.internal:8080"
    assert environment.egress_proxy_network == ""
    assert environment.egress_dns_pinning_required is True
