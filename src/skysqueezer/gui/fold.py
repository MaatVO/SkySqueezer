"""A fold: a row that always shows a badge, a title, one line and a status, and opens into a panel.

Used for the New job steps, the jobs list and the keys, so the three tabs read the same way. The header is a real
button inside a heading (the WAI accordion pattern): Enter and Space work, and ``aria-expanded`` says the state.
"""

from collections.abc import Callable

from nicegui import ui
from nicegui.elements.mixins.text_element import TextElement

BADGES = ("active", "done", "warn", "err", "plain", "ok", "muted")
TONES = ("ok", "warn", "err", "muted", "accent")


class Span(TextElement):
    """Text in a ``<span>``: a button's content must be phrasing content, which ``ui.label``'s ``<div>`` is not."""

    def __init__(self, text: str = "") -> None:
        super().__init__(tag="span", text=text)


class Fold:
    """``on_click`` gets the fold (default: open or close it). ``actions``: the header's button text when closed
    and when open ("" hides it). ``hide_line_open``: the one-line summary goes away while the panel shows it all."""

    def __init__(self, title: str, *, badge: str = "", icon: str | None = None, mark: str = "", level: int = 2,
                 on_click: Callable[["Fold"], None] | None = None, opened: bool = False,
                 actions: tuple[str, str] = ("Open", "Hide"), hide_line_open: bool = False,
                 lead: Callable[[], None] | None = None, title_classes: str = "") -> None:
        self.opened = None
        self.actions = actions
        self.hide_line_open = hide_line_open
        self._shown: dict = {}
        self.root = ui.element("section").classes("edh-fold w-full min-w-0" + (f" edh-tour-{mark}" if mark else ""))
        with self.root:
            with ui.element(f"h{level}").classes("edh-fold-h"):
                self.head = ui.element("button").classes("edh-fold-head").props("type=button")
                with self.head:
                    self.badge = ui.element("span").classes("edh-fold-badge")
                    with self.badge:
                        self.badge_text = Span(badge)
                        self.badge_icon = ui.icon(icon or "check", size="18px")
                    self.badge_text.set_visibility(not icon)
                    self.badge_icon.set_visibility(bool(icon))
                    if lead:
                        lead()
                    with ui.element("span").classes("edh-fold-text"):
                        with ui.element("span").classes("edh-fold-titlerow"):
                            self.title = Span(title).classes("edh-fold-title " + title_classes)
                            self.tag = Span("").classes("edh-fold-tag")
                        self.line = Span("").classes("edh-fold-line")
                    self.status = Span("").classes("edh-fold-status")
                    self.action = Span("").classes("edh-fold-action")
            self.body = ui.column().classes("edh-fold-body w-full gap-3")
        self.body.props(f"id={self.root.html_id}-body role=region")
        self.head.props(f"aria-controls={self.root.html_id}-body")
        self.head.on("click", lambda: on_click(self) if on_click else self.set_open(not self.opened))
        self.set(tag="", line="", status="")
        self.set_open(opened)

    def set_open(self, opened: bool) -> None:
        if opened == self.opened:
            return
        self.opened = opened
        self.body.set_visibility(opened)
        self.root.classes(add="edh-fold-open") if opened else self.root.classes(remove="edh-fold-open")
        self.head.props(f"aria-expanded={'true' if opened else 'false'}")
        text = self.actions[1 if opened else 0]
        self.action.text = text
        self.action.set_visibility(bool(text))
        self.line.set_visibility(bool(self._shown.get("line")) and not (opened and self.hide_line_open))

    def set(self, **kw) -> None:
        """Change what the header shows; only what differs is sent to the browser.
        line, set_line (True: a value, False: a hint), tag, status, tone, badge (BADGES states, space separated),
        badge_text, icon."""
        new = {k: v for k, v in kw.items() if self._shown.get(k, object()) != v}
        if not new:
            return
        self._shown.update(new)
        if "line" in new:
            self.line.text = new["line"]
            self.line.set_visibility(bool(new["line"]) and not (self.opened and self.hide_line_open))
        if "set_line" in new:
            self.line.classes(add="edh-fold-set") if new["set_line"] else self.line.classes(remove="edh-fold-set")
        if "tag" in new:
            self.tag.text = new["tag"]
            self.tag.set_visibility(bool(new["tag"]))
        if "status" in new:
            self.status.text = new["status"]
            self.status.set_visibility(bool(new["status"]))
        if "tone" in new:
            self.status.classes(remove=" ".join(f"edh-tone-{t}" for t in TONES))
            if new["tone"]:
                self.status.classes(add=f"edh-tone-{new['tone']}")
        if "badge" in new:
            self.badge.classes(remove=" ".join(f"edh-badge-{b}" for b in BADGES))
            for b in (new["badge"] or "").split():  # "plain ok": no border, a green icon
                self.badge.classes(add=f"edh-badge-{b}")
        if "badge_text" in new:
            self.badge_text.text = new["badge_text"]
        if "icon" in new:
            if new["icon"]:
                self.badge_icon.name = new["icon"]
            self.badge_text.set_visibility(not new["icon"])
            self.badge_icon.set_visibility(bool(new["icon"]))

    def scroll_into_view(self) -> None:
        ui.run_javascript(f"document.getElementById('{self.root.html_id}')"
                          "?.scrollIntoView({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)')"
                          ".matches ? 'auto' : 'smooth'})")


