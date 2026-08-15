"""The RGB backlight: light in the gaps between the keys.

The obvious way to light a keyboard is to have each key draw its own colour.
That was the first attempt and it does not work. Eighty-three keycaps are
eighty-three widgets, and repainting all of them costs about 55 ms a frame --
more than the frame it has to fit in, and nearly all of it Qt's per-widget
overhead rather than any drawing. A keyboard that sits on screen all day cannot
spend half a core on a picture.

So the light is not part of the keys at all. It is one layer, painted by the
window underneath them, in two pieces that are cheap for opposite reasons:

* a **mask**, built once per layout, with every bloom drawn in white. All the
  expensive antialiased path work happens here, and only when the keyboard is
  resized or restyled.
* a **rainbow**, painted every frame as a single linear gradient through that
  mask. Moving the light is then moving a gradient's origin, which costs the
  same whether there are ten keys or a thousand.

The last piece is what makes it cheap enough to leave running: the lit region
is cut back to *outside* every keycap, so a frame of the wave damages only the
gaps between them. Qt repaints a widget whenever the damaged region touches it,
and a region that stopped exactly at each cap's border would still clip through
all of them and drag every key into every frame. One pixel of clearance took
the measured cost from 20% of a core to 5%.

What that costs is any wash of colour over the face of a cap, and it is no loss
worth arguing about: a wash over the face is a wash over the legend, and this
is a keyboard for people who need to read it.

One hard-won note, because nothing about it is visible in an offscreen render:
this window is translucent, and everything drawn into it has to carry real
alpha. ``QPixmap(size)`` does not -- on Windows it comes back as opaque RGB32 --
and compositing the mask into a surface with no alpha channel produced a light
that punched the desktop straight through the gaps in the keyboard. The layer
is an explicitly premultiplied QImage for that reason.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import (
    QColor, QGradient, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRegion,
)

from . import theme

#: The bloom around a lit key: how many rings out it reaches, and how bright
#: the innermost is. Ring 1 hugs the cap and reads as its lit rim; the rest
#: fade out into the gap. The falloff is gentler than the inverse square real
#: light would give, because the light here only has the width of a gap to
#: fall off across, and an honest inverse square over five pixels is a bright
#: line and then nothing.
GLOW_STEPS = 7
GLOW_ALPHA = 255
GLOW_FALLOFF = 1.45

#: Clearance kept between the lit region and the keycaps. See the note above:
#: this single pixel is the whole performance story.
CLEARANCE = 1

#: Sampling of the hue circle for the gradient. Twelve stops is past the point
#: where another one is visible.
HUE_STOPS = 12

#: The light is rendered at half size and scaled up. It is a soft bloom with no
#: detail to lose, and a quarter of the pixels is a quarter of the work on
#: every frame. If anything the softer edge looks more like light.
SCALE = 0.5


class Backlight:
    """Builds and paints the lit layer for a board of keys."""

    def __init__(self) -> None:
        self._mask: QPixmap | None = None
        self._layer: QPixmap | None = None
        self.region = QRegion()      # the part of the window the light is in
        self._size = (0, 0)
        self._unit = (60.0, 55.0)    # key size in pixels, the wave's scale

    # -- shape -------------------------------------------------------------

    def invalidate(self) -> None:
        self._mask = None
        self.region = QRegion()

    def rebuild(self, size, sources, unit, bounds) -> None:
        """Trace the light over the keys as they are now laid out.

        ``sources`` are callables returning ``(rect, corner radius)`` pairs in
        window coordinates; ``unit`` is the size of one key, which sets the
        scale of the wave; ``bounds`` is the drawn card, which the light is
        held inside.

        The bounds are not cosmetic, and a rectangle will not do. The window is
        translucent, so anything outside the drawn card is genuinely
        transparent; a bloom allowed to reach past a rounded corner puts a hole
        in the keyboard with the desktop behind it.
        """
        self.invalidate()
        self._size = (max(1, size.width()), max(1, size.height()))
        self._unit = (max(1.0, unit[0]), max(1.0, unit[1]))
        if not theme.skin().rgb:
            return

        width, height = self._size
        mask = QPixmap(max(1, round(width * SCALE)), max(1, round(height * SCALE)))
        mask.fill(QColor(0, 0, 0, 0))
        painter = QPainter(mask)
        painter.setRenderHint(QPainter.Antialiasing)
        # Everything below is written in window coordinates; the painter does
        # the shrinking.
        painter.scale(SCALE, SCALE)

        white = QColor(255, 255, 255)
        glow = theme.skin().glow
        region = QRegion()
        for source in sources:
            for rect, radius in source():
                box = QRectF(rect)
                for step in range(GLOW_STEPS, 0, -1):
                    white.setAlpha(min(255, round(
                        GLOW_ALPHA * glow / step ** GLOW_FALLOFF)))
                    painter.setPen(QPen(white, 2.4))
                    painter.drawRoundedRect(
                        box.adjusted(-step, -step * 0.7, step, step * 1.4),
                        radius + step, radius + step)
                lit = rect.adjusted(-GLOW_STEPS - 2, -GLOW_STEPS - 2,
                                    GLOW_STEPS + 2, GLOW_STEPS + 3)
                region += QRegion(lit)
                region -= QRegion(rect.adjusted(-CLEARANCE, -CLEARANCE,
                                                CLEARANCE, CLEARANCE))
        painter.end()
        self._mask = mask
        # Clipped to the card as drawn -- corners included, which a bounding
        # rectangle would miss.
        card = QPainterPath()
        card.addRoundedRect(QRectF(bounds), theme.skin().window_radius,
                            theme.skin().window_radius)
        self.region = region & QRegion(card.toFillPolygon().toPolygon())

    # -- painting ----------------------------------------------------------

    def _rainbow(self) -> QLinearGradient:
        """A repeating rainbow running across and down the board.

        Its direction and period come from the same two numbers as
        :func:`theme.key_hue`, so the light lands on the keys the way that
        function describes: a shallow diagonal band, much wider than one key,
        drifting with the phase.
        """
        unit_w, unit_h = self._unit
        per_x = theme.COLUMN_SHIFT / unit_w      # hue per pixel across
        per_y = theme.ROW_SHIFT / unit_h         # hue per pixel down
        rate = math.hypot(per_x, per_y)
        period = 1.0 / rate                      # pixels for a full hue circle
        dx, dy = per_x / rate, per_y / rate      # unit vector along the wave

        shift = theme.phase() * period
        start = QPointF(-dx * shift, -dy * shift)
        grad = QLinearGradient(start, QPointF(start.x() + dx * period,
                                              start.y() + dy * period))
        grad.setSpread(QGradient.RepeatSpread)
        for i in range(HUE_STOPS + 1):
            grad.setColorAt(i / HUE_STOPS, theme.wave_colour(i / HUE_STOPS))
        return grad

    def paint(self, painter: QPainter) -> None:
        """Draw the light. Cheap; the expensive part was done in rebuild()."""
        if self._mask is None:
            return
        if self._layer is None or self._layer.size() != self._mask.size():
            # A QImage in an explicitly premultiplied format, not a QPixmap:
            # QPixmap(size) comes back as opaque RGB32 on Windows, with no
            # alpha channel for the mask composite below to write into. The
            # light then had no transparency at all, and painting it punched
            # the desktop through the gaps in the keyboard.
            self._layer = QImage(self._mask.size(),
                                 QImage.Format_ARGB32_Premultiplied)

        into = QPainter(self._layer)
        # Source, not SourceOver: this overwrites every pixel of the layer, so
        # there is no need to clear it first.
        into.setCompositionMode(QPainter.CompositionMode_Source)
        into.scale(SCALE, SCALE)
        into.fillRect(QRect(0, 0, *self._size), self._rainbow())
        # Then keep only what the mask says is lit -- one composite over the
        # whole board, rather than a tinted draw per key.
        into.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        into.resetTransform()
        into.drawPixmap(0, 0, self._mask)
        into.end()

        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawImage(QRect(0, 0, *self._size), self._layer)
        painter.restore()
