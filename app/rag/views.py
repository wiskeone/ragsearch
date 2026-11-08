# views.py
import os
import uuid
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib import messages
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST, require_http_methods
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.template.loader import render_to_string

from .models import (
    Collection, Document, DocumentChunk, ChatSession,
    LLMModel, EmbeddingModel, UserProfile, SearchQuery
)
from .forms import (
    RegistrationForm, UserProfileForm, CollectionForm, DocumentUploadForm,
    LLMModelUploadForm, EmbeddingModelUploadForm, DocumentEditForm, ALLOWED_EXTENSIONS
)
from .services.encryption import get_fernet
from .services.rag_service import RAGService
from .services.chat_service import ChatService
from .tasks import (
    process_document_task, download_llm_model_task, download_embedding_model_task, 
    create_embeddings_for_collection_task, 
)
# ALLOWED_EXTENSIONS импортируется из forms (локальная копия удалена — расходилась)

# ============================================================================
# Регистрация и профиль
# ============================================================================

def register(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('rag:index')
    else:
        form = RegistrationForm()
    return render(request, 'rag/register.html', {'form': form})


@login_required
def profile_view(request):
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=request.user.profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Профиль обновлён.')
            return redirect('rag:profile')
    else:
        form = UserProfileForm(instance=request.user.profile)
    llm_models = LLMModel.objects.filter(is_active=True, downloaded=True)
    embedding_models = EmbeddingModel.objects.filter(is_active=True, downloaded=True)
    return render(request, 'rag/profile.html', {
        'form': form,
        'llm_models': llm_models,
        'embedding_models': embedding_models
    })


def index(request):
    context = {}
    if request.user.is_authenticated:
        collections = Collection.objects.filter(owner=request.user).order_by('-created_at')
        llm_models = LLMModel.objects.filter(is_active=True, downloaded=True).order_by('display_name')
        embedding_models = EmbeddingModel.objects.filter(is_active=True, downloaded=True).order_by('display_name')
        sessions = ChatSession.objects.filter(user=request.user).order_by('-updated_at')[:10]

        # Общее количество документов во всех коллекциях пользователя (статус processed или любой)
        total_documents = Document.objects.filter(collection__owner=request.user).count()
        # или только успешно обработанные:
        # total_documents = Document.objects.filter(collection__owner=request.user, status='processed').count()

        context.update({
            'collections': collections,
            'llm_models': llm_models,
            'embedding_models': embedding_models,
            'chat_sessions': sessions,
            'total_documents': total_documents,
        })
    return render(request, 'rag/index.html', context)


# ============================================================================
# Коллекции – отображение списка
# ============================================================================

@login_required
def collection_list(request):
    collections = Collection.objects.filter(owner=request.user).order_by('-created_at')
    paginator = Paginator(collections, 10)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'rag/collection_list.html', {'collections': page})


# ============================================================================
# AJAX API для коллекций (модальные формы)
# ============================================================================

def collection_create_form(request):
    """Возвращает HTML формы создания коллекции для модального окна."""
    form = CollectionForm()
    html = render_to_string('rag/collection_form_modal.html', {'form': form, 'edit_mode': False}, request=request)
    return JsonResponse({'html': html})


def collection_edit_form(request, pk):
    """Возвращает HTML формы редактирования коллекции."""
    collection = get_object_or_404(Collection, pk=pk, owner=request.user)
    form = CollectionForm(instance=collection)
    html = render_to_string('rag/collection_form_modal.html', {'form': form, 'edit_mode': True}, request=request)
    return JsonResponse({'html': html})


@require_POST
def collection_create_ajax(request):
    form = CollectionForm(request.POST)
    if form.is_valid():
        if not request.user.profile.can_create_collection():
            return JsonResponse({'success': False, 'error': 'Достигнут лимит коллекций'})
        collection = form.save(commit=False)
        collection.owner = request.user
        collection.save()
        return JsonResponse({
            'success': True,
            'message': f'Коллекция "{collection.name}" создана',
            'collection_id': collection.id          # ← добавить
        })
    return JsonResponse({'success': False, 'errors': form.errors, 'error': 'Проверьте правильность заполнения'})


@require_POST
def collection_update_ajax(request, pk):
    collection = get_object_or_404(Collection, pk=pk, owner=request.user)
    form = CollectionForm(request.POST, instance=collection)
    if form.is_valid():
        form.save()
        return JsonResponse({'success': True, 'message': f'Коллекция "{collection.name}" обновлена'})
    return JsonResponse({'success': False, 'errors': form.errors, 'error': 'Проверьте правильность заполнения'})


@require_http_methods(["DELETE"])
def collection_delete_ajax(request, pk):
    collection = get_object_or_404(Collection, pk=pk, owner=request.user)
    name = collection.name
    collection.delete()
    return JsonResponse({'success': True, 'message': f'Коллекция "{name}" удалена'})


