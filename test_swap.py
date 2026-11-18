"""Dedicated swap lifecycle tests: all commands and kernel paths are mocked."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('swap_test', Path(__file__).with_name('sleep_control.py'))
sleep = importlib.util.module_from_spec(spec); spec.loader.exec_module(sleep)

class SwapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.active = False; self.commands = []
        self.patch(sleep, 'ROOT', self.root)
        self.patch(sleep, 'owned_directory', lambda missing_ok=False: (self.root/sleep.SWAP_DIR).exists())
        self.patch(sleep, 'filesystem_uuid', lambda: 'test-uuid')
        self.patch(sleep, 'owned_swap', lambda state, missing_ok=False: (self.root/sleep.SWAP_FILE).exists())
        self.patch(sleep, 'swap_location', lambda: ('8:1', 99))
        self.patch(sleep, 'swap_active', lambda: self.active)
        self.patch(sleep, 'active_swaps', lambda: [('/dev/zram0','partition')] + ([(str(self.root/sleep.SWAP_FILE),'file')] if self.active else []))
        self.patch(sleep, 'available_modes', lambda: ['system','s2idle','hibernate','auto'])
        self.patch(sleep, 'required_swap_bytes', lambda: 1024*1024)
        self.patch(sleep.os, 'sysconf', lambda _: 4096, create=True)
        self.patch(sleep.os, 'statvfs', lambda _: types.SimpleNamespace(f_bavail=10000, f_frsize=1024*1024), create=True)
        self.patch(sleep.subprocess, 'run', self.command)
        if os.name != 'posix':
            p = patch.dict(sys.modules, {'fcntl': types.SimpleNamespace(LOCK_EX=1,LOCK_NB=2,LOCK_UN=4,flock=lambda *_:None)})
            p.start(); self.addCleanup(p.stop)
        (self.root/'home').mkdir()
        (self.root/'sys/firmware/efi/efivars').mkdir(parents=True)
        self.write('sys/power/resume', '0:0'); self.write('sys/power/resume_offset', '0')
        self.write('sys/power/mem_sleep', 's2idle [deep]')
        self.status_patch = patch.object(sleep, 'status', return_value={'router_installed':True,'available_modes':['system','s2idle','hibernate','auto'],'delay_minutes':120,'mode':'system'})
        self.status_patch.start(); self.addCleanup(self.status_patch.stop)

    def patch(self, obj, name, value, **kwargs):
        p=patch.object(obj,name,value,**kwargs); p.start(); self.addCleanup(p.stop)
    def write(self, name, text):
        target=self.root/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text); return target
    def command(self, args, **kwargs):
        self.commands.append(args)
        name=Path(args[0]).name
        if name == 'mkswap':
            with (self.root/sleep.SWAP_FILE).open('wb') as f: f.write(bytes(4096-10)+b'SWAPSPACE2')
        if name == 'swapon': self.active=True
        if name == 'swapoff': self.active=False
        if name == 'systemd-sleep' and args[-1] != 'suspend':
            assert (self.root/'sys/power/resume').read_text().strip() == '0:0'
            assert (self.root/'sys/power/resume_offset').read_text().strip() == '0'
            self.write('sys/power/resume', '8:1'); self.write('sys/power/resume_offset', '99')
        return subprocess.CompletedProcess(args,0,stdout='')

    def test_enable_run_disable_preserves_file_until_disabled(self):
        sleep.set_enabled(True)
        file=self.root/sleep.SWAP_FILE
        self.assertTrue(file.exists()); self.assertFalse(self.active)
        self.assertTrue(sleep.read_swap_state()['enabled'])
        self.commands.clear(); sleep.run()
        self.assertEqual([Path(x[0]).name for x in self.commands], ['swapon','systemd-sleep','swapoff'])
        self.assertEqual(self.commands[1][-1], 'suspend-then-hibernate')
        self.assertEqual((self.root/'sys/power/resume').read_text().strip(),'0:0')
        self.assertEqual((self.root/'sys/power/resume_offset').read_text().strip(),'0')
        self.assertTrue(file.exists()); self.assertFalse(self.active)
        sleep.set_enabled(False)
        self.assertFalse(file.exists()); self.assertFalse((self.root/sleep.STATE).exists())

    def test_pending_image_never_activated_or_deleted(self):
        sleep.set_enabled(True)
        file=self.root/sleep.SWAP_FILE
        with file.open('r+b') as stream: stream.seek(4096-10); stream.write(b'S1SUSPEND\x00')
        self.commands.clear(); sleep.run()
        self.assertEqual([Path(x[0]).name for x in self.commands], ['systemd-sleep'])
        self.assertEqual(self.commands[0][-1], 'suspend')
        with self.assertRaisesRegex(RuntimeError,'pending S4 image'): sleep.set_enabled(False)
        self.assertTrue(file.exists())

    def test_disable_swapoff_failure_keeps_state_and_file(self):
        sleep.set_enabled(True); self.active=True
        original=self.command
        def fail(args, **kwargs):
            if Path(args[0]).name=='swapoff': raise subprocess.CalledProcessError(1,args)
            return original(args,**kwargs)
        with patch.object(sleep.subprocess,'run',side_effect=fail):
            with self.assertRaises(subprocess.CalledProcessError): sleep.set_enabled(False)
        self.assertTrue((self.root/sleep.SWAP_FILE).exists())
        self.assertTrue(sleep.read_swap_state()['enabled'])

    def test_pending_image_after_sleep_keeps_swap_and_resume_parameters(self):
        sleep.set_enabled(True)
        original=self.command
        def pending(args, **kwargs):
            result=original(args,**kwargs)
            if Path(args[0]).name == 'systemd-sleep':
                with (self.root/sleep.SWAP_FILE).open('r+b') as stream:
                    stream.seek(4096-10); stream.write(b'S1SUSPEND\x00')
            return result
        self.commands.clear()
        with patch.object(sleep.subprocess,'run',side_effect=pending):
            with self.assertRaisesRegex(RuntimeError, 'pending S4 image'): sleep.run()
        self.assertTrue(self.active)
        self.assertEqual((self.root/'sys/power/resume').read_text().strip(), '8:1')
        self.assertEqual((self.root/'sys/power/resume_offset').read_text().strip(), '99')
        self.assertNotIn('swapoff', [Path(args[0]).name for args in self.commands])
        self.assertFalse((self.root/sleep.RUNTIME).exists())

    def test_new_foreign_swap_after_activation_cleans_up_then_suspends(self):
        sleep.set_enabled(True)
        def entries():
            result = [('/dev/zram0', 'partition')]
            if self.active:
                result += [(str(self.root/sleep.SWAP_FILE), 'file'), ('/dev/sda2', 'partition')]
            return result
        self.commands.clear()
        with patch.object(sleep, 'active_swaps', side_effect=entries): sleep.run()
        self.assertEqual([Path(args[0]).name for args in self.commands], ['swapon','swapoff','systemd-sleep'])
        self.assertEqual(self.commands[-1][-1], 'suspend')
        self.assertFalse(self.active)

    def test_pending_efi_marker_blocks_cleanup(self):
        sleep.set_enabled(True)
        self.write('sys/firmware/efi/efivars/HibernateLocation-pending', 'pending')
        with self.assertRaisesRegex(RuntimeError, 'HibernateLocation'): sleep.set_enabled(False)
        self.assertTrue((self.root/sleep.SWAP_FILE).exists())
        self.assertTrue(sleep.read_swap_state()['enabled'])

    def test_cleanup_retry_after_file_unlink(self):
        sleep.set_enabled(True)
        original=Path.unlink
        def fail_once(target, *args, **kwargs):
            if target == self.root/sleep.STATE: raise OSError('state unlink failed')
            return original(target, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_once):
            with self.assertRaisesRegex(OSError, 'state unlink failed'): sleep.set_enabled(False)
        self.assertFalse((self.root/sleep.SWAP_FILE).exists())
        self.assertEqual(sleep.read_swap_state()['phase'], 'cleaning')
        self.patch(sleep, 'filesystem_type', lambda: 'ext4')
        sleep.set_enabled(False)
        self.assertFalse((self.root/sleep.STATE).exists())

    def test_failed_allocation_leaves_recoverable_owned_state(self):
        original=self.command
        def fail(args, **kwargs):
            if Path(args[0]).name=='dd': raise subprocess.CalledProcessError(1,args)
            return original(args,**kwargs)
        with patch.object(sleep.subprocess,'run',side_effect=fail):
            with self.assertRaises(subprocess.CalledProcessError): sleep.set_enabled(True)
        self.assertEqual(sleep.read_swap_state()['phase'],'creating')
        sleep.set_enabled(False)
        self.assertFalse((self.root/sleep.STATE).exists())

if __name__=='__main__': unittest.main()
