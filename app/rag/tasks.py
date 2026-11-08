import os
import gc
import torch
import shutil
import logging
import tempfile
import psutil
import time
from celery import shared_task
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from django.conf import settings
from django.utils import timezone
from .services.encryption import get_fernet
from .services.embedding_service import embedding_service
from .services.faiss_service import FAISSService
from .services.document_parser import DocumentParser
from huggingface_hub import snapshot_download
from .models import LLMModel

logger = logging.getLogger(__name__)

# Глобальный кэш загруженных LLM (в памяти воркера)
_llm_cache = {}

# Вспомогательная функция чанкинга
def chunk_text(text, chunk_size=1000, overlap=200):
    """Разбивает текст на чанки с перекрытием."""
    if overlap >= chunk_size:
        overlap = chunk_size // 2
        logger.warning(f"Overlap >= chunk_size, adjusted to {overlap}")

    chunks = []
    start = 0
    idx = 0
    text_len = len(text)
    previous_start = 0

    while start < text_len:
        if idx > 0 and start == previous_start:
            logger.error(f"Chunking stuck at start={start}, breaking")
            break
        previous_start = start

        end = min(start + chunk_size, text_len)
        chunk_content = text[start:end]
        chunks.append({
            'index': idx,
            'content': chunk_content,
            'token_count': len(chunk_content.split())
        })
        start = end - overlap
        idx += 1

        if idx > 100000:
            logger.warning("Chunk limit reached (100000), stopping")
            break

    logger.info(f"Generated {len(chunks)} chunks from {text_len} chars")
    return chunks