CSS = """
/* folds: a row that opens into a panel (New job steps, jobs, keys) */
.edh-fold { background: var(--edh-surface); border: 1px solid var(--edh-line); border-radius: var(--edh-r); isolation: isolate;
  scroll-margin-top: 88px; }
.edh-fold-h { margin: 0; font: inherit; letter-spacing: normal; line-height: inherit; }
.edh-fold-head { all: unset; box-sizing: border-box; display: flex; align-items: center; gap: 16px; width: 100%;
  padding: 16px 20px; cursor: pointer; border-radius: var(--edh-r); color: var(--edh-text); font-size: var(--edh-fs-sm); line-height: 1.5; }
.edh-fold-head:hover { background: var(--edh-surface-2); }
.edh-fold-pinned.edh-fold-open > .edh-fold-h .edh-fold-head { cursor: default; }
.edh-fold-pinned.edh-fold-open > .edh-fold-h .edh-fold-head:hover { background: transparent; }
.edh-fold-head:focus-visible { outline: 2px solid var(--edh-accent-text); outline-offset: -2px; }
.edh-fold-badge { flex: none; width: 28px; height: 28px; box-sizing: border-box; border-radius: 4px; border: 1px solid #3d4757;
  color: var(--edh-muted); display: flex; align-items: center; justify-content: center; font-weight: 500; }
.edh-fold-badge.edh-badge-active { background: var(--edh-accent); border-color: var(--edh-accent); color: var(--edh-bg); }
.edh-fold-badge.edh-badge-done { border-color: var(--edh-ok); color: var(--edh-ok); }
.edh-fold-badge.edh-badge-warn { border-color: var(--edh-warn); color: var(--edh-warn); }
.edh-fold-badge.edh-badge-err { border-color: var(--edh-err); color: var(--edh-err); }
.edh-fold-badge.edh-badge-ok { color: var(--edh-ok); } .edh-fold-badge.edh-badge-muted { color: var(--edh-muted); }
.edh-fold-badge.edh-badge-plain { border-color: transparent; }
.edh-fold-badge .q-icon { color: inherit; }
.edh-fold-text { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; }
.edh-fold-titlerow { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.edh-fold-title { font-size: var(--edh-fs-md); font-weight: 500; overflow-wrap: anywhere; }
.edh-fold-open .edh-fold-title.edh-fold-grow { font-size: var(--edh-fs-lg); }
.edh-fold-tag { font-size: var(--edh-fs-xs); color: var(--edh-muted); white-space: nowrap; }
.edh-fold-line { font-size: .8125rem; color: var(--edh-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.edh-fold-line.edh-fold-set { color: var(--edh-text); }
.edh-fold-status { flex: none; font-size: var(--edh-fs-xs); font-weight: 500; color: var(--edh-muted); white-space: nowrap;
  font-variant-numeric: tabular-nums; }
.edh-tone-ok { color: var(--edh-ok); } .edh-tone-warn { color: var(--edh-warn); } .edh-tone-err { color: var(--edh-err); }
.edh-tone-muted { color: var(--edh-muted); } .edh-tone-accent { color: var(--edh-accent-text); }
.edh-fold-action { flex: none; padding: 3px 14px; border: 1px solid #3d4757; border-radius: 3px; color: var(--edh-accent-text);
  font-weight: 500; }
.edh-fold-head:hover .edh-fold-action { border-color: var(--edh-accent-text); }
.edh-fold-body { padding: 0 24px 20px 64px; }
.edh-fold-foot { border-top: 1px solid var(--edh-line); padding-top: 12px; margin-top: 4px; }
.edh-folds { display: flex; flex-direction: column; gap: 8px; width: 100%; min-width: 0; }
@media (max-width: 639px) {
  .edh-fold-head { padding: 12px 16px; gap: 12px; }
  .edh-fold-body { padding: 0 16px 16px; }
  .edh-fold-action { display: none; }
}
"""
