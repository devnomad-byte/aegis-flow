from backend.app.retrieval.schemas import RetrievalEvalMetrics


def compute_retrieval_metrics(
    *,
    expected_chunk_refs: list[str],
    returned_chunk_refs: list[str],
    top_k: int,
) -> RetrievalEvalMetrics:
    limited_results = returned_chunk_refs[:top_k]
    expected = set(expected_chunk_refs)
    if not expected:
        return RetrievalEvalMetrics()

    hit_refs = [chunk_ref for chunk_ref in limited_results if chunk_ref in expected]
    first_hit_rank = next(
        (
            index
            for index, chunk_ref in enumerate(limited_results, start=1)
            if chunk_ref in expected
        ),
        None,
    )
    returned_count = len(limited_results)
    return RetrievalEvalMetrics(
        recall_at_k=len(set(hit_refs)) / len(expected),
        mrr=0.0 if first_hit_rank is None else 1.0 / first_hit_rank,
        context_precision=0.0 if returned_count == 0 else len(hit_refs) / returned_count,
        context_recall=len(set(hit_refs)) / len(expected),
    )
