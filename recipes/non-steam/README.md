# Non-Steam

Launch-time controls for desktop applications added to Steam. Both dropdowns
default to **None**, which adds no command or environment overrides. Scaling
uses native toolkit settings. App Size uses `~/.dlor/run non-steam resize-window`
to resize the application's own window after launch. Neither dropdown edits
application configuration files.

## App Scaling

Choose the entry matching the application's toolkit:

| Entry | Launch setting | Available scales |
| --- | --- | --- |
| GTK / Qt | `GDK_SCALE` and `QT_SCALE_FACTOR` | 100%, 200%, 300% |
| Qt | `QT_SCALE_FACTOR` | 125%, 150%, 175%, 250% |
| Chromium / Electron | `--force-device-scale-factor` application argument | 100%, 125%, 150%, 175%, 200%, 250%, 300% |

These are UI scale requests, not universal webpage zoom controls. Applications
can override or ignore them, and an existing display scale can combine with a
toolkit's scale factor. Firefox-derived applications such as Zen may have their
own UI scaling preference that takes precedence; this recipe does not change it.
Chromium/Electron flags apply to applications that accept the Chromium switch,
not to arbitrary executables, Wine/Proton games, or unrelated launchers.

## App Size

Choose **Fullscreen** to fill the current X11 display, or choose an explicit
window size. Fullscreen preserves browser controls; it does not activate F11 or
kiosk mode. The helper does not start a nested compositor, change the Steam
session's resolution, or modify the performance overlay.

Requires the installed `~/.dlor/run` launcher, Bash, Python 3, `wmctrl`, `xprop`,
`xwininfo`, and the host X11/XRes libraries. GTK, Qt, and Firefox-derived apps
receive X11 backend overrides for this launch. A native Wayland-only app or an
application explicitly forcing Wayland is not covered. GTK/Qt applications need
their X11 backend installed.

The helper waits up to 30 seconds for a main window belonging to the launched
Steam app ID. It uses XRes host process IDs so Flatpak sandbox PIDs do not select
the wrong window, and skips dialogs, menus, and splash screens. During startup
it tags the verified window with its Steam app ID so Gaming Mode can focus it;
it repeats the resize for three seconds to handle restored window dimensions,
then stops so subsequent manual resizing works. It never resizes an unrelated
app. Logging is in `~/.dlor/logs/non-steam/resize-window/`.

A missing dependency or failed helper does not stop the application launching.
Only App Size needs a cached remote script; App Scaling works without the shared
runner. Fully exit the application before testing so the new process receives
the selected environment and scaling argument.

Steam Gaming Mode can scale a smaller window to the physical screen and add bars
when aspect ratios differ. Use Desktop Mode for a freely positioned window.
Flatpak apps must allow X11. Apps may still save their own window dimensions on
exit, as they normally do; this recipe does not edit their settings directly.

References: [GTK scaling](https://docs.gtk.org/gtk3/x11.html),
[Qt scaling](https://doc.qt.io/qt-6/highdpi.html),
[Chromium device scale switch](https://source.chromium.org/chromium/chromium/src/+/main:ui/display/display_switches.cc).
