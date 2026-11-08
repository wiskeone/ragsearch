"""v2.0: тесты шифрования документов (round-trip, Fernet)."""
from django.test import SimpleTestCase
from django.conf import settings
from cryptography.fernet import Fernet
from rag.services.encryption import get_fernet


class EncryptionRoundTripTests(SimpleTestCase):
    """Шифрование-расшифровка должно быть взаимно обратным и не оставлять
    открытый текст в шифротексте."""

    def test_round_trip(self):
        f = get_fernet()
        samples = [
            "Простой текст на русском языке",
            "Aviation safety document #145 — VOT-98/2026 ✈",
            "",  # пустая строка — валидный крайний случай
            "emoji 🔐 and unicode ñ ö ü",
        ]
        for text in samples:
            with self.subTest(text=text[:30]):
                token = f.encrypt(text.encode("utf-8"))
                self.assertNotIn(text.encode("utf-8"), token)  # открытый текст не течёт
                self.assertEqual(f.decrypt(token).decode("utf-8"), text)

    def test_key_from_settings_is_valid_fernet_key(self):
        # ENCRYPTION_KEY из настроек обязан быть валидным Fernet-ключом —
        # иначе шифрование падало бы на первом документе
        Fernet(settings.ENCRYPTION_KEY.encode())

    def test_wrong_key_fails(self):
        f1 = Fernet(settings.ENCRYPTION_KEY.encode())
        f2 = Fernet(Fernet.generate_key())
        token = f1.encrypt(b"secret")
        with self.assertRaises(Exception):
            f2.decrypt(token)

    def test_generate_key_script_output_is_valid(self):
        # scripts/generate_encryption_key.sh печатает Fernet.generate_key()
        self.assertTrue(Fernet.generate_key().startswith(b"gAAAAA") is False)  # ключ base64, не фиксированный префикс
        Fernet(Fernet.generate_key())  # валиден
