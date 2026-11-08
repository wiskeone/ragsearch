from cryptography.fernet import Fernet
from django.conf import settings

def get_fernet():
    """Возвращает экземпляр Fernet для шифрования/дешифрования."""
    return Fernet(settings.ENCRYPTION_KEY.encode())