import os
import logging
import re
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required, method_decorator
from django.contrib.auth import login
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from huggingface_hub import HfApi
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404
from celery.result import AsyncResult
from django.utils import timezone

from .services.rag_service import RAGService

from .tasks import download_llm_model_task, download_embedding_model_task


from .models import Collection, LLMModel, EmbeddingModel, ChatSession, DocumentChunk

logger = logging.getLogger(__name__)

# ============================================================================
# API для поиска и чата (существующие)
# ============================================================================


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_search(request):
    query = request.data.get('query', '').strip()
    collection_id = request.data.get('collection_id')
    if not query or not collection_id:
        return Response({'error': 'query and collection_id required'}, status=400)
    try:
        collection = Collection.objects.get(id=collection_id, owner=request.user)
    except Collection.DoesNotExist:
        return Response({'error': 'Collection not found'}, status=404)
    rag = RAGService()
    results = rag.hybrid_search(query, collection_id, top_k=10)
    chunks = rag.get_chunks_details(results)
    return Response({'results': chunks})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_chat(request):
    query = request.data.get('query', '').strip()
    collection_id = request.data.get('collection_id')
    llm_model_id = request.data.get('llm_model_id')
    embedding_model_id = request.data.get('embedding_model_id')
    temperature = float(request.data.get('temperature', 0.7))
    max_tokens = int(request.data.get('max_tokens', 512))
    session_id = request.data.get('session_id')

    if not query or not collection_id:
        return Response({'error': 'query and collection_id required'}, status=400)

    try:
        collection = Collection.objects.get(id=collection_id, owner=request.user)
    except Collection.DoesNotExist:
        return Response({'error': 'Collection not found'}, status=404)

    # Сохраняем сообщение пользователя, если указана сессия
    if session_id:
        try:
            session = ChatSession.objects.get(session_id=session_id, user=request.user)
            history = session.conversation_history or []
            history.append({
                'role': 'user',
                'content': query,
                'timestamp': timezone.now().isoformat()
            })
            session.conversation_history = history
            session.save(update_fields=['conversation_history', 'updated_at'])
        except ChatSession.DoesNotExist:
            pass

    rag = RAGService()
    results = rag.hybrid_search(query, collection_id, top_k=5, embedding_model_id=embedding_model_id)
    chunks = rag.get_chunks_details(results)

    if not chunks:
        return Response({'answer': 'По вашему запросу ничего не найдено.', 'sources': []})

    # ================= РЕЖИМ БЕЗ LLM (ПОИСК) =================
    if not llm_model_id:
        # Подсветка искомых слов
        query_words = [w for w in query.lower().split() if len(w) >= 3]
        highlighted_chunks = []
        for ch in chunks:
            content = ch['content']
            # Заменяем каждое слово на <mark>слово</mark> (без учёта регистра)
            for word in query_words:
                pattern = re.compile(re.escape(word), re.IGNORECASE)
                content = pattern.sub(lambda m: f'<mark>{m.group(0)}</mark>', content)
            highlighted_chunks.append({
                'chunk_id': ch['chunk_id'],
                'document_id': ch['document_id'],
                'document_title': ch['document_title'],
                'content_highlighted': content,
                'original_content': ch['content']
            })
        return Response({
            'is_search_result': True,
            'sources': highlighted_chunks
        })

    # ================= РЕЖИМ С LLM =================
    from .tasks import generate_text_task
    context = "\n\n".join([f"Документ: {c['document_title']}\n{c['content'][:500]}" for c in chunks])
    prompt = f"Ты полезный ассистент. Отвечай на вопрос, используя только предоставленный контекст.\n\nКонтекст:\n{context}\n\nВопрос: {query}\n\nОтвет:"

    task = generate_text_task.delay(
        model_id=llm_model_id,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        session_id=session_id,
        use_rag=False,
        rag_config=None
    )

    request.session['chat_sources'] = chunks
    return Response({'success': True, 'task_id': task.id, 'async': True, 'session_id': session_id})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_chat_result(request, task_id):
    from celery.result import AsyncResult
    from .models import ChatSession
    from django.utils import timezone

    task = AsyncResult(task_id)
    if task.ready():
        result = task.result
        if isinstance(result, Exception):
            error_msg = str(result)
            logger.error(f"Task {task_id} failed: {error_msg}")
            return Response({'success': False, 'error': error_msg, 'ready': True}, status=500)
        if isinstance(result, dict) and result.get('success'):
            sources = request.session.get('chat_sources', [])
            answer = result.get('response', '')
            session_id = result.get('session_id')
            if session_id:
                try:
                    session = ChatSession.objects.get(session_id=session_id, user=request.user)
                    history = session.conversation_history or []
                    history.append({
                        'role': 'assistant',
                        'content': answer,
                        'timestamp': timezone.now().isoformat(),
                        'metadata': {'sources': sources}
                    })
                    session.conversation_history = history
                    session.save(update_fields=['conversation_history', 'updated_at'])
                except ChatSession.DoesNotExist:
                    pass
            return Response({'success': True, 'answer': answer, 'sources': sources, 'ready': True})
        else:
            return Response({'success': False, 'error': result.get('error', 'Unknown error'), 'ready': True}, status=500)
    else:
        return Response({'success': False, 'status': task.state, 'ready': False})

