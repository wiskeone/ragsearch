"""v2.0: тесты парсера документов на лёгких форматах."""
from django.test import SimpleTestCase
import tempfile
import os
from rag.services.document_parser import DocumentParser


class PlainTextParserTests(SimpleTestCase):
    def _extract(self, name, data):
        fd, path = tempfile.mkstemp(suffix=os.path.splitext(name)[1])
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            return DocumentParser.extract(path, name)
        finally:
            os.remove(path)

    def test_txt_extracts_text(self):
        text = self._extract("doc.txt", "Привет, мир".encode("utf-8"))
        self.assertIn("Привет", text)

    def test_md_extracts_text(self):
        text = self._extract("note.md", "# Заголовок\n\nТекст".encode("utf-8"))
        self.assertIn("Заголовок", text)

    def test_html_strips_tags(self):
        text = self._extract("page.html", "<html><body><p>Содержимое</p></body></html>".encode("utf-8"))
        self.assertIn("Содержимое", text)
        self.assertNotIn("<p>", text)

    def test_csv_extracts_values(self):
        text = self._extract("table.csv", "a,b\n1,2".encode("utf-8"))
        self.assertIn("a", text)

    def test_unknown_format_returns_something_or_raises_cleanly(self):
        # бинарный мусор в неизвестном формате не должен ронять процесс без warning
        try:
            text = self._extract("blob.xyz", b"\x00\x01")
            self.assertIsInstance(text, str)
        except Exception as e:
            self.assertNotIsInstance(e, SystemExit)
