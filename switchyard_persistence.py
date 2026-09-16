from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import json
import os
import shutil
import tempfile
import threading
import time


@dataclass(frozen=True)
class RecoveryNotice:
    kind: str
    message: str
    source: str | None = None
    archived: str | None = None


class FutureSchemaError(ValueError):
    def __init__(self, found: int, supported: int):
        super().__init__(f'file schema {found} is newer than supported schema {supported}')
        self.found = found
        self.supported = supported


_LOCK_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}


def _path_lock(path: Path) -> threading.RLock:
    key = os.path.abspath(os.fspath(path))
    with _LOCK_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def backup_path(path: Path, index: int) -> Path:
    return path.with_name(path.name + f'.bak{index}')


def _parse_object(path: Path, max_version: int, validator: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    raw = path.read_text(encoding='utf-8')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('JSON root must be an object')
    try:
        version = int(data.get('version', 1))
    except (TypeError, ValueError) as exc:
        raise ValueError('schema version must be an integer') from exc
    if version > max_version:
        raise FutureSchemaError(version, max_version)
    if validator:
        validator(data)
    return data


def _archive(path: Path, label: str) -> Path | None:
    if not path.exists():
        return None
    stamp = time.strftime('%Y%m%d-%H%M%S')
    candidate = path.with_name(f'{path.stem}.{label}-{stamp}{path.suffix}')
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f'{path.stem}.{label}-{stamp}-{counter}{path.suffix}')
        counter += 1
    try:
        path.replace(candidate)
        return candidate
    except OSError:
        try:
            shutil.copy2(path, candidate)
            path.unlink(missing_ok=True)
            return candidate
        except OSError:
            return None


def _sync_directory(path: Path) -> None:
    """Best-effort directory fsync so a completed rename survives abrupt shutdown."""
    try:
        flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
        fd = os.open(os.fspath(path), flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _path_lock(path):
        fd, raw_temp = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=os.fspath(path.parent))
        temp = Path(raw_temp)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
                handle.write(text)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            os.replace(temp, path)
            _sync_directory(path.parent)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, indent=2, ensure_ascii=False) + '\n'
    atomic_write_text(Path(path), encoded)


def rotate_valid_backups(path: Path, max_version: int, count: int = 3, validator: Callable[[dict[str, Any]], None] | None = None) -> bool:
    """Rotate only a parseable, supported, schema-valid current file into backups."""
    if count < 1 or not path.exists():
        return False
    try:
        _parse_object(path, max_version, validator)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    for index in range(count, 1, -1):
        older = backup_path(path, index - 1)
        newer = backup_path(path, index)
        if older.exists():
            try:
                shutil.copy2(older, newer)
            except OSError:
                pass
    try:
        shutil.copy2(path, backup_path(path, 1))
        return True
    except OSError:
        return False


def resilient_load_json(
    path: Path,
    max_version: int,
    *,
    label: str,
    backup_count: int = 3,
    validator: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any] | None, RecoveryNotice | None]:
    """Read a supported JSON object and recover from rotating backups when possible.

    Corrupt, structurally invalid, or future-version current files are preserved
    under timestamped names. A supported backup is copied back into the canonical
    path before returning.
    """
    path = Path(path)
    with _path_lock(path):
        if not path.exists():
            return None, None

        archived: Path | None = None
        problem = ''
        try:
            return _parse_object(path, max_version, validator), None
        except FutureSchemaError as exc:
            problem = str(exc)
            archived = _archive(path, f'future-v{exc.found}')
        except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
            problem = f'could not read current file: {exc}'
            archived = _archive(path, 'corrupt')

        for index in range(1, backup_count + 1):
            candidate = backup_path(path, index)
            if not candidate.exists():
                continue
            try:
                data = _parse_object(candidate, max_version, validator)
            except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError):
                continue
            try:
                atomic_write_json(path, data)
            except OSError:
                pass
            notice = RecoveryNotice(
                label,
                f'{label} recovered from backup {candidate.name}; {problem}',
                source=str(candidate),
                archived=str(archived) if archived else None,
            )
            return data, notice

        notice = RecoveryNotice(
            label,
            f'{label} could not be recovered; starting with safe defaults. {problem}',
            source=None,
            archived=str(archived) if archived else None,
        )
        return None, notice


def resilient_save_json(
    path: Path,
    payload: dict[str, Any],
    max_version: int,
    *,
    backup_count: int = 3,
    validator: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Back up a supported current file, then atomically replace it.

    The entire rotate-and-replace sequence is serialized per destination so worker
    threads cannot trample a shared temporary file or interleave backup generations.
    """
    path = Path(path)
    if validator:
        validator(payload)
    with _path_lock(path):
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(current, dict) and int(current.get('version', 1)) > max_version:
                    raise FutureSchemaError(int(current['version']), max_version)
            except FutureSchemaError:
                raise
            except Exception:
                # A corrupt current file is never promoted to a backup. A prior load
                # normally archives it; atomic replacement here is still safe.
                pass
        rotate_valid_backups(path, max_version, backup_count, validator)
        atomic_write_json(path, payload)
