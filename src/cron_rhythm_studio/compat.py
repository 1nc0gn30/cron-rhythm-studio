"""Cross-platform compatibility utilities for cron-rhythm-studio.

Provides resilient file I/O, atomic write operations with fsync,
path normalization, and platform detection across Linux, macOS, Windows, and Termux.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple, Union


@dataclass(frozen=True)
class PlatformInfo:
    """Platform runtime environment information."""
    system: str
    release: str
    machine: str
    python_version: str
    is_windows: bool
    is_linux: bool
    is_macos: bool
    is_termux: bool
    supports_fsync: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "release": self.release,
            "machine": self.machine,
            "python_version": self.python_version,
            "is_windows": self.is_windows,
            "is_linux": self.is_linux,
            "is_macos": self.is_macos,
            "is_termux": self.is_termux,
            "supports_fsync": self.supports_fsync,
        }


def get_platform_info() -> PlatformInfo:
    """Detect current operating system and platform capabilities."""
    sys_name = platform.system()
    is_win = sys_name == "Windows"
    is_mac = sys_name == "Darwin"
    is_lin = sys_name == "Linux"
    
    # Termux detection
    is_termux = False
    if is_lin:
        prefix = os.environ.get("PREFIX", "")
        if "com.termux" in prefix or Path("/data/data/com.termux").exists():
            is_termux = True

    # Test fsync support
    fsync_supported = hasattr(os, "fsync")

    return PlatformInfo(
        system=sys_name,
        release=platform.release(),
        machine=platform.machine(),
        python_version=platform.python_version(),
        is_windows=is_win,
        is_linux=is_lin,
        is_macos=is_mac,
        is_termux=is_termux,
        supports_fsync=fsync_supported,
    )


def safe_path(path: Union[str, Path]) -> Path:
    """Safely expand and resolve a file system path across operating systems."""
    p = Path(path).expanduser()
    try:
        return p.resolve()
    except (OSError, RuntimeError):
        return p.absolute()


def atomic_write_bytes(
    path: Union[str, Path],
    data: bytes,
    fsync: bool = True,
) -> int:
    """Write bytes atomically to target path using a temporary file and atomic replace.
    
    Args:
        path: Target file path.
        data: Byte content to write.
        fsync: Whether to flush disk buffers before replacing.
        
    Returns:
        Number of bytes written.
    """
    target = safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp_filename = f".{target.name}.tmp.{uuid.uuid4().hex}"
    tmp_path = target.parent / tmp_filename

    try:
        with open(tmp_path, "wb") as f:
            bytes_written = f.write(data)
            f.flush()
            if fsync and hasattr(os, "fsync"):
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
        
        # Atomic rename
        os.replace(tmp_path, target)
        return bytes_written
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def atomic_write_text(
    path: Union[str, Path],
    content: str,
    encoding: str = "utf-8",
    fsync: bool = True,
) -> int:
    """Write text atomically to target path with specified encoding.
    
    Args:
        path: Target file path.
        content: Text content to write.
        encoding: Text encoding (default: utf-8).
        fsync: Whether to flush disk buffers before replacing.
        
    Returns:
        Number of bytes written.
    """
    data = content.encode(encoding)
    return atomic_write_bytes(path, data, fsync=fsync)


def read_text_safe(
    path: Union[str, Path],
    default: str = "",
    encoding: str = "utf-8",
    fallback_encodings: Tuple[str, ...] = ("utf-8-sig", "latin-1", "cp1252"),
) -> str:
    """Safely read text from a file with fallback encoding support.
    
    Args:
        path: Path to file.
        default: Default value if file cannot be read.
        encoding: Primary encoding to try.
        fallback_encodings: Secondary encodings if primary fails.
        
    Returns:
        File contents as string, or default if missing or unreadable.
    """
    target = safe_path(path)
    if not target.is_file():
        return default

    # Try primary encoding
    try:
        return target.read_text(encoding=encoding)
    except (UnicodeDecodeError, OSError):
        pass

    # Try fallbacks
    for enc in fallback_encodings:
        try:
            return target.read_text(encoding=enc)
        except (UnicodeDecodeError, OSError):
            continue

    return default


def read_json_safe(
    path: Union[str, Path],
    default: Any = None,
) -> Any:
    """Safely read and parse a JSON file.
    
    Args:
        path: Path to JSON file.
        default: Default value if file is missing or invalid JSON.
        
    Returns:
        Parsed JSON object or default.
    """
    content = read_text_safe(path, default="")
    if not content.strip():
        return default
    try:
        return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return default


def write_json_safe(
    path: Union[str, Path],
    obj: Any,
    indent: int = 2,
    fsync: bool = True,
) -> bool:
    """Safely serialize and write an object to JSON file atomically.
    
    Args:
        path: Target file path.
        obj: Serializable object.
        indent: JSON indentation.
        fsync: Whether to flush disk buffers.
        
    Returns:
        True if write succeeded, False otherwise.
    """
    try:
        content = json.dumps(obj, indent=indent, default=str, ensure_ascii=False)
        atomic_write_text(path, content + "\n", encoding="utf-8", fsync=fsync)
        return True
    except Exception:
        return False


def safe_delete_file(path: Union[str, Path]) -> bool:
    """Safely delete a file if it exists."""
    target = safe_path(path)
    try:
        if target.is_file() or target.is_symlink():
            target.unlink(missing_ok=True)
            return True
        return False
    except OSError:
        return False


def safe_delete_dir(path: Union[str, Path]) -> bool:
    """Safely delete a directory tree if it exists."""
    target = safe_path(path)
    try:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            return True
        return False
    except OSError:
        return False
