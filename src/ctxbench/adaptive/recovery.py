"""Durable, versioned research records outside canonical benchmark schemas."""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from ctxbench.adapters.repoqa.study import digest


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def atomic_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write(path: Path, value):
    atomic_text(path, json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n')


def sealed_write(path: Path, payload):
    write(path, {'schemaVersion': 1, 'digest': digest(payload), 'payload': payload})


def sealed_read(path: Path):
    envelope = read(path)
    if set(envelope) != {'schemaVersion', 'digest', 'payload'} or envelope['schemaVersion'] != 1:
        raise ValueError(f'invalid recovery envelope: {path}')
    if envelope['digest'] != digest(envelope['payload']):
        raise ValueError(f'corrupt recovery packet: {path}')
    return envelope['payload']


@contextmanager
def episode_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.episode.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('episode directory has an active writer') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def project_rows(path: Path, expected: list[dict]):
    """Only missing projections may be repaired; conflicting/duplicate rows fail."""
    if path.exists():
        existing = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if existing == expected:
            return
        cursor = 0
        for row in existing:
            while cursor < len(expected) and expected[cursor] != row:
                cursor += 1
            if cursor == len(expected):
                raise ValueError(f'conflicting or duplicate projection: {path}')
            cursor += 1
    atomic_text(path, ''.join(json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n'
                             for row in expected))


def project_json(path: Path, expected):
    if path.exists():
        if read(path) != expected:
            raise ValueError(f'conflicting projection: {path}')
        return
    write(path, expected)
