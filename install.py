"""Explicit root-only installation of the systemd hook; never starts a service."""
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path('/')
SOURCE = Path(__file__).resolve().with_name('sleep_control.py')
RUNTIME = 'var/lib/boiler-sleep/sleep_control.py'
ROUTER = 'etc/systemd/system/systemd-suspend.service.d/90-boiler-sleep.conf'
LEGACY = 'etc/systemd/system/systemd-suspend.service.d/90-oxp3-battery.conf'
ROUTER_BYTES = b'''# Boiler Sleep: route the existing suspend request.\n[Service]\nExecStart=\nExecStart=/usr/bin/python3 -I -B /var/lib/boiler-sleep/sleep_control.py run\n'''


def target(name):
    return ROOT / name


def trusted(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError(f'Untrusted file: {path}')


def safe_dirs(directory):
    # Existing directories must not permit unprivileged replacement of files.
    for current in (directory, *directory.parents):
        if current.exists():
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise RuntimeError(f'Untrusted directory: {current}')


def existing(path, expected):
    if not os.path.lexists(path):
        return False
    trusted(path)
    if path.read_bytes() != expected:
        raise RuntimeError(f'File differs from this release: {path}')
    return True


def conflicts():
    if os.path.lexists(target(LEGACY)):
        raise RuntimeError('Legacy Battery sleep router is present; remove its integration first')
    for base in ('etc/systemd/system', 'run/systemd/system', 'usr/local/lib/systemd/system'):
        if os.path.lexists(target(f'{base}/systemd-suspend.service')):
            raise RuntimeError('A local systemd-suspend.service override or mask exists')
    for base in ('etc/systemd/system', 'run/systemd/system', 'usr/local/lib/systemd/system', 'usr/lib/systemd/system', 'lib/systemd/system'):
        for name in ('service.d', 'systemd-.service.d', 'systemd-suspend.service.d'):
            directory = target(f'{base}/{name}')
            if not directory.is_dir():
                continue
            for item in directory.glob('*.conf'):
                if item == target(ROUTER):
                    continue
                if re.search(r'^\s*ExecStart\s*=', item.read_text(encoding='utf-8'), re.M):
                    raise RuntimeError(f'Another suspend ExecStart override exists: {item}')


def write_new(path, data):
    safe_dirs(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_dirs(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o644)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)


def reload_systemd():
    subprocess.run(['/usr/bin/systemctl', 'daemon-reload'], check=True)


def change(action):
    if os.geteuid() != 0:
        raise RuntimeError('Run as root')
    import fcntl
    lock = target('run/lock/boiler-sleep.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or (os.name == 'posix' and (info.st_uid != 0 or info.st_mode & 0o077)):
            raise RuntimeError('Untrusted sleep lock')
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('A sleep operation or settings change is in progress') from error
        try:
            return change_locked(action)
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def change_locked(action):
    trusted(SOURCE)
    source = SOURCE.read_bytes()
    runtime, router = target(RUNTIME), target(ROUTER)
    for item in (runtime, router):
        safe_dirs(item.parent)
    have_runtime = existing(runtime, source)
    have_router = existing(router, ROUTER_BYTES)
    if action == 'activate':
        conflicts()
        if have_runtime != have_router:
            raise RuntimeError('Incomplete integration; inspect files before proceeding')
        if have_runtime:
            return 'Already active'
        created = []
        try:
            for item, data in ((runtime, source), (router, ROUTER_BYTES)):
                write_new(item, data)
                created.append(item)
            reload_systemd()
        except Exception:
            for item in reversed(created):
                item.unlink()
            try:
                reload_systemd()
            except Exception:
                pass
            raise
        return 'Activated; no sleep operation was started'
    if action == 'remove':
        if os.path.lexists(target('home/.boiler-s2s4/swap-state.json')):
            raise RuntimeError('Disable S4 and clean its owned swap before removing integration')
        if have_runtime != have_router:
            raise RuntimeError('Incomplete integration; inspect files before proceeding')
        if os.path.lexists(target('home/.boiler-s2s4/deadline-efi.json')):
            # SOURCE is already verified above. The caller holds the shared lock.
            import importlib.util
            spec = importlib.util.spec_from_file_location('boiler_sleep_cleanup', SOURCE)
            sleep = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sleep)
            sleep.ROOT = ROOT
            sleep.deadline_remove()
        if not have_runtime:
            return 'Already removed; preference retained'
        removed = []
        try:
            for item, data in ((router, ROUTER_BYTES), (runtime, source)):
                item.unlink()
                removed.append((item, data))
            reload_systemd()
        except Exception:
            for item, data in reversed(removed):
                write_new(item, data)
            try:
                reload_systemd()
            except Exception:
                pass
            raise
        return 'Removed; preference retained for reinstall'
    raise ValueError('Use activate or remove')


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('activate', 'remove'):
        raise SystemExit('Usage: sudo python3 install.py activate|remove')
    try:
        print(change(sys.argv[1]))
    except Exception as error:
        raise SystemExit(str(error))
