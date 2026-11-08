import logging
from rank_bm25 import BM25Okapi
from ..models import DocumentChunk

logger = logging.getLogger(__name__)

class BM25Service:
    def __init__(self):
        self._cache = {}  # collection_id -> (bm25, chunk_ids)

    def _tokenize(self, text):
        return text.lower().split()

    def get_index(self, collection_id):
        if collection_id in self._cache:
            return self._cache[collection_id]
        # строим индекс по всем чанкам коллекции (без фильтра is_active)
        chunks = DocumentChunk.objects.filter(
            document__collection_id=collection_id
        ).values_list('id', 'content')
        if not chunks:
            return None
        chunk_ids = [c[0] for c in chunks]
        texts = [c[1] for c in chunks]
        tokenized = [self._tokenize(t) for t in texts]
        bm25 = BM25Okapi(tokenized)
        self._cache[collection_id] = (bm25, chunk_ids)
        return self._cache[collection_id]

    def search(self, collection_id, query, top_k=10):
        data = self.get_index(collection_id)
        if not data:
            return []
        bm25, chunk_ids = data
        tokenized_query = self._tokenize(query)
        scores = bm25.get_scores(tokenized_query)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append({'chunk_id': chunk_ids[idx], 'score': float(scores[idx])})
        return results

    def clear_cache(self, collection_id=None):
        if collection_id:
            self._cache.pop(collection_id, None)
        else:
            self._cache.clear()