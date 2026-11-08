"""
v3.0: API-ключи — генерация, хеширование, DRF auth class.

Сырой ключ показывается ОДИН РАЗ при создании; в БД хранится SHA-256.
Формат: rs_<24 hex chars>. Префикс (rs_XXXXXXXX) — для отображения.
"""
import hashlib
import secrets

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import ApiKey, UserProfile


def generate_api_key() -> tuple[str, str, str]:
    """Генерирует ключ. Возвращает (raw_key, key_hash, prefix)."""
    raw = f"rs_{secrets.token_hex(16)}"           # rs_<32 hex>
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:10]                              # rs_XXXXXX
    return raw, key_hash, prefix


def resolve_api_key(raw_key: str) -> ApiKey | None:
    """Ищет активный ключ по SHA-256 хешу."""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return ApiKey.objects.filter(
        key_hash=key_hash, is_active=True
    ).select_related('user').first()


class ApiKeyAuthentication(BaseAuthentication):
    """
    DRF auth class: Authorization: Bearer rs_...

    Использование: на эндпоинтах с программным доступом добавить
    `authentication_classes = [ApiKeyAuthentication, SessionAuthentication]`
    — SessionAuthentication идёт первым для браузера, Bearer-ключ для API.
    """

    def authenticate(self, request):
        auth = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth.startswith('Bearer rs_'):
            return None  # не Bearer-ключ — передаём другим auth классам

        raw_key = auth[7:]  # после "Bearer "
        api_key = resolve_api_key(raw_key)
        if not api_key:
            raise AuthenticationFailed('Invalid or revoked API key')

        # обновляем last_used_at (раз в минуту, чтобы не спамить БД)
        if not api_key.last_used_at or \
           (timezone.now() - api_key.last_used_at).total_seconds() > 60:
            ApiKey.objects.filter(pk=api_key.pk).update(last_used_at=timezone.now())

        return (api_key.user, api_key)

    def authenticate_header(self, request):
        return 'Bearer'
