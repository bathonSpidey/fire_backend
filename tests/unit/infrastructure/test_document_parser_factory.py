from unittest.mock import patch

import pytest
from src.fire.config.settings import Settings
from src.fire.infrastructure.llm.document_parser_factory import DocumentParserFactory
from src.fire.infrastructure.llm.gemini_document_parser import GeminiDocumentParser
from src.fire.infrastructure.llm.ollama_document_parser import OllamaDocumentParser
from src.fire.infrastructure.llm.pdf_text_parser import PdfTextParser


def test_pdf_parser_is_always_available() -> None:
    factory = DocumentParserFactory(Settings())
    assert isinstance(factory.get_pdf_parser(), PdfTextParser)


def test_pdf_mime_always_routes_to_pdf_parser() -> None:
    factory = DocumentParserFactory(Settings())
    parser = factory.get_parser_for_mime("application/pdf")
    assert isinstance(parser, PdfTextParser)


def test_image_routes_to_gemini_when_configured() -> None:
    with patch.dict(
        "os.environ",
        {
            "FIRE_RECEIPT_PROVIDER": "gemini",
            "GEMINI_API_KEY": "fake-key",
        },
    ):
        factory = DocumentParserFactory(Settings())
        parser = factory.get_parser_for_mime("image/png")
        assert isinstance(parser, GeminiDocumentParser)


def test_image_routes_to_ollama_when_configured() -> None:
    with patch.dict("os.environ", {"FIRE_RECEIPT_PROVIDER": "ollama"}):
        factory = DocumentParserFactory(Settings())
        parser = factory.get_parser_for_mime("image/jpeg")
        assert isinstance(parser, OllamaDocumentParser)


def test_gemini_raises_without_api_key() -> None:
    with patch.dict(
        "os.environ",
        {
            "FIRE_RECEIPT_PROVIDER": "gemini",
            "GEMINI_API_KEY": "",
        },
    ):
        factory = DocumentParserFactory(Settings())
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            factory.get_image_parser()


def test_claude_raises_not_implemented() -> None:
    with patch.dict("os.environ", {"FIRE_RECEIPT_PROVIDER": "claude"}):
        factory = DocumentParserFactory(Settings())
        with pytest.raises(NotImplementedError):
            factory.get_image_parser()
