"""
v3.x: vLLM клиент — опциональный OpenAI-совместимый инференс-бэкенд.

Аналог Ivanna Lab: заменяет in-process transformers на HTTP-вызовы
к внешнему vLLM-серверу. Контракт совместим с ChatService.generate_response.

Настройки (settings.py / .env):
    VLLM_BASE_URL   — http://vllm:8001/v1
    VLLM_API_KEY    — токен (опционально)
    VLLM_TIMEOUT    — сек (дефолт 300)
"""
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class VLLMClient:
    def __init__(self, base_url=None, api_key=None, timeout=None):
        self.base_url = (base_url or getattr(settings, 'VLLM_BASE_URL', 'http://vllm:8001/v1')).rstrip('/')
        self.api_key = api_key or getattr(settings, 'VLLM_API_KEY', '') or None
        self.timeout = timeout or getattr(settings, 'VLLM_TIMEOUT', 300)

    def _headers(self):
        h = {'Content-Type': 'application/json'}
        if self.api_key:
            h['Authorization'] = f'Bearer {self.api_key}'
        return h

    def health(self):
        try:
            base = self.base_url.rsplit('/v1', 1)[0]
            return requests.get(f'{base}/health', timeout=10).status_code == 200
        except Exception:
            return False

    def generate(self, model, prompt, max_tokens=512, temperature=0.7, **kw):
        """POST /v1/completions. Возвращает {'success', 'response', 'device': 'vllm', ...}."""
        payload = {
            'model': model, 'prompt': prompt,
            'max_tokens': int(max_tokens), 'temperature': float(temperature),
            'stream': False,
        }
        start = time.time()
        try:
            r = requests.post(f'{self.base_url}/completions', json=payload,
                              headers=self._headers(), timeout=self.timeout)
            if r.status_code != 200:
                detail = r.text[:300]
                logger.error(f"vLLM HTTP {r.status_code}: {detail}")
                return {'success': False, 'error': f'vLLM HTTP {r.status_code}: {detail}'}
            data = r.json()
            choices = data.get('choices') or []
            if not choices:
                return {'success': False, 'error': 'vLLM returned no choices'}
            usage = data.get('usage', {}) or {}
            generation_time = time.time() - start
            return {
                'success': True,
                'response': choices[0].get('text', ''),
                'input_tokens': usage.get('prompt_tokens', 0),
                'output_tokens': usage.get('completion_tokens', 0),
                'total_tokens': usage.get('total_tokens', 0),
                'generation_time': generation_time,
                'device': 'vllm',
            }
        except requests.exceptions.Timeout:
            return {'success': False, 'error': f'vLLM timeout after {self.timeout}s'}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': 'vLLM is unreachable'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
