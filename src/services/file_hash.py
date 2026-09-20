"""Identity of an uploaded document, shared by the launcher and the MCP server.

A document is either one file or a folder of files (e.g. several screenshots of one statement).
A single file keeps the plain sha256 of its bytes, so hashes stored before groups existed stay
valid.
"""

import hashlib
import pathlib


def source_files(path: pathlib.Path) -> list[pathlib.Path]:
    """The files that make up the document, in reading order (folders: by file name)."""
    if path.is_dir():
        return sorted(p for p in path.iterdir() if p.is_file())
    return [path]


def source_sha256(path: pathlib.Path) -> str:
    if not path.is_dir():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    combined = hashlib.sha256()
    for file in source_files(path):
        combined.update(hashlib.sha256(file.read_bytes()).digest())
    return combined.hexdigest()
