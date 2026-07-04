from uuid import uuid4

import pytest
from backend.app.core.settings import AppSettings
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
from backend.app.knowledge.models import RetrievalEvalDataset, RetrievalEvalRun
from backend.app.model_gateway.openai_compatible import OpenAICompatibleModelGatewayClient
from backend.app.model_gateway.runner import LlmNodeRunner, LlmNodeRunRequest
from backend.app.model_gateway.schemas import (
    ModelGatewayPolicyCreate,
    PromptTemplateCreate,
    PromptTemplateVersionCreate,
)
from backend.app.model_gateway.sqlalchemy_store import SqlAlchemyModelGatewayStore
from backend.app.workflows.dsl import (
    EdgeDefinition,
    LlmNodeData,
    NodeDefinition,
    WorkflowDefinition,
    WorkflowMetadata,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_ai_provider,
]


def require_real_provider_settings() -> AppSettings:
    settings = AppSettings()
    if not settings.model_gateway.openai_compatible.has_auth_token:
        pytest.skip("OpenAI-compatible auth token is not configured")

    return settings


@pytest.mark.asyncio
async def test_llm_node_runner_uses_real_provider_and_records_usage_ledger() -> None:
    settings = require_real_provider_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        actor_id = uuid4()
        session.add(Account(id=actor_id, email="real-llm@example.com", display_name="Real LLM"))
        session.add(Project(id=project_id, slug="real-llm", name="Real LLM"))
        await session.commit()

        store = SqlAlchemyModelGatewayStore(session)
        await store.upsert_policy(
            ModelGatewayPolicyCreate(
                project_id=project_id,
                policy_ref="default",
                provider=settings.model_gateway.default_provider,
                model_name=settings.model_gateway.default_model,
                prompt_version="final-acceptance/v1",
                temperature=0,
                max_tokens=24,
                max_total_tokens_per_call=512,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        prompt_template = await store.create_prompt_template(
            PromptTemplateCreate(
                project_id=project_id,
                template_ref="final-acceptance-json",
                name="Final Acceptance JSON",
                description="Real provider JSON output validation prompt.",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await store.create_prompt_template_version(
            PromptTemplateVersionCreate(
                project_id=project_id,
                template_id=prompt_template.id,
                version="v1",
                system_prompt=(
                    "You are a strict integration-test assistant. "
                    "Return only minified JSON matching the requested schema."
                ),
                user_prompt='Return exactly this JSON object: {"result":"aegisflow-llm-node-ok"}',
                variables=[],
                output_schema={
                    "type": "object",
                    "required": ["result"],
                    "properties": {"result": {"const": "aegisflow-llm-node-ok"}},
                    "additionalProperties": False,
                },
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        eval_dataset = RetrievalEvalDataset(
            project_id=project_id,
            key="final-acceptance-prompt-release",
            name="Final Acceptance Prompt Release",
            description="Gate prompt label release for real provider final acceptance.",
            evaluation_scope="prompt_release",
            status="active",
            created_by=actor_id,
            updated_by=actor_id,
        )
        session.add(eval_dataset)
        await session.flush()
        eval_run = RetrievalEvalRun(
            project_id=project_id,
            dataset_id=eval_dataset.id,
            actor_id=actor_id,
            status="completed",
            retrieval_mode="hybrid",
            top_k=5,
            candidate_limit=50,
            case_count=1,
            average_recall_at_k=1.0,
            average_mrr=1.0,
            average_context_precision=1.0,
            average_context_recall=1.0,
            average_faithfulness=1.0,
            leakage_count=0,
            deleted_visible_count=0,
            report={"dataset_key": eval_dataset.key},
            created_by=actor_id,
            updated_by=actor_id,
        )
        session.add(eval_run)
        await session.commit()
        await store.publish_prompt_template_release(
            project_id=project_id,
            template_ref="final-acceptance-json",
            version="v1",
            label="latest",
            environment="preprod",
            eval_run_id=eval_run.id,
            release_note="Final acceptance label release",
            actor_id=actor_id,
        )
        workflow = WorkflowDefinition(
            workflow=WorkflowMetadata(
                id="real_llm_node",
                name="Real LLM Node",
                project_id=str(project_id),
                version=1,
            ),
            nodes=[
                NodeDefinition(id="start_1", name="Start", type="start"),
                NodeDefinition(
                    id="llm_1",
                    name="Real provider node",
                    type="llm",
                    data=LlmNodeData(
                        model_policy_ref="default",
                        prompt_template_ref="final-acceptance-json",
                        prompt_label="latest",
                        prompt_environment="preprod",
                        prompt_version="v1",
                        max_tokens=24,
                        output_schema_ref="final-acceptance-json-output",
                    ),
                ),
                NodeDefinition(id="end_1", name="End", type="end"),
            ],
            edges=[
                EdgeDefinition(source="start_1", target="llm_1"),
                EdgeDefinition(source="llm_1", target="end_1"),
            ],
        )
        runner = LlmNodeRunner(
            policy_store=store,
            invocation_store=store,
            model_client=OpenAICompatibleModelGatewayClient(
                settings.model_gateway.openai_compatible,
            ),
            prompt_store=store,
        )

        result = await runner.run(
            LlmNodeRunRequest(
                project_id=project_id,
                actor_id=actor_id,
                workflow=workflow,
                node_id="llm_1",
                run_id="run-real-llm",
                trace_id="trace-real-llm",
                inputs={},
            )
        )
        invocations = await store.list_invocations_for_run(
            project_id=project_id,
            run_id="run-real-llm",
        )
        filtered_invocations = await store.list_invocations(
            project_id=project_id,
            run_id="run-real-llm",
            node_id="llm_1",
            trace_id="trace-real-llm",
        )

    await engine.dispose()

    assert "aegisflow-llm-node-ok" in result.content.lower()
    assert result.provider == "openai-compatible"
    assert invocations[0].status == "success"
    assert invocations[0].node_id == "llm_1"
    assert invocations[0].trace_id == "trace-real-llm"
    assert invocations[0].prompt_version == "v1"
    assert invocations[0].output_schema_ref == "final-acceptance-json-output"
    assert invocations[0].schema_validation_status == "passed"
    assert invocations[0].request_hash.startswith("sha256:")
    assert filtered_invocations == invocations