@shared_task(bind=True, queue='gpu_tasks')
def process_document_task(self, document_id):
    """
    Полная обработка документа:
    - Извлечение текста
    - Разбиение на чанки
    - Создание эмбеддингов батчами (на CPU)
    - Индексация в FAISS
    """
    # Ленивый импорт моделей для избежания циклических зависимостей
    from .models import Document, DocumentChunk, EmbeddingModel

    logger.info(f"[START] Processing document {document_id}")

    try:
        doc = Document.objects.select_related('collection').get(id=document_id)
    except Document.DoesNotExist:
        logger.error(f"Document {document_id} not found")
        return {'success': False, 'error': 'Document not found'}

    doc.status = 'processing'
    doc.save(update_fields=['status'])

    # Параметры чанкинга
    chunk_size = getattr(settings, 'DEFAULT_CHUNK_SIZE', 1000)
    chunk_overlap = getattr(settings, 'DEFAULT_CHUNK_OVERLAP', 200)
    if doc.collection:
        chunk_size = doc.collection.chunk_size or chunk_size
        chunk_overlap = doc.collection.chunk_overlap or chunk_overlap
    logger.info(f"Chunking config: size={chunk_size}, overlap={chunk_overlap}")

    try:
        # ========== ШАГ 1: Извлечение текста ==========
        logger.info("[STEP 1/5] Extracting text...")
        fernet = get_fernet()
        with open(doc.file_encrypted_path, 'rb') as f:
            encrypted = f.read()
        decrypted = fernet.decrypt(encrypted)

        ext = os.path.splitext(doc.original_filename)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(decrypted)
            tmp_path = tmp.name

        try:
            text = DocumentParser.extract(tmp_path, doc.original_filename)
        finally:
            os.unlink(tmp_path)

        # v3.x: инкрементальная индексация — если контент не изменился,
        # пропускаем чанкирование/эмбеддинги/FAISS (документ уже indexed)
        import hashlib
        content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if doc.content_hash == content_hash and doc.status == 'processed':
            logger.info(f"[SKIP] Document {document_id}: content unchanged (hash match)")
            return {'success': True, 'skipped': True, 'reason': 'content_unchanged'}
        doc.content_hash = content_hash
        doc.save(update_fields=['content_hash'])

        if not text or not text.strip():
            raise ValueError("No extractable text found")

        mem = psutil.virtual_memory()
        logger.info(f"[MEMORY] After text extraction: used={mem.used/1024**3:.2f}GB, free={mem.available/1024**3:.2f}GB")

        # Удаляем старые чанки
        doc.chunks.all().delete()

        # ========== ШАГ 2: Загрузка модели эмбеддингов ==========
        logger.info("[STEP 2/5] Loading embedding model")
        emb_model = EmbeddingModel.objects.filter(is_default=True).first()
        if not emb_model:
            emb_model = EmbeddingModel.objects.create(
                name="BGE-M3",
                model_id=settings.DEFAULT_EMBEDDING_MODEL,
                embedding_dim=settings.EMBEDDING_DIMENSION,
                is_default=True,
                downloaded=False
            )
        logger.info(f"Using embedding model: {emb_model.model_id} (id={emb_model.id})")

        # ========== ШАГ 3: Генерация всех чанков ==========
        logger.info("[STEP 3/5] Generating chunks...")
        all_chunks_data = list(chunk_text(text, chunk_size, chunk_overlap))
        total_chunks = len(all_chunks_data)
        logger.info(f"Generated {total_chunks} chunks")

        chunk_objects = []
        for ch_data in all_chunks_data:
            chunk_objects.append(DocumentChunk(
                document=doc,
                chunk_index=ch_data['index'],
                content=ch_data['content'],
                token_count=ch_data['token_count'],
                has_embedding=False
            ))

        created_chunks = DocumentChunk.objects.bulk_create(chunk_objects)
        logger.info(f"Saved {len(created_chunks)} chunks to DB")

        # ========== ШАГ 4: Создание эмбеддингов батчами (на CPU) ==========
        logger.info("[STEP 4/5] Creating embeddings in batches (CPU)")
        BATCH_SIZE = settings.EMBEDDING_BATCH_SIZE
        total_embedded = 0
        total_batches = (total_chunks + BATCH_SIZE - 1) // BATCH_SIZE

        for i in range(0, len(created_chunks), BATCH_SIZE):
            batch = created_chunks[i:i+BATCH_SIZE]
            texts = [ch.content for ch in batch]

            try:
                embeddings = embedding_service.create_embeddings_batch(
                    texts=texts,
                    model_name=emb_model.model_id,
                    normalize=True,
                    batch_size=len(batch)
                )
                for j, ch in enumerate(batch):
                    ch.embedding_vector = embeddings[j].tolist()
                    ch.has_embedding = True
                    ch.embedding_model = emb_model
                    ch.embedding_dim = len(embeddings[j])
                DocumentChunk.objects.bulk_update(batch, ['embedding_vector', 'has_embedding', 'embedding_model', 'embedding_dim'])
                total_embedded += len(batch)

                # Очистка памяти только раз в 10 батчей (не нужна для CPU, но оставим для порядка)
                if (i // BATCH_SIZE) % 10 == 0:
                    gc.collect()

                logger.info(f"Batch {i//BATCH_SIZE + 1}/{total_batches}: embedded {total_embedded}/{total_chunks}")
                self.update_state(
                    state='PROGRESS',
                    meta={'progress': int(total_embedded / total_chunks * 100), 'step': f'Embedding {total_embedded}/{total_chunks}'}
                )

            except Exception as e:
                logger.error(f"Batch embedding failed at index {i}: {e}", exc_info=True)
                for ch in batch:
                    ch.has_embedding = False
                    ch.save(update_fields=['has_embedding'])
                continue

        mem = psutil.virtual_memory()
        logger.info(f"[MEMORY] After embedding: used={mem.used/1024**3:.2f}GB, free={mem.available/1024**3:.2f}GB")

        # ========== ШАГ 5: Индексация в FAISS (только если есть эмбеддинги) ==========
        logger.info("[STEP 5/5] Updating FAISS index")
        if doc.collection_id and total_embedded > 0:
            try:
                chunks_with_emb = doc.chunks.filter(has_embedding=True)
                if chunks_with_emb.exists():
                    faiss_service = FAISSService()
                    faiss_service.add_document(doc.collection_id, list(chunks_with_emb))
                    logger.info(f"FAISS index updated for collection {doc.collection_id} with {chunks_with_emb.count()} vectors")
                else:
                    logger.warning("No chunks with embeddings, skipping FAISS")
            except Exception as e:
                logger.error(f"FAISS indexing failed: {e}", exc_info=True)
        else:
            logger.info("Skipping FAISS (no collection or no embeddings)")

        doc.status = 'processed'
        doc.processed_at = timezone.now()
        doc.save(update_fields=['status', 'processed_at'])

        logger.info(f"[DONE] Document {document_id} processed: {total_chunks} chunks, {total_embedded} embeddings")
        return {
            'success': True,
            'document_id': document_id,
            'chunks_created': total_chunks,
            'embeddings_created': total_embedded
        }

    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}", exc_info=True)
        doc.status = 'error'
        doc.error_message = str(e)
        doc.save(update_fields=['status', 'error_message'])
        return {'success': False, 'error': str(e), 'document_id': document_id}


