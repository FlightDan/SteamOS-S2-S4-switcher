"""Tests operate only on a temporary directory; daemon-reload is mocked."""
import importlib.util
import os
import sys
import types
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('install_test', Path(__file__).with_name('install.py'))
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = self.root / 'source.py'
        self.src.write_bytes(b'original runtime')
        for obj, name, value in [(install, 'ROOT', self.root), (install, 'SOURCE', self.src),
                                 (install, 'safe_dirs', lambda _: None),
                                 (install, 'trusted', lambda _: None)]:
            patcher = patch.object(obj, name, value); patcher.start(); self.addCleanup(patcher.stop)
        if os.name != 'posix':
            patcher = patch.dict(sys.modules, {'fcntl': types.SimpleNamespace(LOCK_EX=1, LOCK_NB=2, LOCK_UN=4, flock=lambda *_: None)})
            patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(install.os, 'geteuid', lambda: 0, create=True); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(install, 'reload_systemd'); self.reload = patcher.start(); self.addCleanup(patcher.stop)

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return path

    def test_activate_remove_retains_policy_and_only_reloads(self):
        policy = self.put('var/lib/boiler-sleep/sleep-policy.json', b'preference')
        install.change('activate')
        self.assertEqual((self.root / install.RUNTIME).read_bytes(), b'original runtime')
        self.assertEqual((self.root / install.ROUTER).read_bytes(), install.ROUTER_BYTES)
        install.change('remove')
        self.assertFalse((self.root / install.RUNTIME).exists())
        self.assertFalse((self.root / install.ROUTER).exists())
        self.assertEqual(policy.read_bytes(), b'preference')
        self.assertEqual(self.reload.call_count, 2)

    def test_legacy_router_and_alternate_override_block_activation(self):
        legacy = self.put(install.LEGACY, b'legacy')
        with self.assertRaisesRegex(RuntimeError, 'Legacy'):
            install.change('activate')
        legacy.unlink()
        other = self.put('run/systemd/system/systemd-suspend.service.d/other.conf', b'[Service]\nExecStart=/other\n')
        with self.assertRaisesRegex(RuntimeError, 'override'):
            install.change('activate')
        self.assertEqual(other.read_bytes(), b'[Service]\nExecStart=/other\n')
        self.assertFalse((self.root / install.RUNTIME).exists())

    def test_local_full_unit_override_blocks_activation(self):
        unit = self.put('etc/systemd/system/systemd-suspend.service', b'[Service]\nExecStart=/other\n')
        with self.assertRaisesRegex(RuntimeError, 'override or mask'): install.change('activate')
        self.assertTrue(unit.exists())
        self.assertFalse((self.root / install.RUNTIME).exists())

    def test_changed_files_never_overwritten_or_removed(self):
        runtime = self.put(install.RUNTIME, b'changed')
        for action in ('activate', 'remove'):
            with self.assertRaisesRegex(RuntimeError, 'differs'):
                install.change(action)
        self.assertEqual(runtime.read_bytes(), b'changed')

    def test_remove_refuses_retained_swap_state(self):
        install.change('activate')
        self.put('home/.boiler-s2s4/swap-state.json', b'owned')
        with self.assertRaisesRegex(RuntimeError, 'Disable S4'):
            install.change('remove')
        self.assertTrue((self.root / install.RUNTIME).exists())
        self.assertTrue((self.root / install.ROUTER).exists())

    def test_activation_reload_failure_rolls_back_both_files(self):
        self.reload.side_effect = [RuntimeError('reload failed'), None]
        with self.assertRaisesRegex(RuntimeError, 'reload failed'):
            install.change('activate')
        self.assertFalse((self.root / install.ROUTER).exists())
        self.assertFalse((self.root / install.RUNTIME).exists())

    def test_removal_reload_failure_restores_both_files(self):
        install.change('activate')
        self.reload.side_effect = [RuntimeError('reload failed'), None]
        with self.assertRaisesRegex(RuntimeError, 'reload failed'):
            install.change('remove')
        self.assertEqual((self.root / install.ROUTER).read_bytes(), install.ROUTER_BYTES)
        self.assertEqual((self.root / install.RUNTIME).read_bytes(), b'original runtime')

if __name__ == '__main__': unittest.main()
