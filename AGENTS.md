# Art VoiceInput — notes for coding agents

Windows dictation app: sherpa-onnx speech recognition, typed into whatever has the focus, with spoken commands and
mouse-driven fixes. This file holds the working rules, the current design and the lessons worth keeping. Why things
are the way they are, removed features and old measurements: `docs/history.md` (the archived AGENTS.md, not loaded
automatically; read it before reviving or redesigning something). Module docstrings carry the details.

## Working with the user

- When you can infer what the user is really after and see a better approach or a missing detail, stop and ask
  before building (AskUserQuestion, recommended option first), as many rounds as needed. Don't guess between
  materially different designs.
- Direction (2026-10-16): turning listening on and off belongs in the interface (floating button, bubble, focus),
  not on keys and mouse buttons.
- Any UI design change (settings window, floating button, bubble, glow, 選字 menu, popups): use the design plugin
  skills (e.g. `design:design-critique`, `design:ux-copy`, `design:accessibility-review`) and
  `frontend-design:frontend-design` while designing it.
- After every commit, restart Art VoiceInput (start it even if it isn't running), always with `--debug`:

  ```powershell
  $root = (git rev-parse --show-toplevel) -replace '/', '\'
  $procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$root\run.pyw*" }
  if ($procs) {
      $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
      $procs | ForEach-Object { Wait-Process -Id $_.ProcessId -Timeout 10 -ErrorAction SilentlyContinue }
  }
  Start-Process "$root\.venv\Scripts\pythonw.exe" -ArgumentList "`"$root\run.pyw`" --debug" -WorkingDirectory $root
  ```

  Then check the tail of `%LOCALAPPDATA%\ArtVoiceInput-dev\artvoiceinput.log` for "就緒" / errors.
- `--debug` (`config.DEBUG`, set by `app.main`) keeps every utterance's recording (`save_recordings`, no setting);
  a release keeps none. Developer options live only in 系統's Debug card (`SysPage._debug_card`, 2026-10-22, the
  user's design: plain, shown only with --debug and while it has an option; options are removed when their test
  ends, the card's code stays for the next). Autostart registers the launch as this run
  was made. The installed build is a release too: debug only when its exe is started with `--debug` (the user's
  rule, 2026-10-24; never on by default).
- When the user decides something, record it here briefly as the current design (one line of why when it is not
  obvious); don't append dated narrative. Replace what it supersedes; move nothing back from history unless needed.

## Platform, layout, models

- Name (2026-10-20): 阿特語音輸入法, English `Art VoiceInput` in anything shown, `ArtVoiceInput` / `artvoiceinput`
  as identifiers (data folder, autostart value, package, log, lock); repo `art-voice-input`. "VoiceInput" alone
  never names the app (a fork used `%LOCALAPPDATA%\VoiceInput` and the same autostart value).

- Windows only (2026-10-03, macOS failed: no hotkey worked). Don't add `sys.platform` branches;
  `docs/macos-port.md` lists what a port needs.
- Development copy and installed build kept apart (2026-10-24, the user's request: no mixing them up): `paths.ID` is
  `ArtVoiceInput-dev` for a copy run from the repo (`run.pyw`) and `ArtVoiceInput` for the installed exe
  (`paths.FROZEN`); it names the data folder, the autostart Run value and the single-instance pipe, so both can run
  side by side. The home's brand block shows a white 開發版 pill after 版本 when not frozen.
- Code, `.tools/`, `.venv/` stay in the app folder; user data in `paths.DATA_DIR` (`%LOCALAPPDATA%\<paths.ID>`):
  `config.json`, logs, lock, `models/`, `hotword-list.json`, `smart-picks.json`, `packs/`, `cache/`.
  `paths.migrate_legacy()` moves old in-folder data. Autostart is re-registered each launch; it is on by default
  for the installed build, off for a development copy (new or reset; the user's rule, 2026-10-24).
- Installer (2026-10-24, layout B of https://claude.ai/artifact/8jvXUtkd9V8MU8ozxwRijy; our own Qt setup, not Inno
  Setup, so it looks like the app): `installer/build.py` builds the app with PyInstaller onedir (`installer/app.spec`;
  onefile unpacks at every launch, more antivirus false alarms), copies the X-ASR files and the VAD into its `models/`,
  builds the setup program onefile (`installer/setup.spec`) and appends the app folder to it as a zip
  (`installer/payload.py`) -> `dist/ArtVoiceInput-Setup-<version>.exe` (~230MB). Per-user install to
  `%LOCALAPPDATA%\Programs\ArtVoiceInput` (no admin, no UAC; 換個位置 picks a folder, an ArtVoiceInput folder is made
  inside it), Start menu shortcut, uninstall entry in HKCU (Windows 設定 → 應用程式); `uninstall.exe` is the setup exe
  without the payload, run from a temp copy; it closes the app, removes the folder, the shortcut, the entry and the
  autostart Run value only when it points into the folder, and asks whether to delete settings and 詞庫 (default:
  keep; `/quiet` keeps). The installed build (`paths.FROZEN`) reads its bundled models (`paths.BUNDLED_MODELS_DIR`),
  registers the exe for autostart, skips `migrate_legacy`. Unsigned for now: SmartScreen's 其他資訊 → 仍要執行 is
  accepted. Testing an install: `--dir <folder>` on the setup exe; launch the installed exe with LOCALAPPDATA pointed
  elsewhere so it doesn't touch the user's installed data. `build.py` copies the models from the development data
  folder.
- Fixed models, no model choice, no LLM (`models.py`; URL
  `https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/<dir>.tar.bz2`):
  recognition X-ASR int8 `sherpa-onnx-x-asr-zipformer-transducer-zh-en-punct-int8-2026-06-03` (130MB, ~0.75s per
  18s, punctuation, good English); VAD silero (`models.vad_path()`). SenseVoice Small (second opinion,
  `suspects.py`) is not loaded: its code in `app.py` is commented out. Memory ~1.1GB, much of it the word index.
- The app will be shared with other users and must stay light (the user's machine: 8GB RAM, i5-8500): fixes must
  work for anyone (no per-user acoustic training) and not add big models.

## Module map

| Module | Role |
|---|---|
| `app.py` | `App`: hotkey/focus/click events, listening sessions, drafts, commands, 復原, 選字, workers |
| `listen.py` | `Listener`: microphone + VAD, pieces, quick pieces, audio kept for drafts / 復原 (`hold`) |
| `asr.py` | `Recognizer`: X-ASR, hotword biasing, `recognize_timed` (token times), `_pieces` (>30s audio) |
| `textfmt.py` | `format_text` pipeline (below), `changes` for the log |
| `session.py` | text Art VoiceInput typed before the caret, `history` of `Step`s for 復原 |
| `output.py` | Win32 clipboard paste, key sending, clipboard restore and watch |
| `selection.py` | UIA: selection, caret line, `focus_info`, `TermWatcher` (terminal mouse selections) |
| `highlight.py` | draft mark rectangles (`draft_rects`) and `DraftMarks` windows |
| `rules.py` | spoken operations (自訂操作), `defaults`, `upgrade` / `simplify` (rules_version 16) |
| `edit.py` | punctuation names (`symbol`), described characters (`described`), spelled letters (`spelled`) |
| `candidates.py` | McBopomofo dictionary: `is_word`, `frequency`, `ranked`, `sounds_alike`, fuzzy pairs |
| `sounds.py` | English near-sounding words (CMUdict + wordfreq, `dict/english.tsv.gz`) |
| `syllables.py` | the Chinese character an English syllable may have been (啊 -> Ah, 的 -> The) |
| `hotwords.py` / `memory.py` / `spelling.py` / `packs.py` | 詞庫 list, 選字記憶, English spelling/aliases, 詞包 |
| `picker.py` | the 選字 menu |
| `floatbtn.py` / `orbs.py` | floating button and bubble (`OrbButton`), the ten 按鈕樣式 looks |
| `glow.py` | screen-edge glow while listening |
| `appicon.py` | the app icon (design J 光澤: warm diagonal gradient, sheen, white mic): tray, wizard badge, window icon; `dev/build_icon.py` writes `appicon.ico` for the exe |
| `tray.py` | tray icon (the app icon, a turning ring on its square while listening), `promote` (taskbar, not ^) |
| `ui/` | settings window (2026-10 redesign): `theme.py` tokens + QSS, `kit.py` widgets, `shell.py` home and transition, `window.py` app interface, `page_*.py` the six pages, `wizard.py` setup wizard, `tutorial.py` / `desk.py` / `sprite.py` the tutorial, `sheet.py` in-window question |
| `logbook.py` | 辨識紀錄 rows |
| `config.py` / `userdata.py` | `Config` (load migrates old keys) / settings file export, import, reset |
| `hotkey.py` / `keys.py` | low-level hooks, hotkey capture, key names |
| `cues.py`, `mute.py`, `recordings.py`, `autostart.py` | sounds, speaker mute (`recover`), dev recordings, autostart |

## Listening (continuous)

Listening is a switch: on, it takes text, spoken commands and mouse edits until turned off.
- **On / off**: 麥克風快捷鍵 (`config.hotkey`, captured from any key, combination or mouse button but the left; a
  press is always a tap, fully suppressed; a modifier alone fires on release with nothing else pressed and is not
  suppressed, with Alt/Win an unassigned 0xE8 is sent so no menu opens), the floating button, the bubble, a left
  click on the tray icon when 點一下圖示 is 開關麥克風 (`tray_click` "mic"; default "settings" opens the settings
  window; `App._tray_clicked`: the window typed into before gets the foreground back from the taskbar;
  setup wizard unfinished → opens it; the menu is on the right button),
  點進輸入框時 = 自動開麥克風 (`auto_listen`), spoken 結束,
  送出訊息後自動關閉麥克風 (`stop_on_enter`: Enter / Ctrl+Enter or an operation's Enter step), 沒講話多久自動關閉
  (no speech for `auto_off_minutes`, default 5, chips or a 自訂 chip taking 1-240 minutes; tray notice), 自動關閉麥克風
  (`auto_off`, below). Red warning on 麥克風 when nothing can turn it on.
- **Focus** (`App._watch_focus`, every 0.3s, `selection.focus_info`: editable?, identity, rect; a terminal always
  counts as editable). With auto_listen a left click that put the focus in a text box turns listening on, at the
  moments the bubble would show (`App._clicked`; keyboard focus does nothing; 2026-10-20). 離開輸入框後關閉
  (`auto_off`, off by default, a switch in the auto-off card since 2026-10-21, for any way listening was turned on): the focus
  leaving a text box for a non-editable place turns it off. The settings window in front counts as non-editable
  (2026-10-20, the user's request: the user knows where they clicked, a microphone left on there misleads); the
  floating button, bubble and 選字 menu (never in front) and unknown controls change nothing.
- **Bubble** (`show_bubble`, default): fades in just right of a left click (not a drag) that put the focus in a text
  box (focus read 120ms after the click); goes on typing / wheel (at once) or focus leaving (fade). Keyboard focus
  shows nothing. Listening started from it or anywhere else bursts it away; it doesn't come back when listening ends,
  only at the next click into a text box (2026-10-20). Placed at the click because UIA caret positions are wrong in Notion, LINE, web pages.
- **Floating button** (2026-10-22, the user's design: three ticks, multi-select, any one turns it on, `show_float`
  derived): 未偵測到輸入區域時顯示 `float_away`, 偵測到輸入區域時顯示 `float_box`, 錄音時顯示 `float_rec` (old configs:
  show_float with float_text_only / float_keep migrated in `Config.from_data`); `float_pos`, [] until dragged: 24px in
  from the right edge, halfway down, away from title
  bars, tabs and notices, 2026-10-22): never takes focus, draggable; fades in (180ms) and out
  (160ms) as the focus comes and goes.
  Starting to listen grows it to 1.5 and fades it out in `glow.FADE_MS`; ending reverses it. Kept on screen
  (`float_rec`) it shrinks to 0.88 while listening and its orb plays faster (2026-10-20).
- **Pieces**: the microphone opens unseen; silero VAD ends a piece at 0.3s silence (0.5s lead-in, 0.25s tail kept).
  Sample numbers continue across sessions (a reset made queued jobs read the new session's audio: text typed twice);
  the new session's state is reset by a worker job queued after the old ones. Audio is kept as chunks and trimmed
  while nobody speaks.
- **Draft** (`_Draft`): text since the last commit, typed in the document (Backspace to the change + paste). At each
  pause the open sentence is decoded again and retyped (`_refine_job`). Text up to a ，/。 the recognizer put in a
  pause is settled; only the open sentence is re-decoded, from its pieces only (`App._speech`: gaps cut, 0.5s more
  of each pause kept, `_GAP_KEEP`) — beyond 30s the recognizer gives no timestamps, so nothing would settle. A draft
  shows the recognizer's 。？！ at its end; the next pause turns it into ， when the sentence goes on.
- **Commit**: on a command or the end of listening (a draft over 60s commits at a pause). It keeps the recognizer's
  。？！ or adds 。 (？ after 嗎, . when the draft has no Chinese), not when the caret has text on both sides; a
  spoken mark replaces that. A commit reuses the last pause's decode when its last piece is the spans' last (`App._live`).
- **Caret moved** (click, key, selection; `_caret_left` from the hooks): the draft stays as typed, the next speech
  starts a new one; a late update is redone at the new caret (`_redo_job`). A draft started over a selection
  replaces it.
- **Draft mark** (`highlight.py`, color `highlight_color`, default yellow because blue read as a selection; a 自訂
  color's opacity fixed at `config.MARK_ALPHA`, 2026-10-22): only the
  open sentence, read every 0.15s on a thread, hidden while the wheel turns, on caret moves or another window in
  front. Windows Terminal reports a wide character 3 cells wide (it takes 2).
- **Pastes** (`output.paste_text`): Win32 clipboard owned by a hidden window (Qt's lazy clipboard let a following
  paste replace the data before Windows Terminal read it); wait 0.15s after the last Ctrl+V; clipboard (all formats)
  restored 0.4s after a run's last paste, or at once before a copy (`output.restore_now`).
- **Mute** (`mute_while_recording`, Core Audio): only a mute we set is undone; a `.muted` marker lets the next launch
  unmute after a kill (`mute.recover`).

## Commands said alone

An utterance that is exactly an operation's phrase, a punctuation name or a described character commits the draft
and runs (nothing decoded when nothing was said since the last commit).
- Decoding (`App._command_first`): a piece with at most 1.2s of speech is decoded first with commands boosted
  (score 5, commands alone: hotwords and packs competed) and padded with 0.3s of zeros at both ends, then plainly if
  that is no command. A piece of more than 2s of speech (`_ALONE_MAX`; the user's commands: p99.9 2.03s) is not
  decoded alone: straight to the open sentence's decode, 0.25s sooner (2026-10-22, the user's request for speed);
  its tail still runs a command (`_ran_tail`). Decoding threads stay 3 (4: +40%, 6: twice as slow, 2 the same). Boosted-first gate `_FIRST_MAX` 1.5s (1.2 until 2026-10-22: commands
  2370 -> 2395 of 2402). A short piece with no command after the boosted-first decode is boosted once more over it
  and 1s before, then the sentence's plain decode (對 1.25 -> 0.69s; commands 2415/2420 as before; boosting the
  whole sentence too made long sentences slower). Both are the only way since 2026-10-24 (the user's decision: text
  shows sooner; the old decode-alone paths and the Debug card's skip_alone / skip_short switches removed).
  Command phrases are kept out of 詞庫 biasing (`_bias_words`: 括號 at 200% made 逗號 / 換行
  into 括號). A piece that, decoded with the speech before it, ends exactly in a command runs as one (`_split_at`,
  `_ran_tail`). Repeats the boost made (結束結束結束) count once (`_one_command`).
- Sound-alike (`_alike`, `candidates.sounds_alike`): same tones required, fuzzy pairs, dictionary readings of the
  command (any reading of a 多音字 only where the dictionary lacks the word). 金嘆號 → 驚嘆號; 都好, 問好, 放心 are not
  commands. Still taken: 封號 → 分號, 據點 → 句點.
- Quick commands (always on, the user's decision 2026-10-20; no setting): a second VAD at `QUICK_SILENCE` 0.15s
  runs short pieces after a pause at once when a command (`_quick_ok`, all commands), the following piece cut
  (`_quick_done`).
- Spoken operations (`rules.py`, 自訂操作 tab): phrase(s) separated by 、 → one step: keys, text, 左右輸入文字
  (`WRAP`, caret put back between), or a command: 復原, 結束錄音, 全選 / 複製 / 剪下 / 貼上. Defaults
  (`rules.defaults`, rows fixed but the phrase; empty turns off): 換行、下一行 Shift+Enter, 空白, 括號 （）,
  引號 「」, 符號 (the symbol menu, below), 鍵盤 (Windows' on-screen keyboard osk.exe, `rules.OSK`, rules_version 16; 符號 and 鍵盤 are the 工具 group on 語音指令, 2026-10-22), 刪除 Backspace, 復原 / 撤銷, clipboard four, 送出 Enter
  (listening goes on), 結束. With --debug the
  defaults (`rules.defaults(dev=True)`) also have the user's `rules.dev_rules` as 自訂 rows (標點 = "- ", 貼上圖片 = Alt+V);
  a --debug launch adds them when missing. 自訂 rows can't take
  a command a default row has. Problems shown in red when the tab comes into view. The engine still has situations,
  multi-step and key rules (old configs only).
- Edit commands: ordinary apps get Ctrl+A/C/X/V. Terminals: 複製 puts our read selection on the clipboard (Ctrl+C
  clears Claude Code's input), 剪下 also deletes, 貼上 replaces the selection (if the terminal copied the selection
  itself on select, the clipboard text before it is pasted: `output.watch_clipboard` / `text_before`), 全選 a
  notice. Backspace / Delete / text steps act on a terminal selection, not the cursor.
- Punctuation names (`punctuation_names`, `edit.SYMBOLS`; 2026-10-22 the user's list): 逗號 / 逗點, 句號 / 句點, 頓號,
  問號, 驚嘆號 (驚歎號 as X-ASR may write it), 分號, 冒號, 刪節號 / 省略號, 破折號 ——, 斜線 / 斜槓 ／; no 感嘆號 or
  點點點. 語音指令 shows the keycaps on one row, each mark's names under it (two on two lines); the card takes 7/10 of the width. Appended after existing punctuation;
  replace a selection; a mark said right after an added one replaces it (`edit.MARKS`: not —— or ／). A 自訂 row with the same phrase runs instead and is not marked as a clash (the user's choice).
- Described characters (`describe_char`): everything before 的 exactly one dictionary word, no lead-in (節日的節 →
  節; 顯示的是 → 示). Spelled letters over a selected English word type that word (`edit.spelled`, counts as a pick).
- Not carried over from press-and-talk yet: `period_to_comma` (selected 。 → ，+ utterance + 。; checkbox hidden,
  `app.py` ignores it) and trimming punctuation when replacing a selection.
- **復原** (`Session.history`, unlimited while the caret hasn't moved): takes back Art VoiceInput's last change while it
  is right before the caret: typed text, a pause's update of the draft (one each), a mark, a new line, Space, text
  over a selection (selection comes back), a deleted selection, 剪下 / 貼上 (ordinary apps; paste of one line ≤300
  chars), a Backspace after the caret moved (`Session.known`; only if the caret's line still reads as expected,
  `_still_reads`, else a notice). The draft comes back as it was, marked and re-decodable (`Step.restore`,
  `_Draft.restored`, audio held up to 180s by `Listener.hold`), else as fixed text. Operations starting with
  Backspace / 復原 add no sentence end (`_no_mark_first`). Typing or clicking ends the history; nothing to take back
  → tray notice with the reason.

## Text pipeline

`asr.py` (biased toward 詞庫, ticked packs, on-screen terms) → `textfmt.format_text` → English spelling
(`spelling.py`) → 選字記憶 (`memory.apply`) → paste. Each changing step is logged (`format <step>: before -> after`)
and shown in 辨識紀錄. Order inside `format_text` matters: s2tw → filler removal → disfluencies → 百分之 →
numerals → spelled letters → 點 → percent → number+letter → English punctuation → CJK/ASCII spacing → English
sentence end → 嗎 questions → trailing punctuation.
- OpenCC `s2tw` only (`s2twp` rewrites vocabulary: 程序 → 程式); then 臺 → 台, 熒幕/熒光 → 螢幕/螢光. 嗯 / 呃 removed.
- Disfluencies (`remove_disfluencies`): repeated 2-4 char chunks, restarts, stutters; kept: dictionary ABAB
  (研究研究, `_ABAB`), counting (一個一個), laughter, 好的好的, words sharing a character (開關關掉), 剛剛 etc. A-not-A
  is a repeat only when A comes a third time (是不是不會 must keep its meaning). 在 is not a stutter character.
- Numerals: single-character numbers stay Chinese (一個, 第二種) unless decimal / percent / before a single letter;
  multi-character become digits (十五 → 15); `_KEEP_WORDS` (統一, 星期三 …), ranges (三四), 幾, fractions skipped.
  Number+letter join (二 B → 2B); after English a single numeral becomes a digit unless a classifier follows
  (GPT 四 → GPT 4, Python 三個月 stays); decimals digit by digit (零點零五 → 0.05). 點 → `.` only between digits or
  letters. 百分之X / X percent → X%.
- One character said alone (2026-10-21, the user's report; `App._as_chinese`, after spelling, before 選字記憶): an
  utterance that is one English word of 2-6 letters (not all capitals, no known term) replacing one selected Chinese
  character, or next to Chinese at the caret, becomes the likeliest character (`syllables.chinese_for`: pinyin
  spelling or CMUdict phonemes against Mandarin syllables, a character making a word with a neighbour first, never
  the replaced one); 辨識紀錄 step 英文轉中文. 選字記憶 is not involved (tried and reverted the same day: the user's
  mishearings are one character said alone, not English amid Chinese).
- English sentence end: . ? ! after English → 。？！ when the sentence has Chinese. 嗎。 → 嗎？ (only 嗎: 呢 / 吧 end
  statements too).
- Trailing punctuation: kept, except when the caret's line has text on both sides (`selection.read_caret`; in
  terminals the input box row under the cursor). Unknown → kept.
- X-ASR fails on >40.05s audio (encoder Reshape error): `asr._pieces` cuts ≤30s pieces at the quietest 0.2s.

## 選字, 詞庫, picks

- **選字 menu** (`picker.py`): opens by itself while listening (`App._auto_pick`) after a mouse drag or double click
  that selects ≤4 Chinese characters or ≤3 English words (read 80ms after release). Tabs by closeness of sound
  (pointer over a tab opens it), design G2 made compact (the user's pick, not G3): a plain list with the tabs in a
  rail on the right (name over count), light or dark with `config.theme`; grid 3x5 (one character, about the words' size) or 2x5, only as
  many columns as the fullest tab needs; the word there now leads the first tab, bold with an orange mark (a click
  on it keeps it; counts leave it out); no timeout, any click or key closes it. Chinese (`candidates.ranked`): 同音, 不同聲調, 模糊音 (`candidates._FUZZY`: zh/z,
  sh/s, an/ang, en/eng, r/l, ㄩㄣ/ㄧㄣ, ㄈ/ㄏㄨ, ㄋ/ㄌ …; fuzzy-only words from frequency 3, `app._FUZZY_MIN`; 詞庫
  words by sound too). English: 近音字 (`sounds.near`, weighted phoneme edit distance), 詞庫 (`sounds.alike`), 大小寫
  (`memory.variants`), 中文 (Chinese X-ASR wrote as English, `syllables.chinese_words`: one word as characters,
  2-3 words as a dictionary word, How the -> 好的; first next to Chinese; the spaces to Chinese go with the pick;
  nothing learned).
- **Symbol keyboard** (2026-10-22, the user's request; design A of
  https://claude.ai/artifact/FSX49ZChyWMdwvv5i8kPcG): said 符號 (`rules.KEYBOARD`, rules_version 15; shown as 打開符號選單), the
  選字 menu opens under the caret (`selection.caret_rect`, else the selection, else the mouse) with `picker.SYMBOLS`:
  全形 (marks, then pairs), 半形, 英文 A-Z, 數字 0-9 and ０-９ (5x6 cells, "" a gap; 2026-10-22); a click types the symbol (over a selection), a pair (`picker.PAIRS`, also the
  half-width () [] {}) around the caret or selection like 括號, and closes it; no 。 is added before it. Speech typed
  while it is open closes it. Only full- and half-width symbols (no emoji: Win+. has them; no letters or 注音).
- **Numbers in 選字** (`numforms.py`, 2026-10-22, the user's request): a selected number (123, 3.14, full-width
  too) opens the menu by itself with 中文 (一百二十三, 一二三 by digit, 壹佰貳拾參) and 全形 / 半形; letters with digits
  (a12) 大小寫 and 全形; English number words (One, two -> 1, 2; numforms.english) a 數字 tab first. Nothing is
  learned from these picks. Not offered (the user's choice): near-sounding numbers, 千分位, 三十五 -> 35.
- **詞庫 list** (`hotwords.py`, `hotword-list.json`; code says hotwords, UI says 詞庫 / 優先度): 優先度 shown as
  stored − 100 (0% nothing, +100% top, negative red). A pick of 2+ characters or English moves the picked word +25%
  and the replaced one −25%. Typed words are top. English replaced by English goes down too, to −50% at most (2026-10-21, TTS-measured: `hotwords` docstring); English for Chinese or back lowers no English; case forms are separate hotwords. Single characters never listed. ✕ puts a
  word back to unlisted level; −/+ beside its bar move it 25% (sliding), and a word so set stays listed even at 0%
  (`kept`, 2026-10-21); the list shows no source (選字 / typed), only the date. Biasing scores: +5 Chinese / +3 English at the top, −3 at the bottom. A Chinese word
  another one starts with is not sent (剪貼 made 剪貼簿 into 剪貼布).
- **詞包** (`packs.py`, shipped `artvoiceinput/packs/<id>.txt`, user copies in DATA_DIR/packs read instead, edits apply at
  the next dictation; an update appends new shipped terms under a dated comment, `packs/shipped` keeps the last
  shipped copy). Seven packs (`packs.ORDER`), none ticked by default; ticked words bias at 150% unlisted. No version
  numbers, no common words as products, nothing the hotword encoding can't hold (UI/UX, 4K). A pick or typed word an
  unticked pack lists brings a tray hint (`_suggest_pack`) every time, also a 詞包建議 row in 辨識紀錄; clicking either opens 詞庫's 詞包.
- **English spelling** (`spelling.py`): a run of English words whose letters equal a known term's (詞庫, packs,
  on-screen terms) is written as the term (case only when it adds inner capitals). Aliases (Dipsick → DeepSeek, from
  picks or spelling) are always rewritten; 英文強制替換 lists them.
- **選字記憶** (`memory.py`, `smart-picks.json`): single Chinese characters only; key = toned reading + two
  characters on each side; applies only when the characters right before and right after both agree (text edge
  counts) and no dictionary word around is broken (`_breaks_word`); never breaks a raised 詞庫 word or makes a lowered
  one (`Hotwords.levels`). Picking back a changed character learns "keep it here" under the heard reading.
- **On-screen terms**: at the start UIA reads the focused control's text; CamelCase / acronyms / digits, and 5+
  letter words seen twice, bias at 1.5; git commit hashes (afe5559) are not terms.
- Dictionary: McBopomofo word list (MIT, `dict/words.tsv.gz`, `dev/build_dict.py`), cached as
  `cache/word_index.pkl`. English: `dict/english.tsv.gz` (`dev/build_english.py`, wordfreq CC BY-SA + CMUdict BSD).

## Selections and terminals

- Selection read via UIA TextPattern on a thread; speaking replaces it.
- Terminals (Claude Code / Codex / agy in Windows Terminal inside herdr) hide mouse selections from UIA:
  `selection.TermWatcher` maps drag ends with `RangeFromPoint`, narrows to cells herdr highlighted (inverted colors),
  handles double / triple clicks; no clipboard (herdr `copy_on_select` off). Only one line of the input box (row
  starting with ❯ / › / > plus indented rows under it; Claude Code's "❯ 3. …" counts) and the cursor must be in it.
  Edits move the cursor with arrow keys until it sits after the selection (re-read after each burst; Codex needs one
  Left first), then Backspace 20ms apart (a burst lost one) and paste; can't get there → nothing deleted, notice.
  In the background WT reports the cursor one character left.
- Our own windows over the target block UIA `ElementFromPoint` while they animate: hide them at once before a
  terminal edit.

## Settings window and looks

Defaults (`Config`) are the user's own setup: no hotkey, bubble, floating button (流光 look), 彩虹 glow, autostart
on.

Launch (2026-10-21): started by the user the settings window opens on its home; at login (`autostart.FLAG`
`--autostart` in the Run entry) only the tray icon, unless the setup wizard is unfinished. A second launch asks the
running one (`app.PIPE`, QLocalServer) to show its home. Tray icon (`tray.py`, the user's design): the app
icon (`appicon.py`, design J of https://claude.ai/artifact/JU4N5jkE3UiiURvWfUhUNK, 2026-10-21; also every window's
icon and the wizard's badge), while listening a white ring turning on its square (1.2s a turn, half the
frames with 節流模式). 系統's 圖示固定在工作列 (`tray_pinned`, off by default) sets IsPromoted in
`HKCU\Control Panel\NotifyIconSettings` for this executable's entry (applies live; off at launch writes nothing);
"點一下 [the tray icon drawn] [dropdown]" after its switch picks 打開設定視窗 / 開關麥克風 (`tray_click`, 2026-10-21). 系統's names
column is 300px so each gray line fits one line and the page needs no scrolling.

Settings window (`ui/`, the 2026-10 redesign; mockups on the claude.ai Design canvas
https://claude.ai/artifact/8UWdBateenAsqfZKeHPeiG, style C): frameless 960x640, Windows 11 rounded corners. Home:
the orange brand block (status with a pulsing dot while ready, logo, 阿特語音輸入法, version from
`artvoiceinput.__version__`, 44px medium so only the name stands out, 版本's ink bottom on the digits'; logo and
names carry the logo's solid shadow, from design H5; the version, the status line and the lines below have none) and
six tiles, each icon
bled large into the tile's bottom right (tilted 5°; hover lifts it up-right, turning clockwise). A tile opens its page
(transition Fly): the block shrinks to a 56px strip that goes home, the icon flies to the page title. Pages: 麥克風
(design M2: no section labels since 2026-10-21; each of the three cards opens with its illustration (`ui/illus.py`,
round 13's L1-L3 drawn in Qt, played while the pointer is on the card, a still frame at rest, never with 節流模式;
clicks are cartoon bursts); hotkey card, 點進輸入框時 radio, floating button card with three tick rows drawn like the radio rows (偵測到, 錄音時, 未偵測到 last; no switch,
no ⓘ on them); no orange outline on cards (outlines answer the pointer only); each card's state pill (`kit.Pill`) is solid
orange and breathes while on, all pills in step with the clock; auto-off small chips on one line with 送出訊息後關閉 and 離開輸入框後關閉 under them, device with 測試麥克風
(`audio.LevelProbe`, its own stream; meter design I1: 24 segments, the last six warmer, a falling peak tick; stops
when the page hides), mute), 外觀與聲音 (on one screen, no scrolling: preview beside the mark colors (design A3,
named), button looks beside the glow, whose 自訂顏色、速度與邊緣 slides its editor in its place in the same card
(design A1, `kit.Slides`; the page around it stays put): names in one column, controls from the sliders' left, values
after the sliders, small 發光邊緣 chips, 回到光暈樣式 where the chip was, 恢復預設 across; sounds across, 自定義's start
and end beside the sets (room kept, the sets don't move); while listening
▶ 預覽 / ▶ 試聽 read 錄音中無法使用 and picks play nothing), 語音指令 (design C4: "當我說 [chips] 就 [what]" grouped with an orange bar per group, phrase chips edited in
place, 自訂 rows choose 按下按鍵 / 打出文字 / 左右包住, 新增一句; a phrase said for two rows
is marked (a punctuation name is not: the row wins); 說標點的名字 and 說「詞的字」 cards below), 詞庫 (design 1: segmented tabs with counts, search,
order), 辨識紀錄 (design 1: timeline, filters 全部 / 文字 / 指令 / 選字與復原, 清除紀錄 → `App._clear_log`), 系統
(design 3: 外觀模式 亮色 / 暗色 / 跟隨系統 with sun / moon / computer icons, autostart, 節流模式, settings file
drop zone, about; switch notes start with 開： / 關：, about's values one size, the folder path a little smaller;
a mode picked cross-fades the window from a snapshot in 220ms, not with 節流模式; no slide under it). 節流模式 (`orb_lite`) also calms this window (`kit.calm`): pages switch at once, no hover,
switch or slide animations, the ready dot and state pills hold still, the preview's glow stands still. `config.theme` drives the settings window and the 選字 menu;
the floating button, bubble and glow are colored and not themed. `dev/settings_preview.py [page] [--dark]
[shot.png]` shows the window on a temp copy of the user's data.
- One typeface, Noto Sans TC (Bahnschrift for numbers, wherever digits show: chips, counts, dates, times; a
  style-sheet-sized widget takes `theme.NUM_FAMILY`): the window sets the application's font, since a style
  sheet font-size gave a widget Segoe UI / 正黑體 (grainy, the user's report 2026-10-20). Gray lines 12px, checkboxes
  14px medium like the radio rows' names.
- Each setting's help is an ⓘ after its name (`ui.kit.Info`), not tooltips. Where an ⓘ doesn't fit (icon buttons,
  swatches, phrase chips, dates, the 回首頁 strip) a hint shows after the pointer rests 1s (`kit.TipRouter`);
  辨識紀錄's row tips show as soon as the pointer comes (`quick_tip`, 2026-10-21: a page read by sweeping). All are `kit.Tip` (120ms fade), never Qt's tooltip.
- 設定檔 (`userdata.py`): 匯出 writes all settings and the 詞庫 (list, aliases, 選字記憶, pack files) to one JSON; 匯入
  replaces settings except `userdata.LOCAL` (mic, autostart, float place, setup_done) and merges the 詞庫 (file
  wins). 清空並重新設定 (a button, like a phone's factory reset, 2026-10-21) asks in a `ui/sheet.py` card (window
  dimmed; 先匯出設定檔… link), then resets everything including the 詞庫 and 辨識紀錄 (models, cache and dev
  recordings stay), then the app closes and starts again (`App.restart`, `--restarted` waits for the lock), new,
  on the setup wizard.
- **Setup wizard** (`ui/wizard.py`, 2026-10-21, design C of https://claude.ai/artifact/LFjmoPLHVf1bz7irmzKy6i): over
  the whole window, one card on the wall, light or dark with the window. Shown when the settings window opens while
  `setup_done` is false (a new install, after 清空並重新設定; `app.main` opens it at launch; a config.json from
  before the wizard counts as done); closed before the end it comes back. Until it is finished the app rests
  (`App._paused`: no hotkey, floating button, bubble or listening). 1 microphone: name, device, meter; status 試著說…
  → 正在聽… (speech coming in, decoding) → green dot + 聽到了 when 你剛剛說 shows (decoded on the worker; trial, the
  user decides whether it stays); the icon over 阿特語音輸入法 at 26px (34 stood apart from it), no 已經裝好了; 略過 (plain) becomes 下一步 then. 2 packs, 3 columns, two lines of whole sample
  terms, no counts; 跳過 / 下一步. 3 標準 (floating button only while listening, 3 minutes' auto-off) / 簡單 / 自動 / 簡約 (`wizard.PRESETS`, 2026-10-22, rows 80px; buttons 40px high, 168 / 240 wide; 簡約: nothing on screen, no glow, 送出 not closing,
  右 Alt `vk:a5`, the tray icon on the taskbar turning the microphone on/off, 5 minutes' auto-off only), fixed height,
  each one short line, no list of what it sets; 開始教學 (each setup has its tutorial) or 跳過教學，直接開始使用 finishes.
  ‹ sits in the left margin on the title's line; card 600x580 (2026-10-24, the user's report: buttons too high,
  too little padding). Focus rings only after Tab. 系統's Debug card has 進入設定精靈 (2026-10-24: 清空並重新設定 at once, no
  question; the restarted app's wizard alone in the theme shown before, `window.WIZARD_THEME`, the setting reset).
- **Tutorial** (`ui/tutorial.py`, 2026-10-24, the user's design; it teaches the setup in use, `wizard.mode_of`:
  標準 bubble, 簡單 the floating button always there, 自動 a click in turns it on and a click outside off, 簡約 no
  glow, only 右 Alt (the hotkey; hotkey.py's 0xE8 ignored) or the tray icon, both named in the red words; only 標準's 送出 turns the mic off): over the window after the wizard's 開始教學 (the setup applied, `setup_done` still false,
  `Config.tutorial_at` the chapter to come back to) or 系統's 重看教學 (關於 row; `replay`: settings untouched). A
  strip on top (icon, 教學, ten chapter segments, 略過教學 asking in a `Sheet`), a pretend Windows 11 desktop
  (`ui/desk.py`): wallpaper Bloom A1+ of https://claude.ai/artifact/FXMWnBF7Ek4uLwQ3y3JAiM (light and dark, the two
  rings of petals swaying over 14s, still with 節流模式), taskbar (clock in Noto Sans TC like the artifact, not the
  number face: the user's request), 記事本 and a chat with 小美, `FakeText` boxes (caret, drag / double-click
  selection, the draft yellow), the real `OrbButton` as bubble (28) and floating button (44) in 麥克風（原始）, a
  錄音紅 edge glow, the real 選字 menu as a child (`DeskPicker`). The desktop starts empty so the wallpaper shows;
  the user opens 記事本 from the taskbar; the guide opens the chat itself.
  Guide (`ui/sprite.py`): design B of https://claude.ai/artifact/A8FNxjZPgBfCV3z3Tvod8G, the app icon's square with
  a white-line face (eyes look toward the target, blink, bob; faces idle / happy / listen / oops / proud / think,
  C's https://claude.ai/artifact/8sHxkNoyPRWTPMkgmaxQma), moving beside what to look at with its `Card` (繼續, or
  what it waits for; ‹ 上一句 shows past lines on a grayer card; 跳過這步; named 小阿特, 2026-10-24), placed clear of the target and the text being read
  (eyes and a slight lean toward the target from where it lands; no overshoot: it bumped the floating button). A
  click that isn't what it waits for gives the red words (what it waits for) or 繼續 a small cute wiggle, nothing
  else (`_nudge`, 2026-10-24, the user's design; clicks on the bubble or floating button are not stray).
  A miss: the orange box reads 復原, the gray one 要念的是 with what was left out in red; 收回來了 repeats the
  step's line. Taskbar tray as Windows 11 lays it out (︿, app icon only for 簡約 (pinned) with tray.py's ring while listening, 英, Wi-Fi, volume,
  evenly spaced); floating button 24px in from the right like `floatbtn`. The guide's listening ripple leans with it.
  Chapters are generators yielding what they wait for: 打開記事本, 開麥克風 (click → bubble → listening), 念三句
  (2026-10-24, the user's design: a warm-up 今天天氣很好…; 爺爺的視力很好 settles it and is shown with a planted
  勢力; 連對面的招牌都看得清楚 joins the same sentence, then 勢力 → 視力 with a red flash), 定稿 (句號), 換行與復原
  (下一行: 換行 failed more often), 選字 (planted 請幫我定一張車票, fixed candidates; a wrong pick is put back to 定), 選取重講 (一張 → 兩張, the 選字 menu
  opening by itself over 一張 as in the app, the user told to let it be; then 今天天氣很好， selected and 刪除; a
  click dropping the selection before it is spoken over goes back to selecting it), 節日的節 (named by its example: 詞的字 read abstract; only 節 is typed, never
  the words said for it; the tutorial's own rule, no dictionary), 送出 (chat; the mic turns off), 關麥克風 (結束 or
  the floating button: 正在聽… 或 [the button]; the last lines name a few more commands). Independent of the core: its own microphone (`Ear`: level-based, a pause re-decodes the draft,
  the end judges it) and matching; only decoding is lent (`SettingsWindow.tutorial_decode` = `App._tutorial_decode`:
  commands boosted first on a short piece, as `_command_first`). A reading that passes takes the asked sentence's marks where
  its characters line up (`punctuated`: X-ASR writes ， only at a pause it heard). The strip drags the window. A reading under 80% alike (characters or toneless
  pinyin) stays typed and must be taken back with 復原 (nothing else goes on); after 3 misses, a closed mic or no
  model, 跳過這步. Text replacing a selection mid-line drops the recognizer's closing mark. The App rests
  (`_paused`) while it shows; closed midway it comes back at its chapter (each chapter starts from `_scene` then);
  nothing said there is kept (no 辨識紀錄, 選字記憶, 詞庫).
- 辨識紀錄 (`logbook.py`, `set_log`): one row per event, grouped per listening session, newest first, 40 built at
  first and 40 more near the scroll's end or from 顯示更早的紀錄 (all 300 at once took ~1s to open, 2026-10-22), heard vs the
  screen's change as a diff, details in the tooltip; copy icon on rows that settled text; an orange book (the 詞庫 tile's) when the 詞庫
  may have shaped the text (`logbook.bank_of`; good news, not a warning). Text fixed as typed is 定稿 (its tag and dot the text red a
  little deeper, #C8323E); a pause's re-decode that changed the text is 整句修正; speech typed at a new caret is
  plain 文字, the why in its tip (2026-10-21).
- 詞庫 tab: four collapsible sections, one open (`hotword_section`): 詞包, 詞庫列表, 選字記憶 (shown as
  這個ying3片是 → 這個影片是), 英文強制替換; each with its own remembered 排序.
- Glow (`glow.py`, off by default): 錄音紅 first (beside the mic look; 暖陽 冰藍 草本 together read as RGB), styles with editable parameters (`glow_edits`, 已編輯 + 恢復預設), up to 6 colors,
  edges (a style's parameter like the others, `glow.edges_for`, 2026-10-21; the preview shows only those), motions 柔光 / 波浪 / 流星 / 漣漪 (`glow_motion`); four click-through strips; colors by numpy LUT;
  moving motions at 48 fps unless 節流模式 (柔光 24). 流星's position is summed per frame (`EdgeGlow._lap`).
- 按鈕樣式 (`orbs.py`, `button_look`): mic + ten orb looks in the glow's colors (蝕光 the latest), drawn on a canvas
  1.4x the mic (`orbs.SCALE`), frames cached per loop phase, only while shown; 30 fps (15 with 節流模式). Hover
  grows to 1.12 with a spring (the preview's sample: only over the look, its widget is far bigger), not while
  listening (0.88 under the pointer read as no shrink) nor after a click until the pointer leaves; orbs play at 0.6x their loop at rest, 1.6x while listening (`orbs.IDLE_SPEED` /
  `ACTIVE_SPEED`, 2026-10-20). 光環 / 虹膜 middles take clicks (alpha 1/255 disc: fully clear pixels pass clicks).
- Sounds (`cues.py`, `artvoiceinput/cues/*.wav`, built by `dev/build_cues.py`): 12 sets, 無, 自定義; Blip default; the
  start sound's length is silenced for the VAD. 音量 (`cue_volume` 10-100%, default 80, a slider in the 提示音 title row,
  2026-10-21): scaled copies in `cache/cues`. Played from the wav file (winsound can't play memory async).
- ▶ 預覽 / ▶ 試聽 read 播放中… and are disabled while playing.

## Lessons and experiment results

- **Hotword biasing** (sherpa-onnx modified beam search adds the boost after the top `max_active_paths` cut): 12
  paths, Chinese score 5: 16/16, no false hits; 6 made 城市 → 程式; 8 broke English. Encoding: Simplified,
  characters space-separated; one unencodable word drops the whole list (check against tokens.txt; `bpe.vocab`
  exported from `bpe.model` by a small protobuf reader). 20k+ words: 熱詞 → 熱刺 (accuracy hurts before speed).
  English boosts: +4 little help, +5 breaks (DeepSeek → Deep) → spelling replacement after recognition instead.
  Two hotwords sounding alike and starting with the same character cancel out: 自訂 +5 beside 自定 at any score
  (even +0.01) wrote 自定 as with no biasing, so such a lowered word is not sent (`app._bias`, 2026-10-21; 自訂 beside
  自動 -3 and 程式 beside 城市 -3 were fine; 自訂 +5 beside 自動 +5 also lost one, not handled).
- **Command lab** (`dev/cmdlab`, 929 commands + 571 text pieces from the user's recordings): plain path 96.7%,
  padded boosted-first 98.7% (misses 31 → 10), 0 false triggers. X-ASR turns a command into English when the audio
  starts or ends without silence. Rejected: second X-ASR scoring (+260MB, confuses 換行/問號), keyword spotters
  (65-82%, false triggers on text mentioning commands), pinyin/CMUdict matching of decoded text, boost ≥8.
- **Punctuation at pauses**: 0.75s of a pause kept made the recognizer's marks a coin toss; 0.5s more fixed it.
- **CPU measurement**: measure on the real screen at the real frame rate (frames cost ~4x a busy benchmark loop;
  most glow cost is painting/compositing strips). Qt 6's `app.quit()` closes every window: wait with a `QEventLoop`.
  Measured: 柔光 ~17% of a core, 流星 ~50-59% at 48 fps; orbs ~1-3% steady.
- **Tried and dropped**: streaming X-ASR captions / typing as said (too slow, not better); preview box for drafts;
  following the caret by UIA (apps report it wrong); Bopomofo spelling (X-ASR hears symbol names as letters);
  「X改成Y」 (d59596c); jieba (mainland frequencies, missing words; 7593a98); SenseVoice / Qwen3-ASR second opinion
  (shared errors; Qwen 1.2GB); dictionary-only mishearing guesses (all wrong on 80 utterances); start-sound
  cut-out by cross-correlation (press-and-talk era).
- **Popups**: the lean redesign removed every popup but the 選字 menu and tray error notices; new popups get
  designed from scratch with the user. Colors (草稿反白 自訂, the glow's) are picked in `ui/colorpop.py`, a small
  card under the swatch: a hue ring round a square, no numbers, live; outside click keeps, Esc reverts (2026-10-22,
  Qt's color dialog dropped).

## Testing

- `dev/headless.py` runs the real App against a simulated text box (feed:WAV, op:PHRASE, clip:TEXT): default for
  tests. Audio: Windows TTS (zh-TW Hanhan, `dev/tts.ps1`) or the user's saved recordings (`recordings.py`,
  DATA_DIR/recordings with index.jsonl; development only, to be removed before release, keep it inside that module,
  `App._keep` and `save_recordings`). Saved recordings were decoded with that moment's 詞庫;
  press-and-talk ones (before 2026-10-14) still hold the start sound the app cut out.
- Never let a test write the user's real data files while their Art VoiceInput runs.
- `dev/e2e.py` types into real Notepad / Windows Terminal: only when the user is away (it once typed into their
  Notepad document).
- The tutorial: `dev/tutorial_check.py OUT [--dark] [--miss]` walks it end to end (QTest clicks, `Tutorial.hear`)
  saving a screenshot per step; `dev/tutorial_asr.py` speaks each asked phrase by TTS through the real recognizer
  and the tutorial's rules; `dev/settings_preview.py tutorialN` opens it at chapter N.
- Other probes: `dev/term_probe.py`, `dev/highlight_spike.py` / `.html`, `dev/pack_candidates.py`.

## Open questions

- Not yet tried in a real terminal: the spoken edit commands. Not tried with the draft mark: Notepad, LINE,
  Electron apps, scrolling while drafting.
