# Boiler S2/S4 switcher — local trial

A standalone Decky plugin for SteamOS with a root-owned systemd suspend router. This is an experimental, unverified hardware trial: capability detection checks prerequisites, not actual S4 resume. It is separate from Battery/charging controls. No allocation, sleep request or service restart occurs when the panel loads or a delay is saved.

The switch defaults off. Turning it on explicitly allocates a dedicated swap file sized to physical RAM plus readable AMD VRAM, rounded up to MiB, and requires 500 MiB of free space beyond that allocation. It verifies activation and deactivation before reporting enabled. The file remains allocated but inactive between sleep requests. It is activated only while processing a system suspend request, and deactivated after wake. The six settings are immediate S4 or suspend-then-hibernate after 20, 60, 120, 720 or 1440 minutes; stored legacy delays remain readable. Timed S4 is configured for battery power. Turning the switch off deactivates and removes the dedicated swap file, retaining the preference for reinstall. Failures remain visible and do not claim cleanup succeeded.

Initial support is limited to systemd 261, EFI with accessible efivars and a separately mounted ext4 `/home`, a detected resume hook and kernel S4 support. Effective systemd sleep policy and `nohibernate` / `noresume` are respected. Configured `resume=` or `resume_offset=`, nonzero kernel resume settings, a pre-existing EFI HibernateLocation, an unrecognized active disk swap, or stale SteamOS hibernation metadata blocks S4. A recognized `/dev/zramN` partition is permitted. The verified unmodified SteamOS `/home/swapfile` is temporarily deactivated during S4 and restored after clean wake; an inactive stock swap remains inactive. systemd selects the sole active disk swap and must successfully write its EFI location before hibernation. This plugin does not edit the Valve helper or its native swap file/metadata. It uses `/home/.boiler-s2s4/` for its own swap, state and preferences, shared between SteamOS A/B slots; the state binds the file inode and filesystem UUID. A rejected readiness check at sleep time falls back to stock suspend. A possible pending S4 image is preserved and must be investigated, not deleted.

## Install and activate

Install this folder as a Decky plugin with folder name `Boiler-S2S4-Switcher`; the plugin list entry is `Boiler S2-S4 switcher`. The panel displays `Boiler S2/S4 switcher`. Decky must grant the plugin its declared root flag. For the explicit system integration, use a root-owned, non-group-writable copy of `install.py` and `sleep_control.py` together (for example, copy them to a root-owned staging directory); then run:

```sh
sudo /usr/bin/python3 -I -B /path/to/root-owned/staging/install.py activate
```

Activation installs `/var/lib/boiler-sleep/sleep_control.py` and `/etc/systemd/system/systemd-suspend.service.d/90-boiler-sleep.conf`, then runs only `systemctl daemon-reload`. It refuses the legacy Battery router, another suspend `ExecStart` override, or modified/unowned installation files. It never restarts a service or initiates sleep. If daemon-reload fails, it attempts to restore the previous files and reload again. Check the error and systemd configuration if either reload fails. Install/activate separately in each SteamOS slot where the plugin is used. A SteamOS update may change support and may require reactivation.

## Disable and uninstall

Turn off S4 in the plugin and confirm that cleanup succeeded before uninstalling Decky or removing the system hook. If the panel is unavailable, use the root-owned runtime:

```sh
sudo /usr/bin/python3 -I -B /var/lib/boiler-sleep/sleep_control.py disable
sudo /usr/bin/python3 -I -B /path/to/root-owned/staging/install.py remove
```

`remove` refuses while the owned swap state exists, and restores stock routing through daemon-reload without a service restart. It leaves `/home/.boiler-s2s4/sleep-policy.json` for reinstall. If a swapoff, ownership, filesystem or pending-image check fails, inspect and resolve the reported state before retrying; do not remove its files manually or claim space has been reclaimed. Removing the Decky plugin before the system hook is unsupported: the root-owned CLI above is the recovery path. Removing the hook from one A/B slot does not remove a hook installed in the other.

## Validation boundary

The included Python tests use temporary files and mock all system commands; `check-ui.mjs` uses a mocked Decky frontend. These do not validate the actual Decky UI, systemd, ext4 mapping, swap, suspend, firmware, hibernation, or resume on a device. A real trial requires separate controlled device and recovery acceptance.
