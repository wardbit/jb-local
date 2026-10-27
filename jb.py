#!/usr/bin/env python3
"""Offline JetBrains configuration installer. Python 3.9+, standard library only."""

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import sys
import tempfile
import uuid

PRODUCTS = {
    'intellijidea': 'idea', 'ideaic': 'idea', 'idea': 'idea',
    'pycharm': 'pycharm', 'clion': 'clion', 'phpstorm': 'phpstorm',
    'goland': 'goland', 'webstorm': 'webstorm', 'rider': 'rider',
    'datagrip': 'datagrip', 'rubymine': 'rubymine', 'appcode': 'appcode',
    'dataspell': 'dataspell', 'dotmemory': 'dotmemory', 'rustrover': 'rustrover',
}
OPENS = (
    '--add-opens=java.base/jdk.internal.org.objectweb.asm=ALL-UNNAMED',
    '--add-opens=java.base/jdk.internal.org.objectweb.asm.tree=ALL-UNNAMED',
)
REQUIRED = {'ja-netfilter.jar', 'license.key'} | {
    'plugins/' + name + '.jar' for name in ('dns', 'native', 'power', 'url', 'hideme', 'privacy')
} | {'config/' + name + '.conf' for name in ('dns', 'native', 'power', 'url')}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(path):
    """Refuse redirects and special files before reading or replacing a target."""
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError(f'Refusing symlink/junction: {item}')
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError(f'Refusing special file: {item}')
    return path


def read_optional(path):
    path = safe_path(path)
    return path.read_bytes() if path.exists() else None


