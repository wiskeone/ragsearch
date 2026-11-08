# app/rag/services/rag_service.py

import logging
from .embedding_service import embedding_service
from .faiss_service import FAISSService
from .bm25_service import BM25Service
from ..models import DocumentChunk, EmbeddingModel

logger = logging.getLogger(__name__)


class RAGService:
    def __init__(self, user_profile=None):
        self.embedding_service = embedding_service
        self.faiss = FAISSService()
        self.bm25 = BM25Service()
        self.user_profile = user_profile
        from django.conf import settings
        self.default_model_name = getattr(settings, 'DEFAULT_EMBEDDING_MODEL', 'BAAI/bge-m3')

    def hybrid_search(self, query, collection_id, top_k=5, semantic_weight=0.7, keyword_weight=0.3,
                      embedding_model_id=None):
        """
        Гибридный поиск: семантический + ключевой (BM25).
        embedding_model_id – ID модели эмбеддингов из БД (если передан).
        """
        # Определяем имя модели для embedding_service
        model_name = None
        if embedding_model_id:
            try:
                emb_model = EmbeddingModel.objects.get(id=embedding_model_id)
                model_name = emb_model.model_id
                logger.info(f"Using embedding model from DB: {model_name} (id={embedding_model_id})")
            except EmbeddingModel.DoesNotExist:
                logger.warning(f"Embedding model id={embedding_model_id} not found, using default")
                model_name = self.default_model_name
        else:
            model_name = self.default_model_name

        # Семантический поиск
        query_emb = self.embedding_service.create_embedding(
            query, model_name=model_name, normalize=True
        )
        semantic_results = self.faiss.search(collection_id, query_emb, k=top_k * 2)

        # Ключевой поиск (BM25)
        keyword_results = self.bm25.search(collection_id, query, top_k=top_k * 2)

        # Объединение
        merged = {}
        for r in semantic_results:
            merged[r['chunk_id']] = {'semantic': r['score'], 'keyword': 0.0}
        for r in keyword_results:
            if r['chunk_id'] in merged:
                merged[r['chunk_id']]['keyword'] = r['score']
            else:
                merged[r['chunk_id']] = {'semantic': 0.0, 'keyword': r['score']}

        # Нормализация
        sem_scores = [v['semantic'] for v in merged.values()]
        kw_scores = [v['keyword'] for v in merged.values()]
        max_sem = max(sem_scores) if sem_scores else 1
        max_kw = max(kw_scores) if kw_scores else 1
        final = []
        for chunk_id, scores in merged.items():
            sem_norm = scores['semantic'] / max_sem if max_sem > 0 else 0
            kw_norm = scores['keyword'] / max_kw if max_kw > 0 else 0
            score = semantic_weight * sem_norm + keyword_weight * kw_norm
            final.append({'chunk_id': chunk_id, 'score': score})
        final.sort(key=lambda x: x['score'], reverse=True)
        return final[:top_k]

    def get_chunks_details(self, results):
        """results — выдача hybrid_search: [{'chunk_id', 'score', ...}, ...].

        FIX: раньше принимал список id и возвращал чанки в произвольном
        порядке БД (filter id__in не сохраняет порядок), а вызывающий код
        приписывал chunks[i]['score'] = results[i]['score'] — скоры
        попадали на чужие чанки. Теперь порядок входа сохраняется, скоры
        берутся из results."""
        scores = {r['chunk_id']: r.get('score', 0) for r in results}
        chunks = DocumentChunk.objects.filter(id__in=scores).select_related('document')
        by_id = {c.id: {
            'chunk_id': c.id,
            'document_id': c.document.id,
            'document_title': c.document.title,
            'content': c.content,
            'score': scores[c.id],
        } for c in chunks}
        return [by_id[cid] for cid in scores if cid in by_id]

    def clear_collection_index(self, collection_id):
        import os
        from django.conf import settings
        faiss_path = os.path.join(settings.FAISS_INDEX_PATH, f"coll_{collection_id}.faiss")
        meta_path = os.path.join(settings.FAISS_INDEX_PATH, f"coll_{collection_id}.meta")
        if os.path.exists(faiss_path):
            os.remove(faiss_path)
        if os.path.exists(meta_path):
            os.remove(meta_path)
        self.bm25.clear_cache(collection_id)

    def rebuild_collection_index(self, collection_id):
        from ..models import DocumentChunk
        chunks = DocumentChunk.objects.filter(
            document__collection_id=collection_id,
            has_embedding=True
        ).order_by('id')
        if chunks.exists():
            self.faiss.add_document(collection_id, chunks)
        else:
            self.clear_collection_index(collection_id)