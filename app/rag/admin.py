from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import (
    UserProfile, Collection, Document, DocumentChunk, 
    LLMModel, EmbeddingModel, ChatSession
)

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    fields = ('account_status', 'trial_expires_at', 'pro_expires_at', 'work_place', 'payment_customer_id', 'llm_model', 'embedding_model')
    readonly_fields = ('_huggingface_token', '_telegram')

class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)

admin.site.unregister(User)
admin.site.register(User, UserAdmin)

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'account_status', 'trial_expires_at', 'pro_expires_at', 'created_at']
    list_filter = ['account_status']
    search_fields = ['user__username', 'user__email']
    raw_id_fields = ['llm_model', 'embedding_model']

@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ['name', 'owner', 'is_public', 'created_at']
    list_filter = ['is_public', 'created_at']
    search_fields = ['name', 'owner__username']

@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'collection', 'status', 'file_size_mb', 'uploaded_at']
    list_filter = ['status', 'uploaded_at']
    search_fields = ['title', 'original_filename']

@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ['id', 'document', 'chunk_index', 'token_count', 'has_embedding']
    list_filter = ['has_embedding', 'created_at']
    search_fields = ['document__title']

@admin.register(LLMModel)
class LLMModelAdmin(admin.ModelAdmin):
    list_display = ['name', 'model_id', 'model_type', 'parameter_count', 'downloaded', 'is_default']
    list_filter = ['model_type', 'downloaded', 'is_default']
    search_fields = ['name', 'model_id']
    readonly_fields = ['download_status', 'download_progress', 'download_error', 'celery_task_id']
    actions = ['mark_as_downloaded', 'mark_as_default']

    def mark_as_downloaded(self, request, queryset):
        queryset.update(downloaded=True)
    mark_as_downloaded.short_description = "Пометить как скачанные"

    def mark_as_default(self, request, queryset):
        LLMModel.objects.update(is_default=False)
        queryset.update(is_default=True)
    mark_as_default.short_description = "Сделать моделью по умолчанию"

@admin.register(EmbeddingModel)
class EmbeddingModelAdmin(admin.ModelAdmin):
    list_display = ['name', 'model_id', 'embedding_dim', 'downloaded', 'is_default']
    list_filter = ['downloaded', 'is_default', 'download_status']
    search_fields = ['name', 'model_id']
    readonly_fields = ['download_status', 'download_progress', 'download_error', 'celery_task_id']
    actions = ['mark_as_downloaded', 'mark_as_default']

    def mark_as_downloaded(self, request, queryset):
        queryset.update(downloaded=True)
    mark_as_downloaded.short_description = "Пометить как скачанные"

    def mark_as_default(self, request, queryset):
        EmbeddingModel.objects.update(is_default=False)
        queryset.update(is_default=True)
    mark_as_default.short_description = "Сделать моделью по умолчанию"

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'title', 'created_at', 'updated_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'title']