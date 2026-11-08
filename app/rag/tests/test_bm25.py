"""v2.0: тесты гибридного слияния скоров (чистая логика RAGService)."""
from django.test import SimpleTestCase
from rag.services.rag_service import RAGService


class MergeLogicTests(SimpleTestCase):
    def setUp(self):
        self.rag = RAGService.__new__(RAGService)  # без __init__ (не строим эмбеддер)

    def test_get_chunks_details_preserves_order_and_scores(self):
        """FIX-регресс: скоры не должны приписываться чужим чанкам."""
        results = [{"chunk_id": 42, "score": 0.9}, {"chunk_id": 7, "score": 0.4}]

        class FakeQS(list):
            def select_related(self, *a, **k):
                return self

        class FakeChunk:
            def __init__(self, cid):
                self.id = cid
                self.document = type("D", (), {"id": cid, "title": f"doc{cid}"})()
            content = "текст"

        fake = FakeQS([FakeChunk(7), FakeChunk(42)])  # намеренно обратный порядок
        with patch_queryset(self.rag, fake):
            out = self.rag.get_chunks_details(results)
        self.assertEqual([c["chunk_id"] for c in out], [42, 7])  # порядок = выдаче
        self.assertEqual(out[0]["score"], 0.9)
        self.assertEqual(out[1]["score"], 0.4)


def patch_queryset(rag, fake):
    from unittest.mock import patch
    return patch("rag.services.rag_service.DocumentChunk.objects.filter", return_value=fake)
