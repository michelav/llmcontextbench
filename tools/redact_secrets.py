"""Replace credential values persisted in study artifacts by [REDACTED].

Usage:
    python tools/redact_secrets.py --values-file SECRETS.txt studies outputs           # dry run: list files
    python tools/redact_secrets.py --values-file SECRETS.txt studies outputs --apply   # rewrite in place
    python tools/redact_secrets.py --env REPOQA_MCP_TOKEN studies --apply

The values come from a file (one per line) or from environment variables, never from the command line, and
are never printed. Plain files, .gz streams and .tar.gz/.tgz archives are rewritten; modification times are
kept. Only the matched values change, so trial records stay byte-identical elsewhere.
"""
import argparse
import gzip
import io
import os
import sys
import tarfile
from pathlib import Path

REDACTED = b'[REDACTED]'


def redact(data, secrets):
    for secret in secrets:
        data = data.replace(secret, REDACTED)
    return data


def rewrite_tar(path, secrets, apply):
    with tarfile.open(path, 'r:gz') as archive:
        members = [(m, archive.extractfile(m).read() if m.isfile() else None) for m in archive.getmembers()]
    if not any(data is not None and any(s in data for s in secrets) for _, data in members):
        return False
    if apply:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            for member, data in members:
                if data is None:
                    archive.addfile(member)
                else:
                    data = redact(data, secrets)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
        path.write_bytes(buffer.getvalue())
    return True


def rewrite(path, secrets, apply):
    if path.name.endswith(('.tar.gz', '.tgz')):
        return rewrite_tar(path, secrets, apply)
    raw = path.read_bytes()
    compressed = path.suffix == '.gz'
    data = gzip.decompress(raw) if compressed else raw
    if not any(s in data for s in secrets):
        return False
    if apply:
        data = redact(data, secrets)
        path.write_bytes(gzip.compress(data) if compressed else data)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('paths', nargs='+', type=Path)
    parser.add_argument('--values-file', type=Path)
    parser.add_argument('--env', action='append', default=[])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    values = [line.strip() for line in args.values_file.read_text().splitlines()] if args.values_file else []
    values += [os.environ[name] for name in args.env if os.environ.get(name)]
    secrets = sorted({v.encode() for v in values if len(v) >= 8}, key=len, reverse=True)
    if not secrets:
        sys.exit('no secret values (each must have at least 8 characters)')
    files = [p for root in args.paths for p in ([root] if root.is_file() else sorted(root.rglob('*'))) if p.is_file()]
    changed = 0
    for path in files:
        try:
            stat = path.stat()
            if rewrite(path, secrets, args.apply):
                changed += 1
                print(path)
                if args.apply:
                    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        except (OSError, EOFError, gzip.BadGzipFile, tarfile.TarError) as error:
            print(f'skipped {path}: {type(error).__name__}', file=sys.stderr)
    print(f'{"redacted" if args.apply else "would redact"} {changed} of {len(files)} files', file=sys.stderr)


if __name__ == '__main__':
    main()
