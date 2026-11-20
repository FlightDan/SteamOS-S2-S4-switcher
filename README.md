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

Install [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader#-installation) first. In SteamOS Desktop Mode, open Konsole as the user who runs Steam. The script prompts for `sudo` when it needs to write system files.

### Install the plugin and system hook together

From a checkout or extracted **source archive** that includes `install.sh`, run this in the directory containing `plugin.json`:

```sh
bash install.sh
```

If you downloaded the [Decky release ZIP](https://github.com/FlightDan/SteamOS-S2-S4-switcher/releases/latest), extract it and download [install.sh](install.sh) from this repository. Open Konsole in the extracted `Boiler-S2S4-Switcher` directory and provide that directory to the script:

```sh
bash ~/Downloads/install.sh install .
```

The script places the plugin in the standard `~/homebrew/plugins` directory, activates the system hook in the current SteamOS slot, and restarts Decky. Keep the extracted files or checkout for reactivation and uninstall. In Game Mode, open **Boiler S2-S4 switcher** in Decky and turn on **Enable S4 sleep** when ready. The first enable writes the dedicated swap file and can take a while.

### Activate the hook for a plugin already installed in Decky

If you installed the ZIP through Decky, run the script with the extracted files from the **same release**. This also works with a custom Decky plugin directory.

```sh
bash ~/Downloads/install.sh activate .
```

Run `activate` in each SteamOS A/B slot where you use the plugin. The hook and its runtime live on that slot's root filesystem. After an update, run it again if the panel reports **System integration is not active**. The installer stops if it finds the legacy OXP3 Battery router, a conflicting suspend override, or changed installed files. If the plugin files were copied before activation failed, resolve the reported issue and rerun the same command.

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

1. Turn off **Enable S4 sleep** and wait for cleanup to succeed. If the panel is unavailable, use the command in [Turn it off](#turn-it-off).
2. In Konsole, open the directory containing `install.sh` and the plugin files of the version activated in this slot. Run:

   ```sh
   bash install.sh remove
   ```

   If you downloaded the script separately, run `bash ~/Downloads/install.sh remove .` from the directory containing the matching extracted plugin files. For a manual installation that retained its original root-owned scripts, you can also run `sudo /usr/bin/python3 -I -B /root/boiler-s2s4/install.py remove`.

   Removal stops if swap state still needs cleanup. On success, it restores normal suspend routing and keeps the saved delay preference. Repeat this step from each SteamOS A/B slot where you activated the hook.
3. In Decky, open the menu for **Boiler S2-S4 switcher** and select **Uninstall**.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| *System integration is not active* | Run the [activation step](#activate-the-hook-for-a-plugin-already-installed-in-decky) in this slot |
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
| `install.sh` | Installs the Decky plugin and activates or removes the system hook |
| `install.py` | Explicit root-only install/remove of the systemd hook |
| `dist/index.js` | Panel UI and translations |
| `plugin.json` | Decky manifest, including the required root flag |

## License

AGPL-3.0. See [LICENSE](LICENSE).
