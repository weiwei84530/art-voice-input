"""The focused app's selection, the text around its caret and the English terms on screen, read through the
platform's accessibility API (win/selection.py: UI Automation; mac/selection.py: the Accessibility API). This module
holds what both share and picks the platform's functions."""
import re
import threading
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Selection:
    text: str
    before: str       # rest of the line before the selection
    after: str        # rest of the line after the selection
    app: str          # process name, e.g. chrome.exe
    rect: tuple | None = None   # selection bounds (x, y, w, h) in physical screen pixels (where menus open)
    term: tuple | None = None   # terminal: screen point of the selection's last character



# English terms on screen bias the recognizer toward them (worktree, LLM, sherpa-onnx in a terminal).
# Common words are left out: boosting them only risks inserting them.
_TERM = re.compile(r"(?<![A-Za-z0-9_.])[A-Za-z][A-Za-z0-9]*(?![A-Za-z0-9_]|\.[A-Za-z])")
_COMMON = set("""the and for you that this with from have are was were will would could should there their
what when where which while about after before again because being between both each into just like make
more most much must only other over same some such than then them they these those through under until very
your yours also been does done doing here how its itself our out own down off once all any can did don few
has had her him his not now nor too yes who whom why let may might new old use used using file files line
lines code text true false null none return print import class function def else elif self error value
name type data list open close save edit view help tools window select click press enter""".split())
_MAX_TERMS = 40
_HASH = re.compile(r"[0-9a-f]{7,40}")   # a git commit (afe5559): letters and digits nobody says (2026-10-21)


def terms_in(text: str) -> list[str]:
    """Distinctive English terms in text, most frequent first: acronyms, CamelCase and words with digits
    always; other words of 5+ letters only when they appear at least twice. Dotted names (ranges.GetText) are
    skipped: nobody says them aloud."""
    counts = Counter(m.group(0) for m in _TERM.finditer(text))
    out = []
    for w, n in counts.most_common():
        if len(w) < 3 or w.casefold() in _COMMON or (_HASH.fullmatch(w) and any(c.isdigit() for c in w)):
            continue
        strong = any(c.isupper() for c in w[1:]) or any(c.isdigit() for c in w)
        if strong or (len(w) >= 5 and n >= 2):
            out.append(w)
        if len(out) == _MAX_TERMS:
            break
    return out


@dataclass
class Context:
    selection: Selection | None = None
    terms: list[str] = field(default_factory=list)
    caret: tuple[str, str] | None = None   # without a selection: the line's text before and after the caret


def read_context() -> Context:
    """The focused app's selection (see read_selection), else the text around its caret, and the English terms
    visible in it."""
    ctx = Context()
    ctx.selection = read_selection()
    if ctx.selection is None:
        ctx.caret = read_caret()
    ctx.terms = terms_in(visible_text())
    return ctx


class ContextProbe:
    """Reads the selection and on-screen terms on a background thread so a slow app does not delay the
    recording start."""

    def __init__(self):
        self._result = Context()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self._result = read_context()

    def result(self, timeout: float = 2.0) -> Context:
        self._thread.join(timeout)
        return self._result


from .system import MAC   # noqa: E402  (the platform modules import Selection from here)

if MAC:
    from .mac.selection import (caret_rect, draft_rects, focus_editable, focus_holds, focus_info,  # noqa: E402,F401
                                move_cursor_after, read_caret, read_selection, term_watcher, terminal_in_front,
                                visible_text)
else:
    from .win.selection import (caret_rect, draft_rects, focus_editable, focus_holds, focus_info,  # noqa: E402,F401
                                move_cursor_after, read_caret, read_selection, term_watcher, terminal_in_front,
                                visible_text)