@shared_task(bind=True, queue='gpu_tasks')
def download_llm_model_task(self, model_id):
    from .models import LLMModel
    import shutil
    from django.conf import settings

    try:
        model = LLMModel.objects.get(id=model_id)
        model.download_status = 'downloading'
        model.download_progress = 0
        model.celery_task_id = self.request.id
        model.downloaded = False
        model.save()

        local_dir = os.path.join(settings.MEDIA_ROOT, 'llm_models', model.model_id.replace('/', '_'))
        if os.path.exists(local_dir):
            shutil.rmtree(local_dir)
        os.makedirs(local_dir, exist_ok=True)

        snapshot_download(
            repo_id=model.model_id,
            local_dir=local_dir,
            token=os.getenv('HF_TOKEN'),
            ignore_patterns=['*.h5', '*.ot', '*.msgpack']
        )

        model.local_path = local_dir
        model.downloaded = True
        model.download_status = 'completed'
        model.download_progress = 100
        model.save()
        return {'success': True}
    except Exception as e:
        # FIX: если упал сам LLMModel.objects.get — model не определён,
        # except падал с UnboundLocalError вместо честной ошибки
        if 'model' in dir() and model is not None:
            model.download_status = 'failed'
            model.download_error = str(e)
            model.save()
        raise self.retry(exc=e, countdown=60, max_retries=3)


@shared_task(bind=True, queue='cpu_tasks')
def download_embedding_model_task(self, model_id):
    from .models import EmbeddingModel

    try:
        model = EmbeddingModel.objects.get(id=model_id)
        model.download_status = 'downloading'
        model.download_progress = 0
        model.celery_task_id = self.request.id
        model.save()

        local_dir = os.path.join(settings.MEDIA_ROOT, 'embedding_models', model.model_id.replace('/', '_'))
        if os.path.exists(local_dir):
            shutil.rmtree(local_dir)
        os.makedirs(local_dir, exist_ok=True)

        snapshot_download(
            repo_id=model.model_id,
            local_dir=local_dir,
            token=os.getenv('HF_TOKEN'),
            ignore_patterns=['*.h5', '*.ot', '*.msgpack']
        )

        model.local_path = local_dir
        model.downloaded = True
        model.download_status = 'completed'
        model.download_progress = 100
        model.save()
        return {'success': True}
    except Exception as e:
        model.download_status = 'failed'
        model.download_error = str(e)
        model.save()
        raise


@shared_task(queue='cpu_tasks')
def rebuild_collection_index(collection_id):
    from .services.rag_service import RAGService
    rag = RAGService()
    rag.rebuild_collection_index(collection_id)


