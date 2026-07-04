from uuid import UUID, uuid4

import pytest
from backend.app.db.base import Base
from backend.app.workflows.publish_gate import evaluate_workflow_publish_gate
from backend.app.workflows.sqlalchemy_store import (
    SqlAlchemyWorkflowDraftStore,
    SqlAlchemyWorkflowVersionStore,
)
from backend.app.workflows.store import WorkflowVersionConflict
from backend.app.workflows.yaml_io import ProjectResourceCatalog, import_workflow_yaml
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_workflow_version_store_publishes_lists_restores_archives_by_scope() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        draft_store = SqlAlchemyWorkflowDraftStore(session)
        version_store = SqlAlchemyWorkflowVersionStore(session)
        project_id = uuid4()
        other_project_id = uuid4()
        actor_id = uuid4()
        imported = import_workflow_yaml(
            workflow_yaml(project_id),
            catalog=complete_catalog(),
        )
        gate_result = evaluate_workflow_publish_gate(imported.workflow, imported.analysis)
        draft = await draft_store.upsert_project_draft(
            project_id=project_id,
            actor_id=actor_id,
            workflow=imported.workflow,
            analysis=imported.analysis,
        )

        version = await version_store.publish_project_version(
            project_id=project_id,
            actor_id=actor_id,
            draft=draft,
            analysis=imported.analysis,
            gate_result=gate_result,
            release_note="publish test",
        )
        versions = await version_store.list_project_versions(project_id=project_id)
        hidden = await version_store.get_project_version(other_project_id, version.id)
        restored = await version_store.restore_version_as_draft(
            project_id=project_id,
            version_id=version.id,
            actor_id=actor_id,
            draft_store=draft_store,
        )
        archived = await version_store.archive_project_version(
            project_id=project_id,
            version_id=version.id,
            actor_id=actor_id,
        )

    await engine.dispose()

    assert version.status == "published"
    assert version.definition.workflow.status == "published"
    assert version.definition_hash.startswith("sha256:")
    assert versions == [version]
    assert hidden is None
    assert restored is not None
    assert restored.version == 2
    assert restored.definition.workflow.status == "draft"
    assert archived is not None
    assert archived.status == "archived"
    assert archived.archived_by == actor_id
    assert archived.archived_at is not None


@pytest.mark.asyncio
async def test_workflow_version_store_rejects_duplicate_immutable_version() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        draft_store = SqlAlchemyWorkflowDraftStore(session)
        version_store = SqlAlchemyWorkflowVersionStore(session)
        project_id = uuid4()
        actor_id = uuid4()
        imported = import_workflow_yaml(workflow_yaml(project_id), catalog=complete_catalog())
        gate_result = evaluate_workflow_publish_gate(imported.workflow, imported.analysis)
        draft = await draft_store.upsert_project_draft(
            project_id=project_id,
            actor_id=actor_id,
            workflow=imported.workflow,
            analysis=imported.analysis,
        )
        await version_store.publish_project_version(
            project_id=project_id,
            actor_id=actor_id,
            draft=draft,
            analysis=imported.analysis,
            gate_result=gate_result,
            release_note="first publish",
        )

        with pytest.raises(WorkflowVersionConflict):
            await version_store.publish_project_version(
                project_id=project_id,
                actor_id=actor_id,
                draft=draft,
                analysis=imported.analysis,
                gate_result=gate_result,
                release_note="duplicate publish",
            )

    await engine.dispose()


def complete_catalog() -> ProjectResourceCatalog:
    return ProjectResourceCatalog(
        tool_groups=frozenset({"k8s.readonly"}),
        mcp_servers=frozenset({"mcp-k8s-test"}),
        shell_templates=frozenset(),
        environments=frozenset({"test"}),
    )


def workflow_yaml(project_id: UUID) -> str:
    return f"""
schema_version: workflow.dsl/v0.1
workflow:
  id: ops_502_diagnosis
  name: 502 排障助手
  project_id: "{project_id}"
  version: 1
  status: draft
nodes:
  - id: start_1
    name: 开始
    type: start
  - id: tool_1
    name: 查询 Pod 状态
    type: mcp_tool
    risk_level: medium
    data:
      mcp_server_ref: mcp-k8s-test
      tool_group_ref: k8s.readonly
      tool_name: k8s.get_pod
      environment: test
  - id: end_1
    name: 结束
    type: end
edges:
  - source: start_1
    target: tool_1
  - source: tool_1
    target: end_1
policies:
  default_environment: test
  max_runtime_seconds: 900
  max_tool_calls: 20
"""
