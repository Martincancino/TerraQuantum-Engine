"""
Storage abstraction layer — HITO 7 (B-11 path to cloud).

Today: LocalStorageBackend wraps pathlib.Path (zero behaviour change).
Future: S3StorageBackend / GCSStorageBackend implement the same interface.

Switch backends with the STORAGE_BACKEND env var:
  STORAGE_BACKEND=local   (default)
  STORAGE_BACKEND=s3      (not yet implemented — raises NotImplementedError)
  STORAGE_BACKEND=gcs     (not yet implemented — raises NotImplementedError)

Usage in new code:
    from core.storage import storage
    storage.write_bytes(run_dir / "result.parquet", data)
    raw = storage.read_bytes(run_dir / "result.parquet")

Existing code that still uses pathlib.Path directly continues to work —
do not refactor it in bulk; migrate incrementally per service.
"""
import io
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import IO, Iterator


# ── Abstract interface ────────────────────────────────────────────────────────

class StorageBackend(ABC):
    """Minimal filesystem-like interface for run artefacts."""

    @abstractmethod
    def exists(self, path: str | Path) -> bool: ...

    @abstractmethod
    def read_bytes(self, path: str | Path) -> bytes: ...

    @abstractmethod
    def write_bytes(self, path: str | Path, data: bytes) -> None: ...

    @abstractmethod
    def delete(self, path: str | Path) -> None: ...

    @abstractmethod
    def makedirs(self, path: str | Path) -> None: ...

    @abstractmethod
    def list_dir(self, path: str | Path) -> list[str]:
        """Return names of immediate children (files and dirs) under path."""
        ...

    @abstractmethod
    def open(self, path: str | Path, mode: str = "rb") -> IO:
        """Return a file-like object. Caller is responsible for closing it."""
        ...

    @abstractmethod
    def copy(self, src: str | Path, dst: str | Path) -> None: ...

    # ── Convenience helpers (implemented on top of abstract primitives) ───────

    def read_text(self, path: str | Path, encoding: str = "utf-8") -> str:
        return self.read_bytes(path).decode(encoding)

    def write_text(self, path: str | Path, text: str, encoding: str = "utf-8") -> None:
        self.write_bytes(path, text.encode(encoding))


# ── Local implementation ──────────────────────────────────────────────────────

class LocalStorageBackend(StorageBackend):
    """Thin wrapper around pathlib.Path — identical semantics to the current codebase."""

    def exists(self, path: str | Path) -> bool:
        return Path(path).exists()

    def read_bytes(self, path: str | Path) -> bytes:
        return Path(path).read_bytes()

    def write_bytes(self, path: str | Path, data: bytes) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def delete(self, path: str | Path) -> None:
        p = Path(path)
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink(missing_ok=True)

    def makedirs(self, path: str | Path) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)

    def list_dir(self, path: str | Path) -> list[str]:
        p = Path(path)
        if not p.exists():
            return []
        return [child.name for child in p.iterdir()]

    def open(self, path: str | Path, mode: str = "rb") -> IO:
        p = Path(path)
        if "w" in mode:
            p.parent.mkdir(parents=True, exist_ok=True)
        return p.open(mode)

    def copy(self, src: str | Path, dst: str | Path) -> None:
        dst_path = Path(dst)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))


# ── Placeholder stubs (raise clearly — don't silently fall back to local) ─────

class _S3StorageBackend(StorageBackend):
    def __init__(self):
        raise NotImplementedError(
            "S3StorageBackend is not yet implemented. "
            "Install boto3 and implement this class in core/storage.py."
        )

    # All abstract methods — unreachable but satisfy the ABC contract.
    def exists(self, path): raise NotImplementedError
    def read_bytes(self, path): raise NotImplementedError
    def write_bytes(self, path, data): raise NotImplementedError
    def delete(self, path): raise NotImplementedError
    def makedirs(self, path): raise NotImplementedError
    def list_dir(self, path): raise NotImplementedError
    def open(self, path, mode="rb"): raise NotImplementedError
    def copy(self, src, dst): raise NotImplementedError


class _GCSStorageBackend(StorageBackend):
    def __init__(self):
        raise NotImplementedError(
            "GCSStorageBackend is not yet implemented. "
            "Install google-cloud-storage and implement this class in core/storage.py."
        )

    def exists(self, path): raise NotImplementedError
    def read_bytes(self, path): raise NotImplementedError
    def write_bytes(self, path, data): raise NotImplementedError
    def delete(self, path): raise NotImplementedError
    def makedirs(self, path): raise NotImplementedError
    def list_dir(self, path): raise NotImplementedError
    def open(self, path, mode="rb"): raise NotImplementedError
    def copy(self, src, dst): raise NotImplementedError


# ── Factory + module-level singleton ─────────────────────────────────────────

def _build_backend() -> StorageBackend:
    backend_name = os.getenv("STORAGE_BACKEND", "local").lower()
    if backend_name == "local":
        return LocalStorageBackend()
    if backend_name == "s3":
        return _S3StorageBackend()
    if backend_name == "gcs":
        return _GCSStorageBackend()
    raise ValueError(
        f"Unknown STORAGE_BACKEND={backend_name!r}. "
        "Valid values: 'local', 's3', 'gcs'."
    )


# Module-level singleton — imported by services as `from core.storage import storage`.
storage: StorageBackend = _build_backend()