def load_bundle(project):
    manifest_bytes = safe_path(project / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    files = manifest.get('files', {})
    if manifest.get('schema') != 1 or set(files) != REQUIRED:
        raise ValueError('Unexpected manifest schema or resource list')
    vendor = safe_path(project / 'vendor')
    actual = set()
    for directory, dirs, names in os.walk(vendor, followlinks=False):
        for name in dirs + names:
            safe_path(Path(directory) / name)
        actual.update((Path(directory) / name).relative_to(vendor).as_posix() for name in names)
    if actual != REQUIRED:
        raise ValueError('Missing or unlisted files in vendor/')
    payload = {}
    for name, entry in files.items():
        # The fixed allowlist also excludes traversal and platform-specific paths.
        data = safe_path(vendor / name).read_bytes()
        if len(data) != entry['size'] or digest(data) != entry['sha256']:
            raise ValueError(f'Resource integrity check failed: {name}')
        payload[name] = data
    return payload, digest(manifest_bytes)


def platform_roots(system, home, env):
    if system == 'Windows':
        return (Path(env.get('APPDATA', home / 'AppData/Roaming')) / 'JetBrains',
                Path(env.get('LOCALAPPDATA', home / 'AppData/Local')) / 'JetBrains')
    if system == 'Darwin':
        return home / 'Library/Application Support/JetBrains', home / 'Library/Caches/JetBrains'
    if system == 'Linux':
        return (Path(env.get('XDG_CONFIG_HOME', home / '.config')) / 'JetBrains',
                Path(env.get('XDG_CACHE_HOME', home / '.cache')) / 'JetBrains')
    raise ValueError(f'Unsupported operating system: {system}')


def product_name(name):
    for prefix, product in PRODUCTS.items():
        if re.match(re.escape(prefix) + r'(?:ce)?\d', name.lower()):
            return product
    return None


@dataclass
class Target:
    product: str
    config: Path
    vm: Path
    seed: bytes
    original: object


def make_target(config, system, product=None, ide_home=None, vmoptions=None, env=None):
    config = safe_path(config)
    if not config.is_dir():
        raise ValueError(f'Config directory does not exist: {config}')
    product = product or product_name(config.name)
    if product not in PRODUCTS.values():
        raise ValueError(f'Unknown product: {config.name}; supply --product')
    suffix = {'Windows': '64.exe.vmoptions', 'Linux': '64.vmoptions', 'Darwin': '.vmoptions'}[system]
    name = product + suffix
    vm = safe_path(vmoptions if vmoptions is not None else config / name)
    env = os.environ if env is None else env
    override = env.get(product.upper() + '_VM_OPTIONS')
    if override and safe_path(Path(override).expanduser()) != vm:
        raise ValueError(f'{product.upper()}_VM_OPTIONS overrides this file; use --config-dir and --vmoptions {override}')
    seed = read_optional(vm)
    original = seed
    if seed is None:
        if vmoptions is not None:
            raise ValueError(f'Explicit VM options file does not exist: {vm}')
        if ide_home is None:
            raise ValueError(f'No VM options/defaults for {config}; use Help > Edit Custom VM Options or --ide-home')
        ide_home = safe_path(ide_home)
        candidates = [ide_home / 'bin' / name, ide_home / 'Contents/bin' / name]
        default = next((safe_path(p) for p in candidates if p.is_file()), None)
        if default is None:
            raise ValueError(f'Cannot locate distribution default {name} in {ide_home}')
        seed = default.read_bytes()
    return Target(product, config, vm, seed, original)


def discover(system, home, env=None):
    env = os.environ if env is None else env
    config_root, cache_root = platform_roots(system, home, env)
    if not config_root.is_dir():
        return []
    safe_path(config_root)
    targets = []
    for config in sorted(config_root.iterdir()):
        product = product_name(config.name)
        if not product or not config.is_dir():
            continue
        home_file = cache_root / config.name / '.home'
        ide_home = None
        if home_file.is_file():
            value = safe_path(home_file).read_text(encoding='utf-8-sig').strip()
            if value:
                ide_home = Path(value)
        try:
            targets.append(make_target(config, system, product, ide_home, None, env))
        except ValueError as exc:
            print(f'SKIP: {exc}', file=sys.stderr)
    return targets


def merge_options(data, jar):
    jar_text = jar.as_posix()
    if any(c in jar_text for c in '\r\n\x00="'):
        raise ValueError('Agent path contains a JVM option delimiter')
    encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    text = data.decode(encoding)
    newline = '\r\n' if '\r\n' in text else '\n'
    lines = []
    for line in text.splitlines():
        stripped = line.strip().strip('"')
        if stripped.startswith('-javaagent:') and re.search(r'(?:^|[/\\])ja-netfilter\.jar(?:[=" ]|$)', stripped, re.I):
            continue
        lines.append(line)
    for option in OPENS:
        if option not in {line.strip() for line in lines}:
            lines.append(option)
    lines.append('-javaagent:' + jar_text)
    return (newline.join(lines) + newline).encode('utf-8')


@dataclass
class Change:
    path: Path
    before: object
    after: object
    mode: int = 0o600
    persistent: bool = False


def make_plan(targets, project, state):
    if not targets:
        raise ValueError('No usable IDE found. Start the IDE once, or supply --config-dir / --ide-home.')
    payload, identity = load_bundle(project)
    state = safe_path(state)
    runtime = state / 'runtime' / identity
    changes = []
    seen = set()

    def add(path, after, persistent=False):
        path = safe_path(path)
        if path in seen:
            raise ValueError(f'Duplicate target: {path}')
        seen.add(path)
        before = read_optional(path)
        if persistent and before is not None and before != after:
            raise ValueError(f'Installed resource has changed: {path}')
        if before != after:
            mode = stat.S_IMODE(path.stat().st_mode) if before is not None else 0o600
            changes.append(Change(path, before, after, mode, persistent))

    if runtime.exists():
        for path in runtime.rglob('*'):
            safe_path(path)
            if path.is_file() and path.suffix in ('.jar', '.conf') and path.relative_to(runtime).as_posix() not in payload:
                raise ValueError(f'Unlisted installed plugin/config: {path}')
    for name, data in payload.items():
        if name != 'license.key':
            add(runtime / name, data, persistent=True)
    for target in targets:
        if read_optional(target.vm) != target.original:
            raise ValueError(f'VM options changed since discovery: {target.vm}')
        if target.vm == target.config / (target.product + '.key'):
            raise ValueError('VM options and license paths must differ')
        add(target.vm, merge_options(target.seed, runtime / 'ja-netfilter.jar'))
        add(target.config / (target.product + '.key'), payload['license.key'])
    return changes


def atomic_write(path, data, mode=None):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.jb-local-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode if mode is not None else 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def state_lock(state):
    state = safe_path(state)
    state.mkdir(parents=True, exist_ok=True)
    lock = safe_path(state / '.lock')
    try:
        stream = lock.open('x', encoding='ascii')
    except FileExistsError:
        raise ValueError(f'Another operation or stale lock: {lock}. If no installer is running, remove this lock and retry.') from None
    try:
        with stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def write_journal(folder, journal):
    atomic_write(folder / 'journal.json', (json.dumps(journal, indent=2) + '\n').encode())


def apply_plan(changes, state):
    if not changes:
        return None
    state = safe_path(state)
    with state_lock(state):
        for change in changes:
            if read_optional(change.path) != change.before:
                raise ValueError(f'File changed since preview: {change.path}')
        backup_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12]
        folder = safe_path(state / 'backups' / backup_id)
        folder.mkdir(parents=True)
        journal = {'schema': 1, 'status': 'prepared', 'files': []}
        for index, change in enumerate(changes):
            if change.persistent:
                continue  # Shared immutable payload survives restores of individual IDEs.
            backup_name = f'{index}.bin' if change.before is not None else None
            if backup_name:
                atomic_write(folder / backup_name, change.before)
            journal['files'].append({
                'path': str(change.path), 'backup': backup_name,
                'before': digest(change.before) if change.before is not None else None,
                'after': digest(change.after) if change.after is not None else None,
                'mode': change.mode,
            })
        write_journal(folder, journal)
        done = []
        try:
            for change in changes:
                if read_optional(change.path) != change.before:
                    raise ValueError(f'File changed during install: {change.path}')
                if change.after is None:
                    change.path.unlink()
                else:
                    atomic_write(change.path, change.after, change.mode)
                done.append(change)
            journal['status'] = 'applied'
            write_journal(folder, journal)
        except BaseException as exc:
            errors = []
            for change in reversed(done):
                if change.persistent:
                    continue
                try:
                    if read_optional(change.path) != change.after:
                        raise ValueError(f'Concurrent edit: {change.path}')
                    if change.before is None:
                        change.path.unlink(missing_ok=True)
                    else:
                        atomic_write(change.path, change.before, change.mode)
                except (OSError, ValueError) as rollback_error:
                    errors.append(str(rollback_error))
            journal['status'] = 'recovery-needed' if errors else 'rolled-back'
            journal['errors'] = errors
            write_journal(folder, journal)
            if errors:
                raise OSError(f'Incomplete rollback; backup {backup_id}: {errors}') from exc
            raise
        return backup_id


