# Art VoiceInput on macOS

Status (2026-11-02): phase 1 of the port is written; nothing has run on a real Mac yet. CI
(`.github/workflows/mac.yml`) checks on Apple Silicon and Intel what needs no permission or person: imports, key
tables, clipboard, windows opening, recognition, the headless end-to-end test, building the .dmg, installing from it
and launching the app until it is ready. Everything that needs the user's permissions (hotkey, clicks, typing,
selection reading, microphone) is untested until the user tries the .dmg on their iMac 2019 (Intel, Sequoia 15).

## Layout

| Windows (`artvoiceinput/win/`) | macOS (`artvoiceinput/mac/`) |
|---|---|
| `system.py`: Win32 windows, WinEvent foreground hook, low-level mouse hook (pynput), winsound, DWM | `system.py`: NSWindow through pyobjc (nonactivating panel, status level, all Spaces), frontmost app pid, Quartz event taps (`EventTap`, `MouseHook`), NSSound, permissions |
| `keyboard.py`: Win32 clipboard, SendInput | `keyboard.py`: NSPasteboard, CGEventPost (events marked `system.MARK` so our taps skip them), VK ↔ kVK tables |
| `hotkey.py`: pynput hooks feeding `hotkeycore` | `hotkey.py`: key and mouse event taps feeding `hotkeycore`; modifiers from flagsChanged device flags |
| `selection.py`: UI Automation, Windows Terminal `TermWatcher` | `selection.py`: Accessibility API (AXFocusedUIElement, AXSelectedTextRange, AXBoundsForRange …), Chromium / Electron trees switched on |
| `mute.py`: Core Audio via comtypes | `mute.py`: AppleScript volume settings (osascript, on a thread) |
| `autostart.py`: HKCU Run | `autostart.py`: LaunchAgent plist, `open -a` the app bundle |

## Phase 1 (written, untested on a Mac)

- Installer: `installer/build_mac.py` → `dist/ArtVoiceInput-<version>-mac-<arch>.dmg` holding 安裝阿特語音輸入法.app
  (the Windows setup window with `ops_mac.py`). Real app → `~/Library/Application Support/ArtVoiceInput/app`,
  launcher `Art VoiceInput.app` → /Applications. Unsigned: first open needs 系統設定 → 隱私權與安全性 → 強制打開.
- Permissions at launch (`system.permissions`): microphone (macOS asks), Accessibility (macOS's prompt leads to
  System Settings), Input Monitoring. The taps retry every 2s, so allowing them needs no restart. The setup wizard has
  no step for them yet: a tray notice and System Settings opened. A wizard step is a UI design to do with the user.
- Listening, drafts, commands, 復原, 選字, symbol keyboard, settings window, floating button, bubble, glow, draft
  marks: the shared code over the mac modules.
- Menu bar icon: a click does what it does on Windows (`tray_click`), the menu on the right button or Control-click.
- Dock icon only while the settings window is open.
- Fonts: PingFang TC for text, Avenir Next Condensed for numbers (`ui/theme.py`).

## Phase 2

- The tutorial (`ui/tutorial.py`, `ui/desk.py`): its pretend desktop is Windows 11; a Mac would want a Mac one.
- Terminal mouse-selection edits: Terminal.app / iTerm2 report selections through AX; `mac/selection.py` has the
  old fork's approach (cursor moved with Left / Right, then Backspace), never tried.

## Things to watch when trying it

- Whether the event taps see keys (Input Monitoring) and clicks (Accessibility) once allowed; the log says
  "key tap installed" / "mouse tap installed".
- Paste: Command+V posted to the HID tap; the clipboard restore 0.4s later (Qt).
- The floating button / bubble must not take focus from the app typed into (nonactivating panel on Qt's window:
  Qt's NSWindow may not be an NSPanel, then only the level and collection behavior apply).
- Draft marks and the 選字 menu placement: AX rectangles in points, turned into "physical pixels".
- CapsLock as hotkey fires on every press (macOS reports it as a toggle).

## History

The first try (2026-10-02, fork `voice-input-mac`, kept at `E:\Claude\voice-input-mac`) failed on the user's Mac: no
hotkey worked because a pynput listener without Input Monitoring receives nothing and macOS does not ask. The fork
(2026-10-15) had the C launcher idea and the Accessibility code this port builds on; it fell 300 commits behind.
