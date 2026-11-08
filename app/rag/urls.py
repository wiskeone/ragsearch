from django.urls import path
from django.contrib.auth.views import LoginView, LogoutView
from . import views
from . import api_views

app_name = 'rag'

urlpatterns = [
    # Главная и аутентификация
    path('', views.index, name='index'),
    path('login/', LoginView.as_view(template_name='rag/login.html'), name='login'),
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),
    path('register/', views.register, name='register'),
    path('profile/', views.profile_view, name='profile'),

    # HF
    path('api/huggingface/', api_views.HuggingFaceAPI.as_view(), name='huggingface_api'),

    # v3.0: API-ключи, квоты, экспорт
    path('api/keys/generate/', api_views.api_generate_key, name='api_generate_key'),
    path('api/keys/', api_views.api_list_keys, name='api_list_keys'),
    path('api/keys/<int:key_id>/revoke/', api_views.api_revoke_key, name='api_revoke_key'),
    path('api/quota/', api_views.api_quota_status, name='api_quota_status'),
    path('api/export/search/markdown/', api_views.api_export_search_markdown, name='api_export_search_markdown'),
    path('api/search/stream/', api_views.api_search_stream, name='api_search_stream'),

    # Коллекции – единственная страница
    path('collections/', views.collection_list, name='collection_list'),

    # ===================== AJAX API для коллекций =====================
    path('api/collections/create-form/', views.collection_create_form, name='collection_create_form'),
    path('api/collections/<int:pk>/edit-form/', views.collection_edit_form, name='collection_edit_form'),
    path('api/collections/create/', views.collection_create_ajax, name='collection_create_ajax'),
    path('api/collections/<int:pk>/update/', views.collection_update_ajax, name='collection_update_ajax'),
    path('api/collections/<int:pk>/delete/', views.collection_delete_ajax, name='collection_delete_ajax'),
    path('api/collections/<int:pk>/details/', views.collection_detail_modal, name='collection_detail_modal'),
    path('api/collections/<int:pk>/reindex/', views.collection_reindex, name='collection_reindex'),
    path('api/collections/<int:pk>/documents/', views.collection_documents_modal, name='collection_documents_modal'),

    # ===================== AJAX API для документов (внутри модалок) =====================
    path('api/documents/upload-form/', views.document_upload_form, name='document_upload_form'),
    path('api/documents/upload/', views.document_upload_ajax, name='document_upload_ajax'),
    path('api/documents/<int:pk>/edit-form/', views.document_edit_form, name='document_edit_form'),
    path('api/documents/<int:pk>/update/', views.document_update_ajax, name='document_update_ajax'),
    path('api/documents/<int:pk>/delete/', views.document_delete_ajax, name='document_delete_ajax'),
    path('api/documents/<int:pk>/details/', views.document_detail_modal, name='document_detail_modal'),
    path('api/documents/<int:pk>/download/', views.document_download, name='document_download'),
    path('api/documents/<int:pk>/status/', views.ajax_document_status, name='ajax_document_status'),

    # Поиск и чат
    path('api/search/', api_views.api_search, name='api_search'),
    path('api/chat/', api_views.api_chat, name='api_chat'),
    path('api/user/rag-collections/', api_views.api_user_rag_collections, name='api_user_rag_collections'),
    path('api/chat/result/<str:task_id>/', api_views.api_chat_result, name='api_chat_result'),
    path('api/chat/session/create/', api_views.api_chat_create_session, name='api_chat_create_session'),
    path('api/chat/sessions/', api_views.api_chat_sessions_list, name='api_chat_sessions_list'),
    path('api/chat/session/<str:session_id>/history/', api_views.api_chat_session_history, name='api_chat_session_history'),
    path('api/chunks/<int:chunk_id>/', api_views.api_chunk_detail, name='api_chunk_detail'),
    path('api/chunks/batch/', api_views.api_chunks_batch, name='api_chunks_batch'),
    
    # Админские страницы для моделей
    path('admin/models/llm/', views.llm_model_list, name='llm_model_list'),
    path('admin/models/llm/upload/', views.llm_model_upload, name='llm_model_upload'),
    path('admin/models/embedding/', views.embedding_model_list, name='embedding_model_list'),
    path('admin/models/embedding/upload/', views.embedding_model_upload, name='embedding_model_upload'),

    # API эндпоинты
    path('api/search/', api_views.api_search, name='api_search'),
    path('api/chat/', api_views.api_chat, name='api_chat'),

    # API эмбеддинги
    path('api/embedding/<int:model_id>/download/', api_views.embedding_download, name='embedding_download'),
    path('api/embedding/<int:model_id>/download_status/', api_views.embedding_download_status, name='embedding_download_status'),
    path('api/embedding/<int:model_id>/set_default/', api_views.set_default_embedding, name='embedding_set_default'),
    path('api/embedding/<int:model_id>/reload/', api_views.embedding_reload, name='embedding_reload'),
    path('api/embedding/<int:model_id>/details/', api_views.embedding_details, name='embedding_details'),
    path('api/embedding/<int:model_id>/cancel_download/', api_views.embedding_cancel_download, name='embedding_cancel_download'),

    # API ЛЛМ
    path('api/llm/<int:model_id>/download/', api_views.llm_download, name='llm_download'),
    path('api/llm/<int:model_id>/download_status/', api_views.llm_download_status, name='llm_download_status'),
    path('api/llm/<int:model_id>/cancel_download/', api_views.llm_cancel_download, name='llm_cancel_download'),
    path('api/llm/<int:model_id>/set_default/', api_views.llm_set_default, name='llm_set_default'),
    path('api/llm/<int:model_id>/delete/', api_views.llm_delete, name='llm_delete'),
    path('api/llm/<int:model_id>/details/', api_views.llm_details, name='llm_details'),

    # API для админских действий с моделями (дублирует часть эндпоинтов, оставлено для совместимости)
    path('api/admin/models/llm/<int:model_id>/set_default/', api_views.set_default_llm, name='api_set_default_llm'),
    path('api/admin/models/llm/<int:model_id>/download/', api_views.download_llm, name='api_download_llm'),
    path('api/admin/models/llm/<int:model_id>/delete/', api_views.delete_llm, name='api_delete_llm'),
    path('api/admin/models/embedding/<int:model_id>/set_default/', api_views.set_default_embedding, name='api_set_default_embedding'),
    path('api/admin/models/embedding/<int:model_id>/download/', api_views.download_embedding, name='api_download_embedding'),
    path('api/admin/models/embedding/<int:model_id>/delete/', api_views.delete_embedding, name='api_delete_embedding'),
]