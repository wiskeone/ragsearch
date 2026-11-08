import logging
import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from django.conf import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self):
        self._cache = {}          # model_name -> model
        self.default_model_name = getattr(settings, 'DEFAULT_EMBEDDING_MODEL', 'BAAI/bge-m3')
        self.default_dim = getattr(settings, 'EMBEDDING_DIMENSION', 1024)
        # Явно задаём устройство CPU
        self.device = getattr(settings, 'EMBEDDING_DEVICE', 'cpu')
        if self.device == 'cuda' and not torch.cuda.is_available():
            logger.warning("CUDA requested but not available, falling back to CPU")
            self.device = 'cpu'
        logger.info(f"EmbeddingService will use device: {self.device}")

    def _load_model(self, model_name):
        """Загружает модель на CPU (без квантизации) и кэширует."""
        if model_name in self._cache:
            return self._cache[model_name]

        logger.info(f"[LOAD] Loading embedding model {model_name} on {self.device}")
        try:
            model = SentenceTransformer(model_name, device=self.device)
        except Exception as e:
            logger.error(f"Failed to load {model_name} on {self.device}: {e}")
            # Fallback на CPU, если вдруг device='cuda' и ошибка
            if self.device != 'cpu':
                logger.warning(f"Falling back to CPU for {model_name}")
                model = SentenceTransformer(model_name, device='cpu')
            else:
                raise
        self._cache[model_name] = model
        logger.info(f"[LOAD] Model {model_name} loaded, device={model.device}")
        return model

    def create_embedding(self, text, model_name=None, normalize=True):
        model_name = model_name or self.default_model_name
        model = self._load_model(model_name)
        emb = model.encode(text, convert_to_numpy=True)
        if normalize:
            norm = np.linalg.norm(emb)
            if norm > 0:
                emb = emb / norm
        return emb

    def create_embeddings_batch(self, texts, model_name=None, normalize=True, batch_size=32):
        model_name = model_name or self.default_model_name
        model = self._load_model(model_name)
        logger.info(f"[EMBED] Creating {len(texts)} embeddings with batch_size={batch_size} on {model.device}")
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            show_progress_bar=False
        )
        if normalize:
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            embeddings = embeddings / norms
        return embeddings

    def clear_cache(self):
        self._cache.clear()
        import gc
        gc.collect()
        logger.info("Embedding cache cleared")


# Глобальный экземпляр (инициализируется один раз)
embedding_service = EmbeddingService()