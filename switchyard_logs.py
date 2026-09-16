from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from threading import RLock
from typing import Iterable
import json
import re
import time

from switchyard_persistence import atomic_write_text


@dataclass(frozen=True)
class LogEntry:
    timestamp: float
    service_id: str
    service_name: str
    project_name: str
    line: str
    level: str = 'INFO'


def infer_level(line: str) -> str:
    text = line.lower()
    if any(token in text for token in ('traceback', 'exception', 'fatal', ' error', 'error:', '[error]', ' failed', 'failure')):
        return 'ERROR'
    if any(token in text for token in ('warn', 'deprecated', 'retry', 'backoff')):
        return 'WARN'
    if any(token in text for token in ('ready', 'listening', 'started', 'success', 'passed')):
        return 'OK'
    return 'INFO'


class LogStore:
    """Thread-safe bounded log storage keyed by service.

    Runtime output is intentionally memory-bounded. This store keeps enough history
    for debugging without allowing a noisy development server to grow Switchyard
    indefinitely.
    """

    def __init__(self, max_entries: int = 12000, max_per_service: int = 5000):
        self.max_entries = max(100, int(max_entries))
        self.max_per_service = max(100, int(max_per_service))
        self._entries: list[LogEntry] = []
        self._lock = RLock()

    def add(self, service_id: str, service_name: str, project_name: str, line: str, timestamp: float | None = None) -> LogEntry:
        entry = LogEntry(timestamp or time.time(), service_id, service_name, project_name, line, infer_level(line))
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self.max_entries:
                del self._entries[: max(1, len(self._entries) - self.max_entries)]
            indexes = [i for i, item in enumerate(self._entries) if item.service_id == service_id]
            overflow = len(indexes) - self.max_per_service
            if overflow > 0:
                drop = set(indexes[:overflow])
                self._entries = [item for i, item in enumerate(self._entries) if i not in drop]
        return entry

    def query(self, service_id: str | None = None, text: str = '', levels: Iterable[str] | None = None, limit: int | None = None) -> list[LogEntry]:
        wanted_levels = {value.upper() for value in levels} if levels else None
        needle = text.casefold().strip()
        with self._lock:
            rows = [
                item for item in self._entries
                if (not service_id or item.service_id == service_id)
                and (not wanted_levels or item.level in wanted_levels)
                and (not needle or needle in item.line.casefold() or needle in item.service_name.casefold() or needle in item.project_name.casefold())
            ]
        if limit is not None:
            return rows[-max(0, int(limit)):]
        return rows

    def clear(self, service_id: str | None = None) -> None:
        with self._lock:
            if service_id:
                self._entries = [item for item in self._entries if item.service_id != service_id]
            else:
                self._entries.clear()

    def service_ids(self) -> list[str]:
        with self._lock:
            return list(dict.fromkeys(item.service_id for item in self._entries))

    def export_text(self, path: str | Path, service_id: str | None = None, text: str = '', levels: Iterable[str] | None = None) -> Path:
        output = Path(path)
        rows = self.query(service_id, text, levels)
        rendered = []
        for item in rows:
            stamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(item.timestamp))
            rendered.append(f'[{stamp}] [{item.level}] [{item.project_name}/{item.service_name}] {item.line}')
        atomic_write_text(output, '\n'.join(rendered) + ('\n' if rendered else ''))
        return output

    def export_json(self, path: str | Path, service_id: str | None = None) -> Path:
        output = Path(path)
        rendered = json.dumps([asdict(row) for row in self.query(service_id)], indent=2, ensure_ascii=False) + '\n'
        atomic_write_text(output, rendered)
        return output