@login_required
def api_user_rag_collections(request):
    collections = Collection.objects.filter(owner=request.user).order_by('-created_at')
    data = []
    for c in collections:
        data.append({
            'id': c.id,
            'name': c.name,
            'description': c.description,
            'doc_count': c.documents.count(),   # предполагаем, что документы не удаляются физически
            'is_public': c.is_public,
        })
    return JsonResponse({'success': True, 'collections': data})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_chunk_detail(request, chunk_id):
    """Возвращает содержимое одного чанка для просмотра в модалке."""
    try:
        chunk = DocumentChunk.objects.select_related('document').get(id=chunk_id, is_active=True)
        # Проверка доступа
        if chunk.document.collection:
            if chunk.document.collection.owner != request.user and not chunk.document.collection.is_public:
                return Response({'error': 'Access denied'}, status=403)
        return Response({
            'success': True,
            'chunk_id': chunk.id,
            'document_id': chunk.document.id,
            'document_title': chunk.document.title,
            'content': chunk.content,
            'chunk_index': chunk.chunk_index,
        })
    except DocumentChunk.DoesNotExist:
        return Response({'error': 'Chunk not found'}, status=404)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_chunks_batch(request):
    """Возвращает несколько чанков по списку ID (GET параметр ids=1,2,3)."""
    ids_str = request.GET.get('ids', '')
    if not ids_str:
        return Response({'error': 'ids parameter required'}, status=400)
    try:
        chunk_ids = [int(id.strip()) for id in ids_str.split(',') if id.strip().isdigit()]
    except ValueError:
        return Response({'error': 'Invalid ids'}, status=400)
    chunks = DocumentChunk.objects.filter(id__in=chunk_ids, is_active=True).select_related('document')
    data = []
    for ch in chunks:
        data.append({
            'chunk_id': ch.id,
            'document_id': ch.document.id,
            'document_title': ch.document.title,
            'content': ch.content,
            'chunk_index': ch.chunk_index,
        })
    return Response({'success': True, 'chunks': data})

