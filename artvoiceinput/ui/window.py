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
        self.theme.changed.connect(self._theme_changed)

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
        for frame in self.pages.values():
            if hasattr(frame.page, "restyle"):
                frame.page.restyle()

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
        super().showEvent(e)

    def hideEvent(self, e):
        self.mic_page.stop_capture()
        super().hideEvent(e)

    def changeEvent(self, e):
        """Back from editing a pack file: its new terms shown."""
        super().changeEvent(e)
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.bank_page.reload_if_packs_changed()