def collection_detail_modal(request, pk):
    """Возвращает HTML с деталями коллекции для модального окна."""
    collection = get_object_or_404(Collection, pk=pk, owner=request.user)
    docs = collection.documents.all()
    total_docs = docs.count()
    processed_docs = docs.filter(status='processed').count()
    processing_docs = docs.filter(status='processing').count()
    error_docs = docs.filter(status='error').count()
    context = {
        'collection': collection,
        'total_docs': total_docs,
        'processed_docs': processed_docs,
        'processing_docs': processing_docs,
        'error_docs': error_docs,
    }
    html = render_to_string('rag/collection_detail_modal.html', context, request=request)
    return HttpResponse(html)


@require_POST
def collection_reindex(request, pk):
    collection = get_object_or_404(Collection, pk=pk, owner=request.user)
    if not collection.documents.exists():
        return JsonResponse({'success': False, 'error': 'Нет документов для индексации'})
    # Запускаем задачу, которая создаст эмбеддинги (если нужно) и построит индекс
    task = create_embeddings_for_collection_task.delay(collection.id)
    return JsonResponse({
        'success': True,
        'message': f'Запущено создание эмбеддингов и перестроение индекса. ID задачи: {task.id}'
    })


def collection_documents_modal(request, pk):
    """Возвращает HTML со списком документов коллекции для модального окна."""
    collection = get_object_or_404(Collection, pk=pk, owner=request.user)
    documents = collection.documents.all().order_by('-uploaded_at')
    html = render_to_string('rag/collection_documents_modal.html', {
        'collection': collection,
        'documents': documents,
    }, request=request)
    return HttpResponse(html)


# ============================================================================
# Документы – AJAX API (загрузка, редактирование, удаление, просмотр)
# ============================================================================

def document_upload_form(request):
    """Возвращает HTML формы загрузки документов для модального окна."""
    collection_id = request.GET.get('collection_id')
    initial = {}
    if collection_id:
        try:
            collection = Collection.objects.get(id=collection_id, owner=request.user)
            initial['collection'] = collection
        except Collection.DoesNotExist:
            pass
    form = DocumentUploadForm(user=request.user, initial=initial)
    html = render_to_string('rag/document_upload_modal.html', {'form': form}, request=request)
    return JsonResponse({'html': html})


@require_POST
def document_upload_ajax(request):
    """Прямая загрузка файлов без использования DocumentUploadForm."""
    collection_id = request.POST.get('collection')
    if not collection_id:
        return JsonResponse({'success': False, 'error': 'Не указана коллекция'}, status=400)

    try:
        collection = Collection.objects.get(id=collection_id, owner=request.user)
    except Collection.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Коллекция не найдена'}, status=404)

    if not request.user.profile.can_upload_document():
        return JsonResponse({'success': False, 'error': 'Достигнут лимит документов'}, status=400)

    uploaded_files = request.FILES.getlist('files')
    if not uploaded_files:
        return JsonResponse({'success': False, 'error': 'Файлы не переданы'}, status=400)

    uploaded = []
    for f in uploaded_files:
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return JsonResponse({'success': False, 'error': f'Недопустимый формат: {ext}'}, status=400)

        fernet = get_fernet()
        encrypted = fernet.encrypt(f.read())
        filename = f"{uuid.uuid4().hex}_{f.name}"
        file_path = os.path.join(settings.MEDIA_ROOT, 'documents', filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'wb') as out:
            out.write(encrypted)

        doc = Document.objects.create(
            collection=collection,
            original_filename=f.name,
            title=f.name,
            description='',
            tags=[],
            file_encrypted_path=file_path,
            file_size_mb=f.size / (1024 * 1024),
            status='uploaded'
        )
        process_document_task.delay(doc.id)
        uploaded.append(doc.title)

    return JsonResponse({
        'success': True,
        'message': f'Загружено {len(uploaded)} документов. Обработка запущена.'
    })


def document_edit_form(request, pk):
    """Возвращает HTML формы редактирования метаданных документа."""
    doc = get_object_or_404(Document, pk=pk, collection__owner=request.user)
    form = DocumentEditForm(instance=doc)
    html = render_to_string('rag/document_edit_modal.html', {'form': form, 'document': doc}, request=request)
    return JsonResponse({'html': html})


@require_POST
def document_update_ajax(request, pk):
    doc = get_object_or_404(Document, pk=pk, collection__owner=request.user)
    form = DocumentEditForm(request.POST, instance=doc)
    if form.is_valid():
        form.save()
        return JsonResponse({'success': True, 'message': f'Документ "{doc.title}" обновлён'})
    return JsonResponse({'success': False, 'errors': form.errors, 'error': 'Ошибка валидации'})


@require_http_methods(["DELETE"])
def document_delete_ajax(request, pk):
    doc = get_object_or_404(Document, pk=pk, collection__owner=request.user)
    if os.path.exists(doc.file_encrypted_path):
        os.remove(doc.file_encrypted_path)
    title = doc.title
    doc.delete()
    return JsonResponse({'success': True, 'message': f'Документ "{title}" удалён'})


