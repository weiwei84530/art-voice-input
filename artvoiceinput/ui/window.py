"""SettingsWindow: the redesigned settings (shell.py) with its six pages, and the interface the app uses (the
signals and methods the old SettingsDialog had)."""
from PySide6.QtCore import QEvent, Signal

from .. import packs
from . import theme
from .shell import Shell


class SettingsWindow(Shell):
    applied = Signal()
    glow_preview = Signal(str)      # a glow style picked or changed: shown for a moment
    capture_hotkey = Signal(bool)   # 快捷鍵: take the next press (True), or stop waiting for it
    clear_log = Signal()            # 清除紀錄 on the 辨識紀錄 page
    wizard_heard = Signal(object)   # the setup wizard heard speech (16 kHz audio): App decodes it (wizard_said)

    def __init__(self, cfg, hotwords, memory):
        super().__init__(theme.Theme(cfg.theme))
        self.cfg, self.hotwords, self.memory = cfg, hotwords, memory
        self._loading = False
        self._status = "就緒"
        from .page_bank import BankPage
        from .page_cmd import CmdPage
        from .page_log import LogPage
        from .page_look import LookPage
        from .page_mic import MicPage
        from .page_sys import SysPage
        self.mic_page, self.look_page = MicPage(self), LookPage(self)
        self.cmd_page, self.bank_page = CmdPage(self), BankPage(self)
        self.log_page, self.sys_page = LogPage(self), SysPage(self)
        for key, page in (("mic", self.mic_page), ("look", self.look_page), ("cmd", self.cmd_page),
                          ("bank", self.bank_page), ("log", self.log_page), ("sys", self.sys_page)):
            self.add_page(key, page)
            page.installEventFilter(self)
        self.theme.changed.connect(self._theme_changed)
        self.wizard = None

    # --- shared by the pages ---
    def save(self):
        """A setting changed: saved, and the app applies it."""
        if self._loading:
            return
        self.cfg.save()
        self.applied.emit()
        self.refresh_tiles()

    def data_changed(self):
        """Settings and 詞庫 replaced at once (匯入, 還原預設)."""
        self.cfg.save()
        self.hotwords.set_packs(packs.words_for(self.cfg.packs), packs.PCT)
        self.theme.set_mode(self.cfg.theme)
        self.load_values()
        self.applied.emit()

    def refresh_tiles(self):
        for key, tile in self.tiles.items():
            page = self.pages[key].page
            tile.desc = page.summary() if hasattr(page, "summary") else ""
            tile.update()

    def _theme_changed(self):
        """Pages in view are redrawn now, the others when shown: rebuilding a long 辨識紀錄 unseen held the window
        long enough that the cross-fade of 外觀模式 never got painted (2026-10-21)."""
        for frame in self.pages.values():
            if hasattr(frame.page, "restyle"):
                if frame.page.isVisible():
                    frame.page.restyle()
                else:
                    frame.page.restyle_due = True

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Show and getattr(obj, "restyle_due", False):
            obj.restyle_due = False
            obj.restyle()
        return super().eventFilter(obj, e)

    # --- the app's interface ---
    def load_values(self):
        self._loading = True
        try:
            for frame in self.pages.values():
                frame.page.load()
        finally:
            self._loading = False
        self.refresh_tiles()

    def set_status(self, text: str):
        """The app's state (就緒, 載入模型中 …) on the brand block; other messages on the 系統 page."""
        if not text:
            return
        if text in ("就緒",) or text.startswith(("下載模型中", "載入模型中", "模型載入失敗")):
            self._status = text
            self.brand.status = text
            self.brand.update()
        else:
            self.sys_page.notice(text)

    def set_listening(self, on: bool):
        self.look_page.set_listening(on)

    def set_log(self, sessions):
        self.log_page.set_log(sessions)
        self.tiles["log"].desc = self.log_page.summary()
        self.tiles["log"].update()

    def refresh_hotwords(self):
        self.bank_page.load()
        self.refresh_tiles()

    def hotkey_captured(self, spec):
        self.mic_page.hotkey_captured(spec)

    def showEvent(self, e):
        if not e.spontaneous():   # opened again, not restored from the taskbar (that keeps the page)
            self.show_home_now()
            if not self.cfg.setup_done and (self.wizard is None or self.wizard.isHidden()):
                self.start_wizard()
        super().showEvent(e)

    # --- the setup wizard ---
    def start_wizard(self):
        """The wizard over the window from its first step (first launch, 清空並重新設定)."""
        from .wizard import Wizard
        if self.wizard is None:
            self.wizard = Wizard(self)
            self.wizard.mic_step.heard_audio.connect(self.wizard_heard.emit)
            self.wizard.finished.connect(self._wizard_done)
        if self.isVisible():
            from .kit import crossfade
            crossfade(self, 320)
        self.show_home_now()
        self.wizard.begin()
        self.wizard.show()
        self.wizard.raise_()
        self.min_button.raise_()
        self.close_button.raise_()

    def show_packs(self):
        """詞庫's 詞包 section (a pack hint clicked: the tray notice or its 辨識紀錄 row)."""
        if self.wizard is not None and self.wizard.isVisible():
            return
        self.show_home_now()
        self.bank_page.tabs.set("packs")
        self.bank_page._pick_tab("packs")
        self.open_page("bank")

    def wizard_said(self, text):
        if self.wizard is not None:
            self.wizard.mic_step.show_said(text)

    def _wizard_done(self):
        self.data_changed()   # the preset and packs saved and applied
        self.refresh_tiles()

    def hideEvent(self, e):
        self.mic_page.stop_capture()
        super().hideEvent(e)

    def changeEvent(self, e):
        """Back from editing a pack file: its new terms shown."""
        super().changeEvent(e)
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.bank_page.reload_if_packs_changed()
