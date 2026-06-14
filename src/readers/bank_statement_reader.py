import pathlib
from abc import ABC, abstractmethod

from pymupdf import pymupdf


class BankStatementReader(ABC):
    """Abstract Base Class enforcing the Interface for all statement readers."""
    
    def __init__(self, file_path: str | pathlib.Path):
        self.file_path = pathlib.Path(file_path)
        
    def _extract_raw_pdf_text(self, include_page_breaks: bool = False) -> str:
        """Isolated File I/O responsibility."""
        if not self.file_path.exists():
            raise FileNotFoundError(f"The file {self.file_path} does not exist.")
            
        text_segments = []
        with pymupdf.open(self.file_path) as doc:
            for page in doc:
                text_segments.append(page.get_text("text"))
                
        join_delimiter = "\n---PAGE_BREAK---\n" if include_page_breaks else "\n"
        return join_delimiter.join(text_segments)

    @abstractmethod
    def read(self) -> list[tuple[str, str]]:
        """Layout parsing responsibility to be implemented by specific banks."""
        pass