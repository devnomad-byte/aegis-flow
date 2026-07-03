from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from backend.app.audit.schemas import AuditEventRead
from backend.app.audit.sqlalchemy_store import SqlAlchemyAuditEventStore
from backend.app.audit.store import AuditEventFilters
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_audit_sqlalchemy_store_records_and_filters_project_events() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Account(
                    id=actor_id,
                    email="actor@example.com",
                    display_name="Actor",
                    status="active",
                ),
                Project(id=project_id, slug="ops", name="Ops", status="active"),
                Project(id=other_project_id, slug="data", name="Data", status="active"),
            ]
        )
        await session.commit()
        store = SqlAlchemyAuditEventStore(session)
        await store.record_project_event(
            project_id=project_id,
            actor_id=actor_id,
            action="tool_gateway.invoke",
            target_type="tool_gateway_invocation",
            target_id="call-1",
            result="failure",
            risk_level="high",
            metadata={"trace_id": "trace-1"},
        )
        await store.record_project_event(
            project_id=other_project_id,
            actor_id=actor_id,
            action="tool_gateway.invoke",
            target_type="tool_gateway_invocation",
            target_id="call-2",
            result="failure",
            risk_level="high",
            metadata={"trace_id": "trace-2"},
        )

        events = await store.list_project_events(
            project_id=project_id,
            filters=AuditEventFilters(
                actor_id=actor_id,
                action="tool_gateway.invoke",
                risk_level="high",
                result="failure",
                target_type="tool_gateway_invocation",
                created_from=datetime.now(UTC) - timedelta(minutes=1),
                created_to=datetime.now(UTC) + timedelta(minutes=1),
                limit=10,
            ),
        )

    await engine.dispose()

    assert len(events) == 1
    assert isinstance(events[0], AuditEventRead)
    assert events[0].project_id == project_id
    assert events[0].metadata == {"trace_id": "trace-1"}


@pytest.mark.asyncio
async def test_audit_sqlalchemy_store_records_global_events_without_project_scope() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    actor_id = uuid4()
    async with session_factory() as session:
        session.add(
            Account(
                id=actor_id,
                email="super@example.com",
                display_name="Super",
                status="active",
                is_super_admin=True,
            )
        )
        await session.commit()
        store = SqlAlchemyAuditEventStore(session)
        await store.record_global_event(
            actor_id=actor_id,
            action="global.audit.events.list",
            target_type="audit_logs",
            target_id="global",
            result="success",
            risk_level="medium",
            metadata={"event_count": 0},
        )
        events = await store.list_global_events(
            filters=AuditEventFilters(action="global.audit.events.list", limit=10)
        )

    await engine.dispose()

    assert len(events) == 1
    assert events[0].project_id is None
    assert events[0].metadata == {"event_count": 0}