def document_detail_modal(request, pk):
    """Возвращает HTML с деталями документа (включая список чанков)."""
    doc = get_object_or_404(Document, pk=pk, collection__owner=request.user)
    chunks = doc.chunks.all().order_by('chunk_index')
    html = render_to_string('rag/document_detail_modal.html', {'document': doc, 'chunks': chunks}, request=request)
    return HttpResponse(html)


@login_required
def document_download(request, pk):
    """Скачивание оригинального файла (расшифровка)."""
    doc = get_object_or_404(Document, pk=pk, collection__owner=request.user)
    fernet = get_fernet()
    with open(doc.file_encrypted_path, 'rb') as f:
        encrypted = f.read()
    decrypted = fernet.decrypt(encrypted)
    response = HttpResponse(decrypted, content_type='application/octet-stream')
    response['Content-Disposition'] = f'attachment; filename="{doc.original_filename}"'
    return response


# ============================================================================
# Поиск (RAG)
# ============================================================================

@login_required
def search_view(request):
    if request.method == 'POST':
        query = request.POST.get('query', '').strip()
        collection_id = request.POST.get('collection_id')
        if not query or not collection_id:
            messages.error(request, 'Введите запрос и выберите коллекцию.')
            return redirect('rag:search')
        try:
            collection = Collection.objects.get(pk=collection_id, owner=request.user)
        except Collection.DoesNotExist:
            messages.error(request, 'Коллекция не найдена.')
            return redirect('rag:search')
        rag = RAGService()
        results = rag.hybrid_search(query, collection_id, top_k=10)
        chunks = rag.get_chunks_details(results)
        return render(request, 'rag/search_results.html', {
            'query': query,
            'collection': collection,
            'results': chunks
        })
    collections = Collection.objects.filter(owner=request.user)
    return render(request, 'rag/search.html', {'collections': collections})

# ============================================================================
# Админские представления для LLM и эмбеддингов
# ============================================================================

@staff_member_required
def llm_model_list(request):
    models = LLMModel.objects.all()
    return render(request, 'rag/admin/llm_model_list.html', {'models': models})


@staff_member_required
def llm_model_upload(request):
    if request.method == 'POST':
        form = LLMModelUploadForm(request.POST)
        if form.is_valid():
            model = form.save()
            if request.POST.get('download_now'):
                download_llm_model_task.delay(model.id)
            messages.success(request, f'Модель "{model.name}" добавлена.')
            return redirect('rag:llm_model_list')
    else:
        form = LLMModelUploadForm()
    return render(request, 'rag/admin/llm_model_form.html', {'form': form})


@staff_member_required
def embedding_model_list(request):
    models = EmbeddingModel.objects.all()
    return render(request, 'rag/admin/embedding_model_list.html', {'models': models})


@staff_member_required
def embedding_model_upload(request):
    if request.method == 'POST':
        form = EmbeddingModelUploadForm(request.POST)
        if form.is_valid():
            model = form.save()
            if request.POST.get('download_now'):
                download_embedding_model_task.delay(model.id)
            messages.success(request, f'Модель "{model.name}" добавлена.')
            return redirect('rag:embedding_model_list')
    else:
        form = EmbeddingModelUploadForm()
    return render(request, 'rag/admin/embedding_model_form.html', {'form': form})

@login_required
def ajax_document_status(request, pk):
    """Возвращает статус обработки документа для AJAX"""
    try:
        doc = Document.objects.get(pk=pk)
        # Проверка доступа: владелец коллекции или is_public? (упрощённо)
        if doc.collection and doc.collection.owner != request.user and not doc.collection.is_public:
            return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    except Document.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Document not found'}, status=404)
    
    # Считаем чанки документа
    total_chunks = doc.chunks.count()
    processed_chunks = doc.chunks.filter(has_embedding=True).count()
    
    # Определяем статус
    status = doc.status  # 'uploaded', 'processing', 'processed', 'error'
    if status == 'uploaded':
        status_display = 'Загружен'
        progress = 0
    elif status == 'processing':
        status_display = 'Обработка'
        # Прогресс может быть известен из поля processing_progress (если есть)
        progress = getattr(doc, 'processing_progress', 0)
        if progress == 0 and total_chunks > 0:
            # Альтернативный расчёт
            progress = int((processed_chunks / total_chunks) * 100) if total_chunks else 0
    elif status == 'processed':
        status_display = 'Готов'
        progress = 100
    elif status == 'error':
        status_display = 'Ошибка'
        progress = 0
    else:
        status_display = status
        progress = 0
    
    return JsonResponse({
        'success': True,
        'status': status,
        'status_display': status_display,
        'progress': progress,
        'total_chunks': total_chunks,
        'processed_chunks': processed_chunks,
        'processing_progress': getattr(doc, 'processing_progress', 0),
        'error_message': doc.error_message if status == 'error' else '',
    })