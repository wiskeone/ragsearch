import os
import pickle
import logging
import numpy as np
import faiss
from django.conf import settings

logger = logging.getLogger(__name__)


class FAISSService:
    def __init__(self):
        self.index_dir = settings.FAISS_INDEX_PATH
        os.makedirs(self.index_dir, exist_ok=True)
        self.index = None
        self.chunk_ids = []
        self.dimension = None

    def _get_index_path(self, collection_id):
        return os.path.join(self.index_dir, f"coll_{collection_id}.faiss")

    def _get_metadata_path(self, collection_id):
        return os.path.join(self.index_dir, f"coll_{collection_id}.meta")

    def load_index(self, collection_id):
        """Загружает индекс с диска."""
        index_path = self._get_index_path(collection_id)
        meta_path = self._get_metadata_path(collection_id)
        if not os.path.exists(index_path) or not os.path.exists(meta_path):
            logger.warning(f"Index files for collection {collection_id} not found")
            return False
        try:
            self.index = faiss.read_index(index_path)
            with open(meta_path, 'rb') as f:
                meta = pickle.load(f)
            self.chunk_ids = meta['chunk_ids']
            self.dimension = meta.get('dimension', self.index.d)
            logger.info(f"Loaded index for collection {collection_id}: {self.index.ntotal} vectors")
            return True
        except Exception as e:
            logger.error(f"Failed to load index for {collection_id}: {e}")
            return False

    def delete_index(self, collection_id):
        """Удаляет файлы индекса."""
        index_path = self._get_index_path(collection_id)
        meta_path = self._get_metadata_path(collection_id)
        for path in [index_path, meta_path]:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Deleted {path}")

    def add_document(self, collection_id, chunks):
        """Полностью перестраивает индекс для коллекции на основе всех её чанков."""
        from ..models import DocumentChunk
        all_chunks = DocumentChunk.objects.filter(
            document__collection_id=collection_id,
            has_embedding=True,
            is_active=True
        ).exclude(embedding_vector__isnull=True).order_by('id')
        if not all_chunks:
            logger.warning(f"No chunks with embeddings for collection {collection_id}")
            return 0
        vectors = np.array([c.embedding_vector for c in all_chunks], dtype='float32')
        chunk_ids = [c.id for c in all_chunks]
        dim = vectors.shape[1]

        # Создаём новый индекс
        self.index = faiss.IndexFlatIP(dim)  # косинусное сходство через inner product
        self.index.add(vectors)
        self.chunk_ids = chunk_ids
        self.dimension = dim

        # Сохраняем на диск
        faiss.write_index(self.index, self._get_index_path(collection_id))
        with open(self._get_metadata_path(collection_id), 'wb') as f:
            pickle.dump({'chunk_ids': chunk_ids, 'dim': dim}, f)
        logger.info(f"Built index for collection {collection_id}: {self.index.ntotal} vectors")
        return len(vectors)

    def search(self, collection_id, query_vector, k=10):
        """Поиск k ближайших соседей. Автоматически загружает индекс, если он не загружен."""
        # Загружаем индекс, если он ещё не загружен
        if self.index is None:
            if not self.load_index(collection_id):
                return []
        if self.index.ntotal == 0:
            return []
        query = np.array(query_vector, dtype='float32').reshape(1, -1)
        scores, indices = self.index.search(query, min(k, self.index.ntotal))
        results = []
        for i, idx in enumerate(indices[0]):
            if idx != -1 and idx < len(self.chunk_ids):
                results.append({'chunk_id': self.chunk_ids[idx], 'score': float(scores[0][i])})
        return results