import importlib.util
import contextlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('deadline_test', Path(__file__).with_name('sleep_control.py'))
sleep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sleep)
efi_uuid_impl = sleep.deadline_efi_uuid
GRUB = (b'steamenv_init\nmenuentry test {\n\tsteamenv_boot\tlinux /boot/vmlinuz-linux-neptune-72 quiet\n}\n'
        b'menuentry fallback {\n\t\tsteamenv_boot\tlinux /boot/vmlinuz-linux-neptune-72 quiet\n}\n'
        b'### BEGIN /etc/grub.d/41_custom ###\nsource ${config_directory}/custom.cfg\nsource $prefix/custom.cfg\n### END /etc/grub.d/41_custom ###\n')

class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.object(sleep, 'ROOT', self.root); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(sleep.os.path, 'ismount', return_value=True); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(sleep.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(sleep, 'deadline_publish', side_effect=self.publish); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(sleep, 'deadline_sync_directory'); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(sleep, 'owned_directory', return_value=True); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(sleep, 'deadline_efi_uuid', return_value='AAAA-1111'); self.uuid = patcher.start(); self.addCleanup(patcher.stop)
        (self.root / sleep.SWAP_DIR).mkdir(parents=True)
        self.write(sleep.DEADLINE_GRUB, GRUB)
        self.write('proc/cmdline', b'quiet\n')
    def write(self, name, data):
        p = self.root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data); return p
    def publish(self, temporary, directory, record):
        os.rename(temporary, self.root / sleep.DEADLINE_CUSTOM)
    def test_lifecycle_and_reboot_status(self):
        original = (self.root / sleep.DEADLINE_GRUB).read_bytes()
        self.assertFalse(sleep.deadline_status()['tsc_deadline_disabled'])
        sleep.deadline_create()
        self.assertEqual((self.root / sleep.DEADLINE_CUSTOM).read_bytes(), sleep.deadline_bytes(sleep.deadline_read_record()))
        self.assertTrue(sleep.deadline_status()['tsc_deadline_reboot_required'])
        self.write('proc/cmdline', b'quiet lapic=notscdeadline\n')
        self.assertFalse(sleep.deadline_status()['tsc_deadline_reboot_required'])
        sleep.deadline_create(); sleep.deadline_remove(); sleep.deadline_remove()
        self.assertTrue(sleep.deadline_status()['tsc_deadline_reboot_required'])
        self.assertEqual((self.root / sleep.DEADLINE_GRUB).read_bytes(), original)
    def test_external_config_is_never_modified(self):
        custom = self.write(sleep.DEADLINE_CUSTOM, b'external\n')
        self.assertFalse(sleep.deadline_status()['tsc_deadline_available'])
        with self.assertRaisesRegex(RuntimeError, 'External custom.cfg'): sleep.deadline_create()
        sleep.deadline_remove()
        self.assertEqual(custom.read_bytes(), b'external\n')
    def test_external_stock_option_and_partial_conflict(self):
        target = self.write(sleep.DEADLINE_GRUB, GRUB.replace(b' quiet', b' quiet lapic=notscdeadline'))
        self.assertTrue(sleep.deadline_status()['tsc_deadline_external'])
        self.assertFalse(sleep.deadline_status()['tsc_deadline_available'])
        sleep.deadline_create(); self.assertFalse((self.root / sleep.DEADLINE_CUSTOM).exists())
        target.write_bytes(GRUB.replace(b' quiet', b' quiet lapic=notscdeadline', 1))
        self.assertFalse(sleep.deadline_status()['tsc_deadline_available'])
        with self.assertRaisesRegex(RuntimeError, 'Inconsistent'): sleep.deadline_create()
    def test_external_and_owned_can_remove_owned(self):
        sleep.deadline_create()
        self.write(sleep.DEADLINE_GRUB, GRUB.replace(b' quiet', b' quiet lapic=notscdeadline'))
        state = sleep.deadline_status()
        self.assertTrue(state['tsc_deadline_external'])
        self.assertTrue(state['tsc_deadline_owned'])
        self.assertTrue(state['tsc_deadline_available'])
        sleep.deadline_remove()
        self.assertFalse(sleep.deadline_status()['tsc_deadline_available'])
        self.assertTrue(sleep.deadline_status()['tsc_deadline_disabled'])
    def test_changed_custom_is_preserved_on_disable(self):
        sleep.deadline_create()
        custom = self.write(sleep.DEADLINE_CUSTOM, b'externally changed\n')
        with patch.object(sleep, 'locked', side_effect=contextlib.nullcontext), \
             patch.object(sleep, 'status', return_value={}), \
             patch.object(sleep, 'read_swap_state', return_value=None):
            sleep.set_enabled(False)
        self.assertEqual(custom.read_bytes(), b'externally changed\n')
    def test_cleanup_after_unsupported_update(self):
        sleep.deadline_create()
        self.write(sleep.DEADLINE_GRUB, b'changed')
        self.assertFalse(sleep.deadline_status()['tsc_deadline_available'])
        sleep.deadline_remove()
        self.assertFalse((self.root / sleep.DEADLINE_CUSTOM).exists())
    def test_failed_syntax_check_does_not_publish(self):
        with patch.object(sleep.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'check')):
            with self.assertRaises(subprocess.CalledProcessError): sleep.deadline_create()
        self.assertFalse((self.root / sleep.DEADLINE_CUSTOM).exists())
        self.assertIsNotNone(sleep.deadline_read_record())
        self.assertEqual(list((self.root / 'efi/EFI/steamos').glob('.boiler-sleep-*')), [])
        sleep.deadline_create()
        self.assertTrue(sleep.deadline_owned(sleep.deadline_read_record()))

    def test_wrong_slot_preserves_shared_swap_and_record(self):
        sleep.deadline_create()
        swap = self.write(sleep.SWAP_FILE, b'owned swap')
        state = self.write(sleep.STATE, b'state')
        record = (self.root / sleep.DEADLINE_RECORD).read_bytes()
        self.uuid.return_value = 'BBBB-2222'
        with patch.object(sleep, 'locked', side_effect=contextlib.nullcontext), \
             patch.object(sleep, 'status', return_value={}), \
             patch.object(sleep, 'read_swap_state', return_value={'phase': 'creating'}), \
             patch.object(sleep, 'owned_swap', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'another EFI slot'):
                sleep.set_enabled(False)
        self.assertEqual(swap.read_bytes(), b'owned swap')
        self.assertEqual(state.read_bytes(), b'state')
        self.assertEqual((self.root / sleep.DEADLINE_RECORD).read_bytes(), record)
        self.assertTrue((self.root / sleep.DEADLINE_CUSTOM).exists())

    def test_missing_mount_preserves_record(self):
        sleep.deadline_create()
        self.uuid.side_effect = RuntimeError('EFI mount unavailable')
        with self.assertRaisesRegex(RuntimeError, 'mount unavailable'): sleep.deadline_remove()
        self.assertTrue((self.root / sleep.DEADLINE_RECORD).exists())
        self.assertTrue((self.root / sleep.DEADLINE_CUSTOM).exists())

    def test_identical_foreign_custom_without_record_is_never_claimed(self):
        record = {'efi_uuid': 'AAAA-1111', 'token': '1' * 32}
        custom = self.write(sleep.DEADLINE_CUSTOM, sleep.deadline_bytes(record))
        self.assertFalse(sleep.deadline_status()['tsc_deadline_owned'])
        with self.assertRaisesRegex(RuntimeError, 'External custom.cfg'): sleep.deadline_create()
        sleep.deadline_remove()
        self.assertEqual(custom.read_bytes(), sleep.deadline_bytes(record))
        self.assertFalse((self.root / sleep.DEADLINE_RECORD).exists())

    def test_findmnt_requires_active_vfat_uuid(self):
        result = subprocess.CompletedProcess([], 0, stdout='/efi vfat abcd-1234\n')
        with patch.object(sleep.subprocess, 'run', return_value=result):
            self.assertEqual(efi_uuid_impl(), 'ABCD-1234')
        result.stdout = '/efi autofs       \n/efi vfat  95F7-61E7\n'
        with patch.object(sleep.subprocess, 'run', return_value=result):
            self.assertEqual(efi_uuid_impl(), '95F7-61E7')
        result.stdout += '/efi vfat 1234-5678\n'
        with patch.object(sleep.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'mounted EFI'): efi_uuid_impl()
        result.stdout = '/efi ext4 abcd-1234\n'
        with patch.object(sleep.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'mounted EFI'): efi_uuid_impl()
        result.stdout = '/other vfat abcd-1234\n'
        with patch.object(sleep.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'mounted EFI'): efi_uuid_impl()
    def test_rpc_requires_boolean_root_and_enabled_s4(self):
        with self.assertRaises(ValueError): sleep.set_tsc_deadline_disabled(1)
        with patch.object(sleep.os, 'geteuid', return_value=1000, create=True):
            with self.assertRaisesRegex(RuntimeError, 'root'): sleep.set_tsc_deadline_disabled(True)
        with patch.object(sleep.os, 'geteuid', return_value=0, create=True), \
             patch.object(sleep, 'locked', side_effect=contextlib.nullcontext), \
             patch.object(sleep, 'status', return_value={'enabled': False, 'router_installed': True}):
            with self.assertRaisesRegex(RuntimeError, 'Enable S4'): sleep.set_tsc_deadline_disabled(True)
        self.assertFalse((self.root / sleep.DEADLINE_CUSTOM).exists())

    def test_s4_off_cleans_owned_file_even_without_swap_state(self):
        sleep.deadline_create()
        with patch.object(sleep, 'locked', side_effect=contextlib.nullcontext), \
             patch.object(sleep, 'status', return_value={}), \
             patch.object(sleep, 'read_swap_state', return_value=None):
            sleep.set_enabled(False)
        self.assertFalse((self.root / sleep.DEADLINE_CUSTOM).exists())
    def test_failed_swap_safety_check_keeps_owned_setting(self):
        sleep.deadline_create()
        with patch.object(sleep, 'locked', side_effect=contextlib.nullcontext), \
             patch.object(sleep, 'status', return_value={}), \
             patch.object(sleep, 'read_swap_state', return_value={'phase': 'ready'}), \
             patch.object(sleep, 'owned_swap', side_effect=RuntimeError('pending image')):
            with self.assertRaisesRegex(RuntimeError, 'pending image'):
                sleep.set_enabled(False)
        self.assertEqual((self.root / sleep.DEADLINE_CUSTOM).read_bytes(), sleep.deadline_bytes(sleep.deadline_read_record()))

if __name__ == '__main__': unittest.main()
