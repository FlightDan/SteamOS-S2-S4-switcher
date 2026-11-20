# Boiler S2/S4 switcher

A Decky plugin that makes your SteamOS handheld **hibernate (S4) instead of suspending**. Built for SteamOS on the Steam Deck and other AMD handhelds, with a small root-owned systemd hook that does the real work.

> [!WARNING]
> Experimental. The plugin checks that your system *looks* ready for hibernation, not that it actually wakes up afterwards. Hibernation writes your RAM to disk; if resume fails you can lose the session or need recovery media. Try it on a device you can afford to recover, and read the [test status](#test-status) before you trust it.

## Why S4

A normal suspend keeps RAM alive, so a handheld left in a bag slowly drains. Hibernation writes RAM to disk and powers the machine off, so it can sit for days without losing charge.

## What it does

- **Off by default.** No swap file, no state, nothing running.
- **Turning it on** creates one dedicated swap file at `/home/.boiler-s2s4/hibernation.swapfile`, sized to physical RAM plus the readable AMD VRAM carve-out (rounded up to whole MiB), and requires another 500 MiB free on `/home`.
- **The swap file sits inactive** between sleep requests. It is only switched on while a real suspend request is being processed, and switched off again after wake.
- **Two modes:** hibernate immediately, or suspend first and hibernate after 20 min, 1 h, 2 h, 12 h or 24 h. Timed modes only hibernate on battery; on AC the system just stays suspended.
- **Turning it off** deactivates and deletes the swap file, but keeps your chosen mode in `/home/.boiler-s2s4/sleep-policy.json` so a reinstall remembers it.
- **Failures stay visible.** If something does not work, the panel shows the error instead of pretending cleanup succeeded.

There is no daemon, no timer and no polling. Nothing runs until systemd asks for a suspend.

## Requirements

- SteamOS with **systemd 261**. The check is exact, so other versions report S4 as unavailable.
- EFI boot with readable efivars.
- `/home` mounted as its own **ext4** filesystem.
- A resume hook in the initramfs and kernel S4 support.
- For timed modes: `s2idle`, an RTC, and a system sleep policy that allows suspend-then-hibernate.
- Roughly RAM + VRAM of free space, plus 500 MiB.
- Decky's permission for the plugin's declared `root` flag.

## Before you start

The plugin is deliberately picky. It refuses to enable S4 if any of these are true, because each one can produce an unbootable resume or a corrupted image:

| Condition | Why it blocks |
| --- | --- |
| `resume=` or `resume_offset=` on the kernel command line, or a non-zero `/sys/power/resume` | Someone else already owns the resume target |
| `nohibernate` or `noresume` on the command line | Hibernate or resume is disabled at boot |
| A SteamOS hibernation helper is active, or `/home/.hibernation.metadata` exists | SteamOS has its own pending hibernate state to inspect |
| An EFI `HibernateLocation` variable is already present | A previous hibernation image may still exist |
| An active disk swap it does not recognise | systemd needs exactly one active disk swap to pick |
| `/home` is not ext4, or `/efi` is not really mounted | The offset math and boot slots cannot be trusted |

A `/dev/zramN` swap partition is allowed, and the stock SteamOS `/home/swapfile` is allowed if it is unmodified.

## Install

### 1. Add the plugin

```sh
cd ~/homebrew/plugins
git clone https://github.com/FlightDan/SteamOS-S2-S4-switcher Boiler-S2S4-Switcher
```

Restart Decky. The entry shows up as **Boiler S2-S4 switcher**. Accept Decky's prompt to grant the plugin root, otherwise the panel can only report status.

### 2. Activate the system hook

The panel talks to the plugin, but the suspend override is a root-owned file in `/etc`. Copy the two scripts to a root-owned staging directory first — `install.py` refuses to work from a user-writable folder:

```sh
sudo mkdir -p /root/boiler-s2s4
sudo cp "$HOME/homebrew/plugins/Boiler-S2S4-Switcher/install.py" \
        "$HOME/homebrew/plugins/Boiler-S2S4-Switcher/sleep_control.py" /root/boiler-s2s4/
sudo /usr/bin/python3 -I -B /root/boiler-s2s4/install.py activate
```

That installs:

- `/var/lib/boiler-sleep/sleep_control.py` — the copy systemd actually runs
- `/etc/systemd/system/systemd-suspend.service.d/90-boiler-sleep.conf` — routes suspend through it

Then it runs `systemctl daemon-reload` and nothing else: no service restart, no sleep. If the reload fails it puts the old files back.

Activation refuses to continue if it finds the legacy OXP3 Battery router, another suspend `ExecStart` override, or files it did not create. Remove that other integration first.

Do this **in each SteamOS A/B slot** you use. `/var/lib/boiler-sleep` lives on the root filesystem, so it is per-slot. A SteamOS update may reset `/etc` and require reactivation.

### 3. Turn it on

Open the panel, flip **Enable S4 sleep**, pick a delay, done. The first enable can take a while — it writes the whole swap file.

## The panel

| Control | What it does |
| --- | --- |
| **Enable S4 sleep** | Creates or removes the swap file and reports the current state |
| **Enter S4** | Immediately / 20 min / 1 h / 2 h / 12 h / 24 h. Older saved delays remain readable |
| **Disable TSC deadline** | Adds `lapic=notscdeadline` for Intel devices. Needs a restart, and the panel says so while it is pending |

The TSC option writes `/efi/EFI/steamos/custom.cfg` and removes it again when you turn the option off. If you already have a `custom.cfg` of your own, the plugin will not touch it and the option shows as unavailable. If the flag is already in your boot configuration, the panel says it is managed there.

## What happens on a sleep request

1. Something asks systemd to suspend.
2. The drop-in runs `sleep_control.py run`.
3. If S4 is off, or the active policy is plain suspend, it hands the request straight back to `systemd-sleep`.
4. Otherwise it re-checks hardware and swap state, turns on the dedicated swap, temporarily turns off the stock `/home/swapfile` if it was active, and asks systemd to hibernate.
5. After wake it turns our swap off, restores the stock swap, and removes the temporary runtime sleep config.

If any check fails, the suspend request is **aborted** — the device stays awake — and the reason is written to the journal. That is intentional: a half-prepared hibernate is worse than not sleeping.

## Turn it off

Turn the switch off in the panel and wait until it reports success. This removes the swap file but keeps your mode preference.

If the panel is not available:

```sh
sudo /usr/bin/python3 -I -B /var/lib/boiler-sleep/sleep_control.py disable
```

## Uninstall

Turn S4 off first. `remove` refuses while the swap state still exists, because deleting the hook does not delete the swap file.

```sh
sudo /usr/bin/python3 -I -B /root/boiler-s2s4/install.py remove
```

Then delete the plugin folder and restart Decky:

```sh
rm -rf "$HOME/homebrew/plugins/Boiler-S2S4-Switcher"
```

Order matters: the hook in `/etc` stays behind if you just delete the plugin folder, and the CLI above is the only supported way to remove it. Removing the hook from one A/B slot does not remove it from the other.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| *System integration is not active* | Run `activate` in this slot. A SteamOS update may have reset `/etc` |
| *S4 cannot be enabled. …* | One of the requirement checks failed; the message names it |
| *Enabling S4 sleep requires N MB…* | Free space on `/home`, then retry |
| *Swap cleanup requires attention* | A previous turn-off did not finish. Press **Retry cleanup**, do not delete files by hand |
| *Saved mode is unavailable; system suspend will be used* | The saved mode no longer passes its checks; plain suspend still works |
| *A restart is required…* | Reboot to apply the TSC deadline change |

Errors raised during a sleep request are in the journal:

```sh
journalctl -b -u systemd-suspend.service
```

Do not delete `/home/.boiler-s2s4/` or clear an EFI `HibernateLocation` by hand to make a warning go away. They are the only record of what the plugin owns, and a pending image needs to be understood before it is discarded.

## What this is not

- Not battery or charging control. It is a separate plugin and refuses to install alongside the legacy OXP3 Battery sleep router.
- Not a scheduler. Nothing hibernates unless you or the system already asked for a suspend.
- Not a replacement for Valve's hibernate helper. It never edits that helper, its swap file, or its metadata.
- Not verified on hardware. See below.

## Test status

The Python tests (`test_deadline.py`, `test_install.py`, `test_router.py`, `test_swap.py`) use temporary files and mock every system command. `check-ui.mjs` uses a mocked Decky frontend.

```sh
python3 -m unittest test_deadline test_install test_router test_swap
node check-ui.mjs
```

Passing tests mean the logic behaves as written. They do **not** prove that Decky renders the panel, that systemd picks the right swap, that ext4 offsets are correct on your disk, or that your firmware resumes from S4. That needs a real device, a known-good recovery path, and someone willing to test it.

## Files

| File | Purpose |
| --- | --- |
| `main.py` | Decky entry point; forwards panel calls to the installed runtime |
| `sleep_control.py` | All state, swap, policy and suspend routing logic |
| `install.py` | Explicit root-only install/remove of the systemd hook |
| `dist/index.js` | Panel UI and translations |
| `plugin.json` | Decky manifest, including the required root flag |

## License

AGPL-3.0. See [LICENSE](LICENSE).
