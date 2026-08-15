"""Lays keys out on a grid measured in key units.

A stretching QLayout cannot express a keyboard: Enter is two rows tall, Space is
six units wide, and every row must stay in column with the ones above it.
Positioning the keys directly from a unit grid is both simpler and exact, and it
lets the whole keyboard scale to any window size without the rows drifting
apart.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget

from ..layouts.albanian import Key
from .keycap import KeyCap

GAP = 3


class UnitGrid(QWidget):
    """A block of keys whose rows are ``width_units`` wide."""

    activated = Signal(object)
    repeated = Signal(object)

    def __init__(self, rows: list[list[Key]], width_units: float,
                 row_count: int | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.width_units = width_units
        self.row_count = row_count or len(rows)
        self._rows: list[list[Key]] = []
        self._caps: list[tuple[KeyCap, float, float]] = []  # cap, x_units, y_units
        self._style = dict(font_scale=1.0, dwell=False, dwell_ms=900,
                           repeat=True, repeat_delay=500, repeat_rate=60)
        self.set_rows(rows)

    # -- construction ------------------------------------------------------

    def set_rows(self, rows: list[list[Key]]) -> None:
        for cap, _x, _y in self._caps:
            cap.setParent(None)
            cap.deleteLater()
        self._caps.clear()
        self._rows = rows

        for r, row in enumerate(rows):
            x = 0.0
            for key in row:
                cap = KeyCap(key, self)
                cap.configure(**self._style)
                cap.activated.connect(self.activated)
                cap.repeated.connect(self.repeated)
                cap.show()
                self._caps.append((cap, x, float(r)))
                x += key.w
        self._relayout()

    # -- appearance --------------------------------------------------------

    def apply_style(self, *, font_scale: float, dwell: bool, dwell_ms: int,
                    repeat: bool, repeat_delay: int, repeat_rate: int) -> None:
        self._style = dict(font_scale=font_scale, dwell=dwell, dwell_ms=dwell_ms,
                           repeat=repeat, repeat_delay=repeat_delay,
                           repeat_rate=repeat_rate)
        for cap, _x, _y in self._caps:
            cap.configure(**self._style)

    def set_modifier_state(self, shift: bool, altgr: bool) -> None:
        for cap, _x, _y in self._caps:
            cap.set_modifier_state(shift, altgr)

    def caps_for_action(self, action: str) -> list[KeyCap]:
        return [cap for cap, _x, _y in self._caps if cap.key.action == action]

    def all_caps(self) -> list[KeyCap]:
        return [cap for cap, _x, _y in self._caps]

    # -- geometry ----------------------------------------------------------

    def _relayout(self) -> None:
        if not self._caps:
            return
        unit_w = self.width() / self.width_units
        unit_h = self.height() / self.row_count
        for cap, x, y in self._caps:
            cap.set_unit_size(unit_w, unit_h)
            cap.setGeometry(
                round(x * unit_w),
                round(y * unit_h),
                max(1, round(cap.key.w * unit_w) - GAP),
                max(1, round(cap.key.h * unit_h) - GAP),
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()
