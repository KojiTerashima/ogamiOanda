"""Check maintained links and source-reference coverage without importing trading code."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'\[[^\]\n]+\]\(([^\s)]+)\)')


def check_documents(root: Path) -> list[str]:
    """Check local Markdown targets and exact file/symbol coverage of src."""
    errors = []
    documents = [
        root / 'README.md',
        *sorted((root / 'docs').rglob('*.md')),
        *sorted((root / 'src').rglob('README.md')),
    ]
    for document in documents:
        if not document.is_file():
            errors.append(f'missing document: {document.relative_to(root)}')
            continue
        for target in LINK.findall(document.read_text(encoding='utf-8')):
            parts = urlsplit(target)
            if parts.scheme or not parts.path:
                continue
            path = (document.parent / unquote(parts.path)).resolve()
            if not path.exists():
                errors.append(f'{document.relative_to(root)}: missing link target {target}')
    source = root / 'src' / 'ogami_oanda'
    reference = root / 'docs' / 'reference'
    expected = set()
    actual = set()
    for page in reference.glob('*.md'):
        for label, path, line in re.findall(
            r'\[`([^`]+)`\]\(../../src/ogami_oanda/([^#)]+)#L(\d+)\)',
            page.read_text(encoding='utf-8'),
        ):
            actual.add((path, label, int(line)))
    for path in sorted(source.rglob('*')):
        if path.suffix not in {'.py', '.yaml'}:
            continue
        relative = path.relative_to(source).as_posix()
        page = reference / ('README.md' if path.parent == source else f'{relative.split("/")[0]}.md')
        if not page.exists():
            errors.append(f'missing reference page: {page.relative_to(root)}')
            continue
        text = page.read_text(encoding='utf-8')
        if f'../../src/ogami_oanda/{relative})' not in text:
            errors.append(f'missing file reference: {relative}')
        if path.suffix != '.py':
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=relative)
        for node in tree.body:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            expected.add((relative, node.name, node.lineno))
            if isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        expected.add((relative, f'{node.name}.{method.name}', method.lineno))
    for item in sorted(expected - actual):
        errors.append(f'missing or stale definition reference: {item}')
    for item in sorted(actual - expected):
        errors.append(f'obsolete definition reference: {item}')
    return errors


def check_archives(root: Path) -> list[str]:
    """Opt-in: verify bundle/member hashes and paths without extracting anything."""
    errors = []
    archive_root = root / 'archive' / 'retired'
    manifest = json.loads((archive_root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['schema_version'] != 1:
        return ['unsupported archive manifest version']
    seen_paths = set()
    for bundle in manifest['bundles']:
        name = bundle['file']
        if PurePosixPath(name).name != name:
            errors.append('bundle filename must be a basename')
            continue
        path = archive_root / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != bundle['sha256']:
            errors.append(f'bundle hash mismatch: {name}')
            continue
        records = {record['member_path']: record for record in bundle['files']}
        if len(records) != len(bundle['files']):
            errors.append(f'duplicate manifest members: {name}')
        with tarfile.open(path, 'r:gz') as archive:
            members = archive.getmembers()
            if len(members) != len(records) or {m.name for m in members} != set(records):
                errors.append(f'member list mismatch: {name}')
                continue
            for member in members:
                record = records[member.name]
                member_path = PurePosixPath(member.name)
                if not member.isfile() or member_path.is_absolute() or '..' in member_path.parts:
                    errors.append(f'unsafe archive member: {member.name}')
                    continue
                if member.name in seen_paths:
                    errors.append(f'duplicate original path: {member.name}')
                seen_paths.add(member.name)
                if record['original_path'] != member.name:
                    errors.append(f'original path mismatch: {member.name}')
                with archive.extractfile(member) as stream:
                    data = stream.read()
                digest = hashlib.sha256(data).hexdigest()
                if digest != record['sha256'] or len(data) != record['size'] or member.mode != record['mode']:
                    errors.append(f'member integrity mismatch: {member.name}')
                if not record['redactions'] and digest != record['original_sha256']:
                    errors.append(f'unchanged original hash mismatch: {member.name}')
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archives', action='store_true', help='also verify retired bundles (no extraction)')
    args = parser.parse_args(argv)
    errors = check_documents(ROOT)
    if args.archives:
        errors.extend(check_archives(ROOT))
    if errors:
        print('\n'.join(errors))
        return 1
    print('Documentation links and source coverage: OK')
    if args.archives:
        print('Archive paths, modes and SHA-256 integrity: OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
