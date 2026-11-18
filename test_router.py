"""Router behavior tests use a temporary root and mocked commands only."""
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

spec = importlib.util.spec_from_file_location('sleep_test', Path(__file__).with_name('sleep_control.py'))
sleep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sleep)
version_impl = sleep.supported_systemd
mount_impl = sleep.filesystem_type

class RouterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'home').mkdir()
        p = patch.object(sleep, 'ROOT', self.root); p.start(); self.addCleanup(p.stop)
        if os.name != 'posix':
            p = patch.dict(sys.modules, {'fcntl': types.SimpleNamespace(LOCK_EX=1, LOCK_NB=2, LOCK_UN=4, flock=lambda *_: None)})
            p.start(); self.addCleanup(p.stop)
        self.commands = []
        p = patch.object(sleep.subprocess, 'run', side_effect=self.command); p.start(); self.addCleanup(p.stop)
        self.write('sys/power/state', 'freeze mem disk')
        self.write('sys/power/mem_sleep', 's2idle [deep]')
        self.write('sys/power/disk', '[platform] shutdown')
        self.write('sys/power/resume', '0:0')
        self.write('sys/power/resume_offset', '0')
        self.write(sleep.HELPER, '#!/bin/sh').chmod(0o755)
        self.write('usr/lib/initcpio/hooks/resume', '/usr/lib/systemd/systemd-hibernate-resume')
        (self.root/'sys/firmware/efi/efivars').mkdir(parents=True)
        self.write('proc/cmdline', 'quiet')
        self.write('proc/swaps', 'Filename Type Size Used Priority\n/dev/zram0 partition 100 0 100\n')
        (self.root/'sys/class/rtc/rtc0').mkdir(parents=True)
        self.config = '[Sleep]\n'
        p = patch.object(sleep, 'owned_directory', return_value=True); p.start(); self.addCleanup(p.stop)
        p = patch.object(sleep, 'supported_systemd', return_value=True); p.start(); self.addCleanup(p.stop)
        p = patch.object(sleep, 'filesystem_type', return_value='ext4'); p.start(); self.addCleanup(p.stop)

    def write(self, name, value):
        target = self.root/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(value); return target

    def command(self, args, **kwargs):
        self.commands.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=self.config)

    def test_unsupported_saved_mode_passes_through(self):
        self.write(sleep.POLICY, json.dumps({'mode':'hibernate','delay_minutes':120}))
        self.write('sys/power/disk', '[disabled]')
        sleep.run()
        self.assertEqual(self.commands[-1][-1], 'suspend')
        self.assertFalse((self.root/sleep.RUNTIME).exists())

    def test_disabled_uses_stock_suspend(self):
        self.write(sleep.POLICY, json.dumps({'mode':'s2idle','delay_minutes':120}))
        sleep.run()
        self.assertEqual(self.commands[-1][-1], 'suspend')
        self.assertFalse((self.root/sleep.RUNTIME).exists())

    def test_effective_policy_and_exact_boot_flags(self):
        self.config = '[Sleep]\nAllowHibernation=yes\nAllowHibernation=no\n'
        modes, reasons = sleep.capabilities()
        self.assertNotIn('hibernate', modes); self.assertIn('policy_disabled', reasons['hibernate'])
        self.config = '[Sleep]\nAllowHibernation=yes\nAllowSuspendThenHibernate=no\n'
        self.write('proc/cmdline', 'notnohibernate')
        modes, reasons = sleep.capabilities()
        self.assertIn('hibernate', modes); self.assertNotIn('auto', modes)
        self.write('proc/cmdline', 'nohibernate')
        modes, reasons = sleep.capabilities()
        self.assertNotIn('hibernate', modes); self.assertIn('boot_disabled', reasons['hibernate'])

    def test_efi_resume_and_swap_preflight(self):
        self.write('proc/cmdline', 'quiet resume=UUID=foreign')
        self.assertIn('external_resume', sleep.capabilities()[1]['hibernate'])
        self.write('proc/cmdline', 'quiet resume_offset=123')
        self.assertIn('external_resume', sleep.capabilities()[1]['hibernate'])
        self.write('proc/cmdline', 'quiet')
        self.write('sys/power/resume', '8:1')
        self.assertIn('resume_configured', sleep.capabilities()[1]['hibernate'])
        self.write('sys/power/resume', '0:0')
        self.write('sys/power/resume_offset', '1')
        self.assertIn('resume_configured', sleep.capabilities()[1]['hibernate'])
        self.write('sys/power/resume_offset', '0')
        self.write('sys/firmware/efi/efivars/HibernateLocation-foreign', 'pending')
        self.assertIn('pending_efi_location', sleep.capabilities()[1]['hibernate'])
        (self.root/'sys/firmware/efi/efivars/HibernateLocation-foreign').unlink()
        self.write('proc/swaps', 'Filename Type Size Used Priority\n/dev/zram0 partition 100 0 100\n/dev/sda2 partition 100 0 -2\n')
        self.assertIn('other_swap', sleep.capabilities()[1]['hibernate'])
        self.write('proc/swaps', 'Filename Type Size Used Priority\n/dev/zram0 partition 100 0 100\n')
        self.assertIn('hibernate', sleep.capabilities()[0])

    def test_version_and_mount_parsers(self):
        for version, supported in [('systemd 261 (261.1)\n', True), ('systemd 261.2\n', True),
                                   ('systemd 260\n', False), ('systemd 2610\n', False), ('bad', False)]:
            with self.subTest(version=version), patch.object(sleep.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout=version)):
                self.assertEqual(version_impl(), supported)
        for output, result in [('/home ext4\n', 'ext4'), ('/ ext4\n', ''), ('/home btrfs\n','btrfs')]:
            with self.subTest(output=output), patch.object(sleep.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout=output)):
                self.assertEqual(mount_impl(), result)

    def test_systemd_version_and_home_mount_are_explicit(self):
        with patch.object(sleep, 'supported_systemd', return_value=False):
            self.assertIn('systemd_unsupported', sleep.capabilities()[1]['hibernate'])
        with patch.object(sleep, 'filesystem_type', return_value=''):
            self.assertIn('filesystem_unsupported', sleep.capabilities()[1]['hibernate'])

    def test_configuration_does_not_override_host_hibernation_policy(self):
        config = sleep.configuration({'mode':'auto','delay_minutes':120})
        self.assertNotIn('AllowHibernation=', config)
        self.assertNotIn('AllowSuspendThenHibernate=', config)
        self.assertIn('HibernateDelaySec=120min', config)

if __name__ == '__main__': unittest.main()