def restore(backup_id, state, apply=False):
    if not re.fullmatch(r'\d{8}T\d{6}Z-[0-9a-f]{12}', backup_id):
        raise ValueError('Invalid backup ID')
    folder = safe_path(state / 'backups' / backup_id)
    journal = json.loads(safe_path(folder / 'journal.json').read_text(encoding='utf-8'))
    if journal.get('schema') != 1:
        raise ValueError('Unsupported backup schema')
    changes = []
    seen = set()
    for entry in journal['files']:
        target = safe_path(entry['path'])
        if not Path(entry['path']).is_absolute() or target in seen:
            raise ValueError('Invalid/duplicate backup target')
        seen.add(target)
        backup_name = entry['backup']
        original = None
        if backup_name is not None:
            if not re.fullmatch(r'\d+\.bin', backup_name):
                raise ValueError('Invalid backup file name')
            original = safe_path(folder / backup_name).read_bytes()
            if digest(original) != entry['before']:
                raise ValueError(f'Backup integrity check failed: {backup_name}')
        elif entry['before'] is not None:
            raise ValueError('Missing backup file')
        current = read_optional(target)
        if current == original:
            continue
        if (digest(current) if current is not None else None) != entry['after']:
            raise ValueError(f'File edited after installation; refusing to overwrite: {target}')
        changes.append(Change(target, current, original, entry['mode']))
    show_plan(changes)
    if apply:
        return apply_plan(changes, state)
    return None


def show_plan(changes):
    if not changes:
        print('No changes needed.')
    for change in changes:
        action = 'DELETE' if change.after is None else 'CREATE' if change.before is None else 'UPDATE'
        print(f'{action}: {change.path}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=Path.home() / '.jb-local', help='Payload and backups directory')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('verify', help='Verify all bundled resource hashes; no writes')
    commands.add_parser('list', help='List usable standard IDE configurations')
    install = commands.add_parser('install', help='Preview configuration changes; --apply writes them')
    install.add_argument('--config-dir', type=Path, help='One explicit IDE configuration directory')
    install.add_argument('--product', choices=sorted(set(PRODUCTS.values())))
    install.add_argument('--ide-home', type=Path, help='Installation directory or macOS .app (read only)')
    install.add_argument('--vmoptions', type=Path, help='Explicit existing effective VM options file')
    install.add_argument('--apply', action='store_true')
    undo = commands.add_parser('restore', help='Preview restoring a previous backup')
    undo.add_argument('backup_id')
    undo.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    project = Path(__file__).resolve().parent
    state = Path(os.path.abspath(args.state_dir.expanduser()))
    if args.command == 'verify':
        payload, identity = load_bundle(project)
        print(f'Verified {len(payload)} files. Bundle: {identity}')
        print('Integrity only: privacy.jar publisher comparison and IDE activation are not verified.')
        return 0
    if args.command == 'restore':
        recovery = restore(args.backup_id, state, args.apply)
        if recovery:
            print(f'Restored. Recovery backup: {recovery}')
        elif not args.apply:
            print('Preview only. Add --apply to restore. Close IDEs first.')
        return 0
    system = platform.system()
    if args.command == 'install' and args.config_dir:
        targets = [make_target(args.config_dir.expanduser(), system, args.product, args.ide_home, args.vmoptions)]
    else:
        if args.command == 'install' and (args.product or args.ide_home or args.vmoptions):
            parser.error('--product, --ide-home and --vmoptions require --config-dir')
        targets = discover(system, Path.home())
    if args.command == 'list':
        for target in targets:
            print(f'{target.product}: {target.config}\n  VM: {target.vm}')
        if not targets:
            print('No usable IDE configurations found.')
        return 0
    plan = make_plan(targets, project, state)
    show_plan(plan)
    if args.apply:
        backup_id = apply_plan(plan, state)
        if backup_id:
            print(f'Configuration written. Backup: {backup_id}')
            print('Activation is NOT verified. Start the IDE and check its license screen.')
    else:
        print('Preview only. Close IDEs, then add --apply to install. No administrator/sudo required.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
