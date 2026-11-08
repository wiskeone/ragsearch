from django_prometheus.models import model_metrics
from .models import Collection, Document, LLMModel, EmbeddingModel

# Регистрируем метрики для основных моделей
model_metrics.register(Collection, document=True)
model_metrics.register(Document, document=True)
model_metrics.register(LLMModel, document=True)
model_metrics.register(EmbeddingModel, document=True)