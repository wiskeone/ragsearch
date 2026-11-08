"""
v3.x: реранкер — cross-encoder переранжирование FAISS/BM25 кандидатов.

Опциональный этап после hybrid_search: cross-encoder модель (например,
BAAI/bge-reranker-v2-m3) скорит пары (query, chunk) и пересортировывает.

Активация: settings.RERANKER_MODEL = 'BAAI/bge-reranker-v2-m3'
Деактивация: None или пустая строка (дефолт) — реранкер выключен.

Загрузка модели ленивая — только при первом вызове.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_model = None
_tokenizer = None


def _get_model():
    """Ленивая загрузка cross-encoder модели."""
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    model_name = getattr(settings, 'RERANKER_MODEL', '')
    if not model_name:
        return None, None

    try:
        from sentence_transformers import CrossEncoder
        _model = CrossEncoder(model_name)
        logger.info(f"Reranker model loaded: {model_name}")
    except Exception as e:
        logger.error(f"Failed to load reranker model: {e}")
        return None, None
    return _model, _tokenizer


def rerank(query: str, results: list, top_k: int = None) -> list:
    """
    Переранжирует результаты поиска cross-encoder-ом.

    results — [{'chunk_id', 'content', 'score', ...}, ...]
    Возвращает тот же список, отсортированный по релевантности.
    score обновляется на cross-encoder score.
    """
    model_name = getattr(settings, 'RERANKER_MODEL', '')
    if not model_name or not results:
        return results

    model, _ = _get_model()
    if model is None:
        return results

    try:
        pairs = [(query, r.get('content', '')) for r in results]
        scores = model.predict(pairs)
        for i, r in enumerate(results):
            r['score'] = float(scores[i])
            r['reranked'] = True
        results.sort(key=lambda x: x['score'], reverse=True)
        if top_k:
            results = results[:top_k]
        return results
    except Exception as e:
        logger.error(f"Rerank error: {e}")
        return results
