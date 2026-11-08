from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.conf import settings
from .services.encryption import get_fernet
import os


class LLMModel(models.Model):
    """Модель LLM, загруженная из Hugging Face (только для админов)"""
    DOWNLOAD_STATUS_CHOICES = [
        ('not_started', _('Не начата')),
        ('downloading', _('Загрузка...')),
        ('completed', _('Загружена')),
        ('failed', _('Ошибка')),
    ]
    MODEL_TYPE_CHOICES = [
        ('QWEN', 'Qwen'),
        ('LLAMA', 'Llama'),
        ('MISTRAL', 'Mistral'),
        ('GEMMA', 'Gemma'),
        ('CUSTOM', 'Custom'),
    ]
    name = models.CharField(max_length=255, unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    model_id = models.CharField(max_length=500)  # Hugging Face ID
    model_type = models.CharField(max_length=20, choices=MODEL_TYPE_CHOICES, default='CUSTOM')
    parameter_count = models.BigIntegerField(default=0)
    quantization = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    downloaded = models.BooleanField(default=False)
    local_path = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    download_status = models.CharField(max_length=20, choices=DOWNLOAD_STATUS_CHOICES, default='not_started')
    download_progress = models.IntegerField(default=0)
    download_error = models.TextField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.display_name or self.name


class EmbeddingModel(models.Model):
    """Модель эмбеддингов"""
    DOWNLOAD_STATUS_CHOICES = [
        ('not_started', _('Не начата')),
        ('downloading', _('Загрузка...')),
        ('completed', _('Загружена')),
        ('failed', _('Ошибка')),
    ]
    name = models.CharField(max_length=255, unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    model_id = models.CharField(max_length=500)  # Hugging Face ID
    embedding_dim = models.IntegerField()
    max_tokens = models.IntegerField(default=512, help_text=_('Максимальное количество токенов на вход'))
    is_multilingual = models.BooleanField(default=False, help_text=_('Поддерживает ли несколько языков'))
    license_type = models.CharField(max_length=100, blank=True, help_text=_('Тип лицензии'))
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    downloaded = models.BooleanField(default=False)
    local_path = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    download_status = models.CharField(max_length=20, choices=DOWNLOAD_STATUS_CHOICES, default='not_started')
    download_progress = models.IntegerField(default=0)
    download_error = models.TextField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.display_name or self.name

        
class UserProfile(models.Model):
    ACCOUNT_STATUS_CHOICES = [
        ('trial', 'Trial'),
        ('pro', 'Pro'),
        ('expired', 'Expired'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    
    # Зашифрованные поля
    _huggingface_token = models.TextField(blank=True, db_column='huggingface_token')
    _telegram = models.CharField(max_length=100, blank=True, db_column='telegram')
    
    work_place = models.CharField(max_length=200, blank=True)
    # v3.0: роль для разграничения доступа (admin > member > viewer)
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('member', 'Member'),
        ('viewer', 'Viewer'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='member')

    account_status = models.CharField(max_length=20, choices=ACCOUNT_STATUS_CHOICES, default='trial')
    trial_expires_at = models.DateTimeField(null=True, blank=True)
    pro_expires_at = models.DateTimeField(null=True, blank=True)
    
    # Системная информация
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Заглушки для оплаты
    payment_customer_id = models.CharField(max_length=100, blank=True)
    payment_subscription_id = models.CharField(max_length=100, blank=True)

    llm_model = models.ForeignKey(LLMModel, on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    embedding_model = models.ForeignKey(EmbeddingModel, on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    
    class Meta:
        indexes = [
            models.Index(fields=['account_status']),
            models.Index(fields=['trial_expires_at']),
        ]

    @property
    def huggingface_token(self):
        if not self._huggingface_token:
            return ''
        fernet = get_fernet()
        return fernet.decrypt(self._huggingface_token.encode()).decode()

    @huggingface_token.setter
    def huggingface_token(self, value):
        if not value:
            self._huggingface_token = ''
            return
        fernet = get_fernet()
        self._huggingface_token = fernet.encrypt(value.encode()).decode()

    @property
    def telegram(self):
        if not self._telegram:
            return ''
        fernet = get_fernet()
        return fernet.decrypt(self._telegram.encode()).decode()

    @telegram.setter
    def telegram(self, value):
        if not value:
            self._telegram = ''
            return
        fernet = get_fernet()
        self._telegram = fernet.encrypt(value.encode()).decode()

    def can_upload_document(self):
        from .models import Document
        if self.account_status == 'pro':
            return True
        doc_count = Document.objects.filter(collection__owner=self.user).count()
        return doc_count < settings.TRIAL_MAX_DOCUMENTS

    def can_create_collection(self):
        from .models import Collection
        if self.account_status == 'pro':
            return True
        coll_count = Collection.objects.filter(owner=self.user).count()
        return coll_count < settings.TRIAL_MAX_COLLECTIONS

    # v3.0: ролевые хелперы
    @property
    def is_admin(self):
        return self.role == 'admin' or self.user.is_superuser

    @property
    def is_member(self):
        return self.role in ('admin', 'member')

    @property
    def can_manage_models(self):
        """Загрузка/удаление моделей — только admin."""
        return self.is_admin

    @property
    def can_delete_documents(self):
        """Удаление документов — member и admin."""
        return self.is_member

    def is_trial_active(self):
        if self.account_status != 'trial':
            return False
        if self.trial_expires_at:
            from django.utils import timezone
            return timezone.now() < self.trial_expires_at
        return True

    def is_pro_active(self):
        if self.account_status != 'pro':
            return False
        if self.pro_expires_at:
            from django.utils import timezone
            return timezone.now() < self.pro_expires_at
        return True

    def create_subscription(self, plan='pro_monthly'):
        return f"https://pay.example.com/subscribe?user={self.user.id}&plan={plan}"

    def cancel_subscription(self):
        self.payment_subscription_id = ''
        self.account_status = 'trial'
        self.save()


class Collection(models.Model):
    CHUNK_STRATEGY_CHOICES = [
        ('recursive', _('Рекурсивное разделение')),
        ('semantic', _('Семантическое разделение')),
        ('paragraph', _('По параграфам')),
        ('custom', _('Свои настройки')),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='collections')
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Новые поля для обработки документов
    chunking_strategy = models.CharField(
        max_length=20,
        choices=CHUNK_STRATEGY_CHOICES,
        default='recursive',
        help_text=_('Стратегия разделения документа на чанки')
    )
    chunk_size = models.IntegerField(
        default=1000,
        help_text=_('Размер чанка в символах')
    )
    chunk_overlap = models.IntegerField(
        default=200,
        help_text=_('Перекрытие между чанками')
    )
    auto_process = models.BooleanField(
        default=True,
        help_text=_('Автоматически обрабатывать новые документы после загрузки')
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Document(models.Model):
    STATUS_CHOICES = [
        ('uploaded', _('Загружен')),
        ('processing', _('Обработка')),
        # FIX: был 'indexed' в choices, но весь код (tasks/views) ставит и
        # фильтрует 'processed' — значения приведены к фактически используемому
        ('processed', _('Проиндексирован')),
        ('error', _('Ошибка')),
    ]

    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name='documents')
    original_filename = models.CharField(max_length=500)
    title = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    file_encrypted_path = models.CharField(max_length=1000)
    content_hash = models.CharField(max_length=64, blank=True, help_text='SHA-256 decrypted content (incremental indexing)')
    file_size_mb = models.FloatField(default=0.0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded')
    error_message = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.title or self.original_filename

    def get_decrypted_content(self):
        fernet = get_fernet()
        with open(self.file_encrypted_path, 'rb') as f:
            encrypted = f.read()
        return fernet.decrypt(encrypted)

    def save_encrypted_file(self, file_content):
        fernet = get_fernet()
        encrypted = fernet.encrypt(file_content)
        os.makedirs(os.path.dirname(self.file_encrypted_path), exist_ok=True)
        with open(self.file_encrypted_path, 'wb') as f:
            f.write(encrypted)


class DocumentChunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='chunks')
    chunk_index = models.IntegerField()
    content = models.TextField()
    token_count = models.IntegerField(default=0)
    embedding_vector = models.JSONField(null=True, blank=True)
    embedding_model = models.ForeignKey('EmbeddingModel', null=True, blank=True, on_delete=models.SET_NULL)
    has_embedding = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, help_text=_('Активен ли чанк (мягкое удаление)'))
    embedding_dim = models.IntegerField(null=True, blank=True, help_text=_('Размерность эмбеддинга'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['document', 'chunk_index']


class SearchQuery(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='searches')
    query_text = models.TextField()
    search_type = models.CharField(max_length=20, default='hybrid')
    collection = models.ForeignKey(Collection, null=True, blank=True, on_delete=models.SET_NULL)
    results_count = models.IntegerField(default=0)
    processing_time_ms = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SearchResult(models.Model):
    query = models.ForeignKey(SearchQuery, on_delete=models.CASCADE, related_name='results')
    chunk = models.ForeignKey(DocumentChunk, on_delete=models.CASCADE)
    relevance_score = models.FloatField()
    rank = models.IntegerField()


class ChatSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions')
    session_id = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=255, blank=True)
    conversation_history = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.title or f"Chat {self.id}"

class ApiKey(models.Model):
    """v3.0: API-ключ для программного доступа к /api/ (Bearer auth)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_keys')
    name = models.CharField(max_length=100, help_text="Метка ключа (для пользователя)")
    key_hash = models.CharField(max_length=64, unique=True, help_text="SHA-256 ключа (сырой ключ НЕ хранится)")
    prefix = models.CharField(max_length=12, help_text="Первые 8 символов ключа для отображения")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['key_hash']),
            models.Index(fields=['user', 'is_active']),
        ]

    def __str__(self):
        return f"{self.prefix}… ({self.user.username})"
