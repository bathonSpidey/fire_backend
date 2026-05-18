"""
Factory that builds the correct ILLMDocumentParser based on Settings.

Routing:
  application/pdf  →  PdfTextParser       (always local, free, no API key)
  image/*          →  provider from FIRE_RECEIPT_PROVIDER setting

Adding a new provider:
  1. Create MyProviderDocumentParser(ILLMDocumentParser) in its own file
  2. Add MY_PROVIDER = "myprovider" to ReceiptProvider in settings.py
  3. Add one elif in _build_image_parser() below — nothing else changes
"""

from src.fire.config.settings import ReceiptProvider, Settings
from src.fire.domain.interfaces.services import ILLMDocumentParser
from src.fire.infrastructure.llm.pdf_text_parser import PdfTextParser


class DocumentParserFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pdf_parser = PdfTextParser()

    def get_pdf_parser(self) -> ILLMDocumentParser:
        return self._pdf_parser

    def get_image_parser(self) -> ILLMDocumentParser:
        return self._build_image_parser()

    def get_parser_for_mime(self, mime_type: str) -> ILLMDocumentParser:
        if mime_type == "application/pdf":
            return self.get_pdf_parser()
        return self.get_image_parser()

    def _build_image_parser(self) -> ILLMDocumentParser:
        provider = self._settings.fire_receipt_provider

        if provider == ReceiptProvider.GEMINI:
            from fire.infrastructure.llm.gemini_document_parser import GeminiDocumentParser

            return GeminiDocumentParser(
                api_key=self._settings.gemini_api_key,
                model=self._settings.gemini_model,
            )

        if provider == ReceiptProvider.CLAUDE:
            from fire.infrastructure.llm.claude_document_parser import ClaudeDocumentParser

            return ClaudeDocumentParser(
                api_key=self._settings.anthropic_api_key,
                model=self._settings.anthropic_model,
            )

        if provider == ReceiptProvider.OLLAMA:
            from fire.infrastructure.llm.ollama_document_parser import OllamaDocumentParser

            return OllamaDocumentParser(
                base_url=self._settings.ollama_base_url,
                vision_model=self._settings.ollama_vision_model,
                text_model=self._settings.ollama_text_model,
            )

        raise ValueError(f"Unknown receipt provider: {provider}")
