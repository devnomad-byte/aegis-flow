from backend.app.retrieval.eval_metrics import compute_retrieval_metrics


def test_retrieval_eval_metrics_score_expected_chunk_hits() -> None:
    metrics = compute_retrieval_metrics(
        expected_chunk_refs=["child-a", "child-c"],
        returned_chunk_refs=["child-b", "child-a", "child-d"],
        top_k=3,
    )

    assert metrics.recall_at_k == 0.5
    assert metrics.mrr == 0.5
    assert metrics.context_precision == 1 / 3
    assert metrics.context_recall == 0.5


def test_retrieval_eval_metrics_handle_empty_expected_and_empty_results() -> None:
    metrics = compute_retrieval_metrics(
        expected_chunk_refs=[],
        returned_chunk_refs=[],
        top_k=5,
    )

    assert metrics.recall_at_k == 0.0
    assert metrics.mrr == 0.0
    assert metrics.context_precision == 0.0
    assert metrics.context_recall == 0.0


def test_retrieval_eval_metrics_only_count_top_k_results() -> None:
    metrics = compute_retrieval_metrics(
        expected_chunk_refs=["child-c"],
        returned_chunk_refs=["child-a", "child-b", "child-c"],
        top_k=2,
    )

    assert metrics.recall_at_k == 0.0
    assert metrics.mrr == 0.0
    assert metrics.context_precision == 0.0
    assert metrics.context_recall == 0.0
