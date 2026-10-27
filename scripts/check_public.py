"""Check distributable files; print paths and finding types, never matched values."""
from pathlib import Path
import hashlib
import json
import re
import sys
ROOT = Path(__file__).resolve().parents[1]
rules = {
    'local_home': re.compile(rb'/(?:Users|home)/[A-Za-z0-9_.-]+/'),
    'private_key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'provider_token': re.compile(rb'(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,})'),
    'physical_mac': re.compile(rb'(?<![0-9A-Fa-f:])(?!(?:02:00:00:00:00:0[123]))(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}(?![0-9A-Fa-f:])'),
}
forbidden = {'.bin','.elf','.ogg','.mp3','.wav','.aiff','.png','.jpg','.jpeg','.sqlite','.db','.log'}
findings, count, actual_hashes = [], 0, {}
for p in ROOT.rglob('*'):
    rel = p.relative_to(ROOT)
    if any(x in {'.git','.build','.venv','__pycache__','.pytest_cache'} for x in rel.parts): continue
    if p.is_symlink(): findings.append((str(rel),'symlink')); continue
    if not p.is_file(): continue
    count += 1
    if 'private' in rel.parts or 'runtime' in rel.parts or p.suffix.lower() in forbidden:
        findings.append((str(rel),'private_or_binary_file'))
    data = p.read_bytes()
    if str(rel) != 'source-manifest.json':
        actual_hashes[rel.as_posix()] = hashlib.sha256(data).hexdigest()
    try: data.decode('utf-8')
    except UnicodeDecodeError: findings.append((str(rel),'non_text_payload'))
    for kind, rule in rules.items():
        if rule.search(data): findings.append((str(rel),kind))
try:
    expected = json.loads((ROOT / 'source-manifest.json').read_text())['files']
    if not isinstance(expected, dict): raise ValueError('Invalid manifest')
    for name in sorted(set(expected) | set(actual_hashes)):
        if expected.get(name) != actual_hashes.get(name): findings.append((name, 'manifest_mismatch'))
except (OSError, ValueError, KeyError):
    findings.append(('source-manifest.json', 'invalid_manifest'))
for path, kind in findings: print(f'{path}: {kind}')
print(f'Checked {count} distributable files; findings={len(findings)}')
sys.exit(bool(findings))
