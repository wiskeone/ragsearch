import os
import logging
import chardet
import pandas as pd
from bs4 import BeautifulSoup
from striprtf.striprtf import rtf_to_text
from odf.opendocument import load as odf_load
from odf.text import P
from ebooklib import epub
from pptx import Presentation
import docx2txt
import pdfplumber
import markdown
import csv
import io

logger = logging.getLogger(__name__)

class DocumentParser:
    """Унифицированное извлечение текста из разных форматов."""

    @staticmethod
    def extract(file_path, original_filename):
        """
        Определяет формат по расширению и возвращает извлечённый текст.
        """
        ext = os.path.splitext(original_filename)[1].lower()
        if ext == '.pdf':
            return DocumentParser._extract_pdf(file_path)
        elif ext in ('.docx', '.doc'):
            return DocumentParser._extract_docx(file_path)
        elif ext == '.pptx':
            return DocumentParser._extract_pptx(file_path)
        elif ext in ('.xlsx', '.xls', '.ods'):
            return DocumentParser._extract_spreadsheet(file_path, ext)
        elif ext in ('.html', '.htm'):
            return DocumentParser._extract_html(file_path)
        elif ext == '.epub':
            return DocumentParser._extract_epub(file_path)
        elif ext == '.odt':
            return DocumentParser._extract_odt(file_path)
        elif ext == '.rtf':
            return DocumentParser._extract_rtf(file_path)
        elif ext == '.csv':
            return DocumentParser._extract_csv(file_path)
        elif ext in ('.md', '.markdown'):
            return DocumentParser._extract_markdown(file_path)
        elif ext == '.txt':
            return DocumentParser._extract_txt(file_path)
        else:
            raise ValueError(f"Неподдерживаемый формат: {ext}")

    @staticmethod
    def _read_file_content(file_path, binary=False):
        with open(file_path, 'rb') as f:
            raw = f.read()
        if binary:
            return raw
        encoding = chardet.detect(raw)['encoding'] or 'utf-8'
        return raw.decode(encoding, errors='replace')

    @staticmethod
    def _extract_pdf(file_path):
        text = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text.append(page_text)
        return '\n'.join(text)

    @staticmethod
    def _extract_docx(file_path):
        return docx2txt.process(file_path)

    @staticmethod
    def _extract_pptx(file_path):
        prs = Presentation(file_path)
        text = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text.append(shape.text)
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame.text
                if notes.strip():
                    text.append(f"[Заметки]: {notes}")
        return '\n'.join(text)

    @staticmethod
    def _extract_spreadsheet(file_path, ext):
        """Извлекает данные из Excel/OpenOffice таблиц в читаемом текстовом виде."""
        try:
            if ext in ('.xlsx', '.xls'):
                df_dict = pd.read_excel(file_path, sheet_name=None)
            else:  # .ods
                df_dict = pd.read_excel(file_path, engine='odf', sheet_name=None)
        except Exception as e:
            logger.error(f"Ошибка чтения таблицы: {e}")
            return ""
        parts = []
        for sheet_name, df in df_dict.items():
            if df.empty:
                continue
            parts.append(f"=== Лист: {sheet_name} ===")
            # преобразуем DataFrame в строку с разделителями табуляции
            parts.append(df.to_csv(sep='\t', index=False, header=True))
        return '\n'.join(parts)

    @staticmethod
    def _extract_html(file_path):
        raw = DocumentParser._read_file_content(file_path, binary=True)
        soup = BeautifulSoup(raw, 'lxml')
        for script in soup(["script", "style"]):
            script.decompose()
        return soup.get_text(separator='\n')

    @staticmethod
    def _extract_epub(file_path):
        book = epub.read_epub(file_path)
        text = []
        for item in book.get_items_of_type(9):  # ITEM_DOCUMENT
            soup = BeautifulSoup(item.get_content(), 'lxml')
            text.append(soup.get_text(separator='\n'))
        return '\n'.join(text)

    @staticmethod
    def _extract_odt(file_path):
        doc = odf_load(file_path)
        paragraphs = doc.getElementsByType(P)
        return '\n'.join([str(p) for p in paragraphs])

    @staticmethod
    def _extract_rtf(file_path):
        raw = DocumentParser._read_file_content(file_path)
        return rtf_to_text(raw)

    @staticmethod
    def _extract_csv(file_path):
        raw = DocumentParser._read_file_content(file_path)
        try:
            dialect = csv.Sniffer().sniff(raw[:1024])
        except csv.Error:
            dialect = 'excel'
        reader = csv.reader(io.StringIO(raw), dialect)
        lines = ['\t'.join(row) for row in reader]
        return '\n'.join(lines)

    @staticmethod
    def _extract_markdown(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            md_text = f.read()
        html = markdown.markdown(md_text)
        soup = BeautifulSoup(html, 'lxml')
        return soup.get_text(separator='\n')

    @staticmethod
    def _extract_txt(file_path):
        return DocumentParser._read_file_content(file_path)