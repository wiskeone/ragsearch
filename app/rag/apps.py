from django.apps import AppConfig

class RagConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'rag'
    verbose_name = 'RAG Search'

    def ready(self):
        # Импорт сигналов
        try:
            import rag.signals
        except ImportError:
            pass
        # Импорт метрик для регистрации
        try:
            import rag.metrics
        except ImportError:
            pass