# ============================================================================
# API для управления сессиями чата (простая версия, без chat_service)
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_chat_create_session(request):
    """Создаёт новую сессию чата для пользователя."""
    from .models import ChatSession
    import uuid
    session_id = str(uuid.uuid4())
    session = ChatSession.objects.create(
        user=request.user,
        session_id=session_id,
        title=f"Чат {session_id[:8]}",
        conversation_history=[]
    )
    return Response({
        'success': True,
        'session_id': session.session_id,
        'id': session.id,
        'title': session.title,
        'created_at': session.created_at.isoformat()
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_chat_sessions_list(request):
    """Возвращает список всех сессий пользователя."""
    from .models import ChatSession
    sessions = ChatSession.objects.filter(
        user=request.user
    ).order_by('-updated_at')

    data = []
    for s in sessions:
        # Получаем последнее сообщение из истории
        history = s.conversation_history or []
        last_msg = history[-1].get('content', '')[:100] if history else ''
        data.append({
            'id': s.id,
            'session_id': s.session_id,
            'title': s.title or f"Чат {s.created_at.strftime('%d.%m.%Y')}",
            'created_at': s.created_at.isoformat(),
            'last_activity': s.updated_at.isoformat(),
            'total_messages': len(history),
            'last_message': last_msg,
        })
    return Response({'success': True, 'sessions': data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_chat_session_history(request, session_id):
    """Возвращает историю сообщений указанной сессии."""
    from .models import ChatSession
    try:
        session = ChatSession.objects.get(session_id=session_id, user=request.user)
    except ChatSession.DoesNotExist:
        return Response({'error': 'Session not found'}, status=404)

    history = session.conversation_history or []
    return Response({'success': True, 'history': history})

# ============================================================================
# API для Hugging Face Hub
# ============================================================================

class HuggingFaceAPI(View):
    """
    API для взаимодействия с Hugging Face Hub:
    - поиск моделей (LLM и эмбеддингов)
    - топ-модели
    - валидация модели по ID

    FIX: прокси к HF Hub был доступен анонимно — теперь только
    аутентифицированным пользователям.
    """

    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.api = HfApi()
    
    def get(self, request):
        action = request.GET.get('action')
        
        if action == 'search':
            return self.search_models(request)
        elif action == 'top_models':
            return self.get_top_models(request)
        elif action == 'model_info':
            return self.get_model_info(request)
        elif action == 'validate':
            return self.validate_model(request)
        elif action == 'search_embedding':
            return self.search_embedding_models(request)
        elif action == 'top_embedding_models':
            return self.get_top_embedding_models(request)
        elif action == 'validate_embedding':
            return self.validate_embedding_model(request)
        else:
            return JsonResponse({'error': 'Unknown action'}, status=400)
    
    # ========== LLM модели ==========
    
    def search_models(self, request):
        query = request.GET.get('q', '')
        model_type = request.GET.get('type', '')
        limit = int(request.GET.get('limit', 10))
        
        filter_tags = None
        if model_type == 'QWEN':
            filter_tags = 'qwen,text-generation'
        elif model_type == 'LLAMA':
            filter_tags = 'llama,text-generation'
        elif model_type == 'MISTRAL':
            filter_tags = 'mistral,text-generation'
        elif model_type == 'GEMMA':
            filter_tags = 'gemma,text-generation'
        elif model_type == 'DEEPSEEK':
            filter_tags = 'text-generation'
        elif model_type == 'PHI':
            filter_tags = 'text-generation'
        elif model_type == 'YI':
            filter_tags = 'text-generation'
        
        try:
            models = self.api.list_models(
                search=query or None,
                filter=filter_tags,
                sort="downloads",
                limit=limit,
                full=True
            )
            results = []
            for m in models:
                results.append({
                    'id': m.id,
                    'name': m.id.split('/')[-1],
                    'author': m.id.split('/')[0],
                    'downloads': m.downloads,
                    'likes': m.likes,
                    'tags': m.tags[:5] if m.tags else [],
                    'pipeline_tag': m.pipeline_tag,
                })
            return JsonResponse({'results': results, 'total': len(results)})
        except Exception as e:
            logger.error(f"Search error: {e}")
            return JsonResponse({'error': str(e), 'results': []}, status=500)
    
    def get_top_models(self, request):
        model_type = request.GET.get('type', 'ALL')
        limit = int(request.GET.get('limit', 5))
        
        type_config = {
            'QWEN': {'search': 'qwen', 'filter': 'qwen,text-generation'},
            'LLAMA': {'search': 'llama', 'filter': 'llama,text-generation'},
            'MISTRAL': {'search': 'mistral', 'filter': 'mistral,text-generation'},
            'GEMMA': {'search': 'gemma', 'filter': 'gemma,text-generation'},
            'DEEPSEEK': {'search': 'deepseek', 'filter': 'text-generation'},
            'PHI': {'search': 'phi-3', 'filter': 'text-generation'},
            'YI': {'search': 'yi-1.5', 'filter': 'text-generation'},
            'ALL': {'search': '', 'filter': 'text-generation'},
        }
        cfg = type_config.get(model_type, type_config['ALL'])
        
        try:
            models = self.api.list_models(
                search=cfg['search'],
                filter=cfg['filter'],
                sort="downloads",
                limit=limit
            )
            results = []
            for m in models:
                results.append({
                    'id': m.id,
                    'name': m.id.split('/')[-1],
                    'full_name': m.id,
                    'author': m.id.split('/')[0],
                    'downloads': m.downloads,
                    'likes': m.likes,
                })
            return JsonResponse({'type': model_type, 'models': results})
        except Exception as e:
            logger.error(f"Top models error: {e}")
            return JsonResponse({'error': str(e), 'models': []}, status=500)
    
    def get_model_info(self, request):
        model_id = request.GET.get('model_id', '')
        if not model_id:
            return JsonResponse({'error': 'model_id required'}, status=400)
        try:
            info = self.api.model_info(model_id)
            return JsonResponse({
                'id': info.id,
                'author': info.author,
                'downloads': info.downloads,
                'likes': info.likes,
                'tags': info.tags[:10] if info.tags else [],
                'pipeline_tag': info.pipeline_tag,
                'private': info.private,
                'gated': info.gated,
            })
        except Exception as e:
            return JsonResponse({'error': str(e), 'model_id': model_id}, status=404)
    
    def validate_model(self, request):
        model_id = request.GET.get('model_id', '')
        if not model_id:
            return JsonResponse({'error': 'model_id required'}, status=400)
        try:
            info = self.api.model_info(model_id, timeout=10)
            # Пытаемся получить конфиг
            import requests
            context_length = 4096
            parameter_count = 0
            try:
                config_url = f"https://huggingface.co/{model_id}/raw/main/config.json"
                resp = requests.get(config_url, timeout=5)
                if resp.status_code == 200:
                    config = resp.json()
                    context_length = config.get('max_position_embeddings', 4096)
                    parameter_count = config.get('num_parameters', 0)
            except Exception:
                pass
            # Если параметров нет, пробуем извлечь из имени
            if parameter_count == 0:
                import re
                match = re.search(r'(\d+\.?\d*)[bB]', model_id)
                if match:
                    parameter_count = int(float(match.group(1)) * 1_000_000_000)
            return JsonResponse({
                'valid': True,
                'exists': True,
                'model_id': info.id,
                'author': info.author,
                'downloads': info.downloads,
                'private': info.private,
                'gated': info.gated,
                'context_length': context_length,
                'parameter_count': parameter_count,
            })
        except Exception as e:
            return JsonResponse({'valid': False, 'exists': False, 'error': str(e)}, status=404)
    
    # ========== Модели эмбеддингов ==========
    
    def search_embedding_models(self, request):
        query = request.GET.get('q', '')
        limit = int(request.GET.get('limit', 10))
        try:
            models = self.api.list_models(
                search=query or None,
                filter="sentence-transformers,feature-extraction",
                sort="downloads",
                limit=limit
            )
            results = []
            for m in models:
                dim = None
                if m.tags:
                    for tag in m.tags:
                        if tag.startswith('dim'):
                            dim = tag.replace('dim', '')
                            break
                results.append({
                    'id': m.id,
                    'name': m.id.split('/')[-1],
                    'author': m.id.split('/')[0],
                    'downloads': m.downloads,
                    'likes': m.likes,
                    'tags': m.tags[:10] if m.tags else [],
                    'dimension': dim,
                })
            return JsonResponse({'results': results, 'total': len(results)})
        except Exception as e:
            return JsonResponse({'error': str(e), 'results': []}, status=500)
    
    def get_top_embedding_models(self, request):
        limit = int(request.GET.get('limit', 5))
        try:
            models = self.api.list_models(
                filter="sentence-transformers,feature-extraction",
                sort="downloads",
                limit=limit
            )
            results = []
            for m in models:
                dim = None
                if m.tags:
                    for tag in m.tags:
                        if tag.startswith('dim'):
                            dim = tag.replace('dim', '')
                            break
                results.append({
                    'id': m.id,
                    'name': m.id.split('/')[-1],
                    'author': m.id.split('/')[0],
                    'downloads': m.downloads,
                    'likes': m.likes,
                    'dimension': dim,
                })
            return JsonResponse({'models': results})
        except Exception as e:
            return JsonResponse({'error': str(e), 'models': []}, status=500)
    
    def validate_embedding_model(self, request):
        model_id = request.GET.get('model_id', '')
        if not model_id:
            return JsonResponse({'error': 'model_id required'}, status=400)
        try:
            info = self.api.model_info(model_id, timeout=10)
            if info.pipeline_tag not in ['feature-extraction', 'sentence-similarity']:
                return JsonResponse({'valid': False, 'exists': True, 'error': 'Not an embedding model'})
            dim = None
            if info.tags:
                for tag in info.tags:
                    if tag.startswith('dim'):
                        dim = tag.replace('dim', '')
                        break
            return JsonResponse({
                'valid': True,
                'exists': True,
                'id': info.id,
                'author': info.author,
                'downloads': info.downloads,
                'likes': info.likes,
                'tags': info.tags[:10],
                'dimension': dim,
                'license': info.cardData.get('license', 'unknown') if hasattr(info, 'cardData') else '',
            })
        except Exception as e:
            return JsonResponse({'valid': False, 'exists': False, 'error': str(e)}, status=404)

@staff_member_required
def embedding_download(request, model_id):
    try:
        model = EmbeddingModel.objects.get(id=model_id)
        if model.download_status == 'downloading':
            return JsonResponse({'success': False, 'error': 'Already downloading'})
        task = download_embedding_model_task.delay(model.id)
        model.download_status = 'downloading'
        model.download_progress = 0
        model.download_error = ''
        model.save()
        return JsonResponse({'success': True, 'task_id': task.id})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def embedding_download_status(request, model_id):
    try:
        model = EmbeddingModel.objects.get(id=model_id)
        return JsonResponse({
            'status': model.download_status,
            'progress': model.download_progress,
            'error': model.download_error
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=404)

@staff_member_required
def embedding_cancel_download(request, model_id):
    try:
        model = EmbeddingModel.objects.get(id=model_id)
        if model.download_status == 'downloading' and model.celery_task_id:
            AsyncResult(model.celery_task_id).revoke(terminate=True)
        model.download_status = 'not_started'
        model.download_progress = 0
        model.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

        
@staff_member_required
def set_default_llm(request, model_id):
    try:
        LLMModel.objects.update(is_default=False)
        model = LLMModel.objects.get(id=model_id)
        model.is_default = True
        model.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def set_default_embedding(request, model_id):
    try:
        EmbeddingModel.objects.update(is_default=False)
        model = EmbeddingModel.objects.get(id=model_id)
        model.is_default = True
        model.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def embedding_reload(request, model_id):
    """Перекачать модель (сбросить статус и запустить загрузку заново)"""
    try:
        model = EmbeddingModel.objects.get(id=model_id)
        # Отменяем предыдущую задачу, если есть
        if model.celery_task_id:
            from celery.result import AsyncResult
            AsyncResult(model.celery_task_id).revoke(terminate=True)
        # Сбрасываем статус
        model.download_status = 'not_started'
        model.download_progress = 0
        model.downloaded = False
        model.download_error = ''
        model.save()
        # Запускаем новую загрузку
        from .tasks import download_embedding_model_task
        task = download_embedding_model_task.delay(model.id)
        model.celery_task_id = task.id
        model.download_status = 'downloading'
        model.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def embedding_details(request, model_id):
    try:
        model = EmbeddingModel.objects.get(id=model_id)
        return JsonResponse({
            'id': model.id,
            'name': model.name,
            'display_name': model.display_name,
            'model_id': model.model_id,
            'embedding_dim': model.embedding_dim,
            'max_tokens': model.max_tokens,
            'is_multilingual': model.is_multilingual,
            'license_type': model.license_type,
            'is_default': model.is_default,
            'is_active': model.is_active,
            'downloaded': model.downloaded,
            'download_status': model.download_status,
            'download_progress': model.download_progress,
            'download_error': model.download_error,
            'local_path': model.local_path,
            'created_at': model.created_at.isoformat() if model.created_at else None,
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=404)

@staff_member_required
def download_llm(request, model_id):
    try:
        model = LLMModel.objects.get(id=model_id)
        if model.downloaded:
            return JsonResponse({'success': False, 'error': 'Already downloaded'})
        download_llm_model_task.delay(model.id)
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def download_embedding(request, model_id):
    try:
        model = EmbeddingModel.objects.get(id=model_id)
        if model.downloaded:
            return JsonResponse({'success': False, 'error': 'Already downloaded'})
        download_embedding_model_task.delay(model.id)
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def llm_details(request, model_id):
    try:
        model = LLMModel.objects.get(id=model_id)
        return JsonResponse({
            'name': model.name,
            'display_name': model.display_name,
            'model_id': model.model_id,
            'model_type_display': model.get_model_type_display(),
            'parameter_count': model.parameter_count,
            'quantization': model.quantization,
            'download_status_display': model.get_download_status_display(),
            'local_path': model.local_path,
            'is_default': model.is_default,
            'is_active': model.is_active,
            'created_at': model.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'download_error': model.download_error
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=404)

@staff_member_required
def delete_llm(request, model_id):
    try:
        LLMModel.objects.get(id=model_id).delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def delete_embedding(request, model_id):
    try:
        EmbeddingModel.objects.get(id=model_id).delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def llm_download(request, model_id):
    try:
        model = LLMModel.objects.get(id=model_id)
        if model.download_status == 'downloading':
            return JsonResponse({'success': False, 'error': 'Already downloading'})
        # Если уже скачана, удаляем локальную папку перед перекачкой
        if model.downloaded and model.local_path:
            import shutil
            if os.path.exists(model.local_path):
                shutil.rmtree(model.local_path)
        task = download_llm_model_task.delay(model.id)
        model.download_status = 'downloading'
        model.download_progress = 0
        model.download_error = ''
        model.celery_task_id = task.id
        model.downloaded = False
        model.save()
        return JsonResponse({'success': True, 'task_id': task.id})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def llm_download_status(request, model_id):
    try:
        model = LLMModel.objects.get(id=model_id)
        return JsonResponse({
            'status': model.download_status,
            'progress': model.download_progress,
            'error': model.download_error
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=404)

@staff_member_required
def llm_cancel_download(request, model_id):
    try:
        model = LLMModel.objects.get(id=model_id)
        if model.download_status == 'downloading' and model.celery_task_id:
            AsyncResult(model.celery_task_id).revoke(terminate=True)
        model.download_status = 'not_started'
        model.download_progress = 0
        model.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def llm_set_default(request, model_id):
    try:
        LLMModel.objects.update(is_default=False)
        model = LLMModel.objects.get(id=model_id)
        model.is_default = True
        model.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def llm_delete(request, model_id):
    try:
        model = LLMModel.objects.get(id=model_id)
        if model.downloaded and model.local_path and os.path.exists(model.local_path):
            import shutil
            shutil.rmtree(model.local_path)
        model.delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})





