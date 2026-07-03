from backend.app.knowledge.ingestion import (
    ChunkPipelineConfig,
    KnowledgeIngestionPipeline,
    normalize_document_text,
)


def test_normalize_document_text_keeps_meaningful_spacing() -> None:
    raw_text = "  # Runbook\r\n\r\n\r\nStep 1  \r\n\tcheck service\r\n\r\n\r\n\r\nStep 2\r\n"

    assert normalize_document_text(raw_text) == "# Runbook\n\nStep 1\n    check service\n\nStep 2"


def test_markdown_pipeline_preserves_heading_metadata_and_parent_child_links() -> None:
    pipeline = KnowledgeIngestionPipeline(
        ChunkPipelineConfig(
            parent_target_tokens=120,
            child_target_tokens=34,
            child_overlap_tokens=8,
        )
    )
    document = """
# 运维排障手册

## 服务 502

当服务返回 502 时，先检查 ingress、upstream pod、最近发布和依赖健康状态。

### 诊断步骤

第一步查看最近发布记录。第二步查询 pod 日志。第三步检查服务发现和 readiness probe。
如果发现生产写入类操作，必须进入人工审批。

## 回滚策略

只允许在审批通过后执行回滚模板。回滚前记录 run_id、审批人和变更窗口。
"""

    result = pipeline.build_chunks(document, content_format="markdown")

    parent_chunks = [chunk for chunk in result.chunks if chunk.kind == "parent"]
    child_chunks = [chunk for chunk in result.chunks if chunk.kind == "child"]

    assert result.content_hash
    assert parent_chunks
    assert child_chunks
    assert child_chunks[0].parent_ref == parent_chunks[0].chunk_ref
    assert child_chunks[0].chunk_ref.startswith("child-0001-")
    assert "运维排障手册" in child_chunks[0].metadata["heading_path"]
    assert any("服务 502" in chunk.metadata["heading_path"] for chunk in child_chunks)
    assert all(chunk.token_count <= 42 for chunk in child_chunks)
    assert all(chunk.content_hash for chunk in result.chunks)


def test_plain_text_pipeline_is_deterministic() -> None:
    pipeline = KnowledgeIngestionPipeline(
        ChunkPipelineConfig(parent_target_tokens=40, child_target_tokens=18, child_overlap_tokens=4)
    )
    text = "检查告警。确认项目。查询日志。生成结论。记录 run lesson。" * 8

    first = pipeline.build_chunks(text, content_format="text")
    second = pipeline.build_chunks(text, content_format="text")

    assert first.content_hash == second.content_hash
    assert [chunk.chunk_ref for chunk in first.chunks] == [
        chunk.chunk_ref for chunk in second.chunks
    ]
    assert [chunk.content_hash for chunk in first.chunks] == [
        chunk.content_hash for chunk in second.chunks
    ]