@shared_task(bind=True, queue='gpu_tasks')
def create_embeddings_for_collection_task(self, collection_id):
    from .models import Collection, DocumentChunk, EmbeddingModel
    from .services.faiss_service import FAISSService

    logger.info(f"[START] Creating embeddings for collection {collection_id}")

    try:
        collection = Collection.objects.get(id=collection_id)
    except Collection.DoesNotExist:
        logger.error(f"Collection {collection_id} not found")
        return {'success': False, 'error': 'Collection not found'}

    emb_model = EmbeddingModel.objects.filter(is_default=True).first()
    if not emb_model:
        error_msg = "No default embedding model found"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}
    logger.info(f"[MODEL] Using embedding model: {emb_model.model_id} (id={emb_model.id})")

    chunks = DocumentChunk.objects.filter(
        document__collection=collection,
        has_embedding=False,
        is_active=True
    ).exclude(content='')

    total = chunks.count()
    logger.info(f"Found {total} chunks without embeddings in collection {collection_id}")

    if total == 0:
        logger.info(f"All chunks already have embeddings, updating FAISS index only")
        faiss = FAISSService()
        faiss.add_document(collection_id, [])
        return {'success': True, 'message': 'FAISS index updated'}

    processed = 0
    batch_size = 64

    for i in range(0, total, batch_size):
        batch = chunks[i:i+batch_size]
        texts = [ch.content for ch in batch]
        try:
            embeddings = embedding_service.create_embeddings_batch(
                texts=texts,
                model_name=emb_model.model_id,
                normalize=True,
                batch_size=batch_size
            )
            for j, chunk in enumerate(batch):
                chunk.embedding_vector = embeddings[j].tolist()
                chunk.embedding_model = emb_model
                chunk.has_embedding = True
                chunk.embedding_dim = len(embeddings[j])
                chunk.save()
            processed += len(batch)

            self.update_state(
                state='PROGRESS',
                meta={'current': processed, 'total': total, 'percent': int(processed / total * 100)}
            )
            if (i // batch_size) % 10 == 0:
                gc.collect()
            logger.info(f"Batch {i//batch_size+1}/{ (total+batch_size-1)//batch_size }: processed {processed}/{total}")

        except Exception as e:
            logger.error(f"Error processing batch starting at index {i}: {e}", exc_info=True)

    if processed > 0:
        logger.info(f"Building FAISS index for collection {collection_id}")
        faiss = FAISSService()
        faiss.add_document(collection_id, [])
        logger.info(f"FAISS index updated for collection {collection_id}")

    logger.info(f"[DONE] Embedding creation completed for collection {collection_id}: {processed} chunks processed")
    return {'success': True, 'collection_id': collection_id, 'chunks_processed': processed}


@shared_task(bind=True, queue='gpu_tasks')
def generate_text_task(self, model_id, prompt, max_tokens=512, temperature=0.7,
                       session_id=None, use_rag=False, rag_config=None, **kwargs):
    logger.info(f"generate_text_task: model_id={model_id}, prompt_len={len(prompt)}, session_id={session_id}")
    try:
        llm_model = LLMModel.objects.get(id=model_id, downloaded=True)
        model_identifier = llm_model.model_id

        if model_identifier not in _llm_cache:
            logger.info(f"Loading LLM {model_identifier}...")
            tokenizer = AutoTokenizer.from_pretrained(model_identifier, trust_remote_code=True)
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4"
            )
            model = AutoModelForCausalLM.from_pretrained(
                model_identifier,
                quantization_config=quantization_config,
                device_map="auto",
                trust_remote_code=True
            )
            model.eval()
            _llm_cache[model_identifier] = (model, tokenizer)

        model, tokenizer = _llm_cache[model_identifier]

        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        start_time = time.time()
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                do_sample=temperature > 0,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        gen_time = time.time() - start_time
        response = tokenizer.decode(outputs[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)
        input_tokens = inputs['input_ids'].shape[1]
        output_tokens = outputs.shape[1] - input_tokens

        return {
            'success': True,
            'response': response.strip(),
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': input_tokens + output_tokens,
            'generation_time': gen_time,
            'tokens_per_second': output_tokens / gen_time if gen_time > 0 else 0,
            'device': str(model.device),
            'session_id': session_id,
        }
    except Exception as e:
        logger.error(f"Error in generate_text_task: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}