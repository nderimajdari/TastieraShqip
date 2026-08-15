"""Options and Help dialogs.

The interface language is Albanian throughout: the people this keyboard is for
are writing in Albanian, and an assistive tool that explains itself in a foreign
language is one more barrier.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QGroupBox,
    QLabel, QMessageBox, QPushButton, QSlider, QSpinBox, QTextBrowser, QVBoxLayout,
)

from .. import APP_NAME, __version__
from ..config import Settings
from ..prediction.engine import PredictionEngine
from . import theme


def close_box(dialog: QDialog) -> QDialogButtonBox:
    """A Close button reading "Mbyll".

    Qt labels its standard buttons from the system language, which on an
    otherwise Albanian dialog leaves one stray English word.
    """
    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    buttons.button(QDialogButtonBox.Close).setText("Mbyll")
    buttons.rejected.connect(dialog.accept)
    buttons.accepted.connect(dialog.accept)
    return buttons


class OptionsDialog(QDialog):
    settings_changed = Signal()

    def __init__(self, settings: Settings, engine: PredictionEngine, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.engine = engine
        self.setWindowTitle(f"{APP_NAME} — Opsionet")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(self._prediction_group())
        layout.addWidget(self._accessibility_group())
        layout.addWidget(self._appearance_group())

        layout.addWidget(close_box(self))

    # -- helpers -----------------------------------------------------------

    def _changed(self) -> None:
        self.settings_changed.emit()

    def _checkbox(self, label: str, value: bool, attr: str) -> QCheckBox:
        box = QCheckBox(label)
        box.setChecked(value)

        def on_toggle(state: bool) -> None:
            setattr(self.settings, attr, bool(state))
            self._changed()

        box.toggled.connect(on_toggle)
        return box

    def _spin(self, attr: str, lo: int, hi: int, value: int,
              suffix: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setValue(value)
        if suffix:
            spin.setSuffix(suffix)

        def on_change(v: int) -> None:
            setattr(self.settings, attr, v)
            self._changed()

        spin.valueChanged.connect(on_change)
        return spin

    def _combo(self, attr: str, choices: list[tuple[str, str]],
               value: str) -> QComboBox:
        """A drop-down over ``(key, label)`` pairs storing the key."""
        combo = QComboBox()
        for key, label in choices:
            combo.addItem(label, key)
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))

        def on_change(i: int) -> None:
            setattr(self.settings, attr, combo.itemData(i))
            self._changed()

        combo.currentIndexChanged.connect(on_change)
        return combo

    def _slider(self, attr: str, lo: int, hi: int, value: int, suffix: str = "",
                scale: float = 1.0,
                display_scale: float | None = None) -> tuple[QSlider, QLabel]:
        """A slider whose stored value and displayed value may differ in unit.

        Opacity is stored as a fraction but read by people as a percentage, so
        the two scales are kept separate rather than dividing by a hundred twice.
        """
        shown = scale if display_scale is None else display_scale
        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(value)
        readout = QLabel(f"{value * shown:g}{suffix}")
        readout.setMinimumWidth(56)

        def on_move(v: int) -> None:
            setattr(self.settings, attr, v * scale if scale != 1.0 else v)
            readout.setText(f"{v * shown:g}{suffix}")
            self._changed()

        slider.valueChanged.connect(on_move)
        return slider, readout

    # -- groups ------------------------------------------------------------

    def _prediction_group(self) -> QGroupBox:
        box = QGroupBox("Parashikimi i fjalëve")
        grid = QGridLayout(box)
        s = self.settings

        grid.addWidget(self._checkbox("Aktivizo parashikimin", s.prediction_enabled,
                                      "prediction_enabled"), 0, 0, 1, 3)
        grid.addWidget(self._checkbox("Shto hapësirë pas fjalës së zgjedhur",
                                      s.auto_space, "auto_space"), 1, 0, 1, 3)
        grid.addWidget(self._checkbox("Mëso nga fjalët që shkruaj",
                                      s.learn_from_typing, "learn_from_typing"), 2, 0, 1, 3)

        grid.addWidget(QLabel("Fjalë për rresht"), 3, 0)
        grid.addWidget(self._spin("suggestion_count", 3, 10, s.suggestion_count), 3, 1)

        grid.addWidget(QLabel("Rreshta sugjerimesh"), 4, 0)
        grid.addWidget(self._spin("suggestion_rows", 1, 3, s.suggestion_rows), 4, 1)
        hint = QLabel("Më shumë rreshta = më shumë fjalë për të zgjedhur,\n"
                      "por edhe më shumë vend të zënë në ekran.")
        hint.setStyleSheet(f"color:{theme.palette().text_faint};")
        grid.addWidget(hint, 4, 2)

        clear = QPushButton("Fshi fjalorin tim personal")
        clear.clicked.connect(self._clear_user_model)
        grid.addWidget(clear, 5, 0, 1, 3)

        words = self.engine.user.unigram
        info = QLabel(f"Fjalor personal: {len(words):,} fjalë  •  "
                      f"Fjalor shqip: {self.engine.model.vocabulary_size:,} fjalë")
        info.setStyleSheet(f"color:{theme.palette().text_faint};")
        grid.addWidget(info, 6, 0, 1, 3)
        return box

    def _clear_user_model(self) -> None:
        answer = QMessageBox.question(
            self, "Fshi fjalorin personal",
            "Të fshihen të gjitha fjalët e mësuara nga shkrimi juaj?\n"
            "Fjalori i përgjithshëm shqip nuk preket.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.engine.user.clear()
            self._changed()

    def _accessibility_group(self) -> QGroupBox:
        box = QGroupBox("Qasshmëria")
        grid = QGridLayout(box)
        s = self.settings

        grid.addWidget(self._checkbox(
            "Zgjedhje me qëndrim — shtyp tastin duke mbajtur kursorin mbi të",
            s.dwell_enabled, "dwell_enabled"), 0, 0, 1, 3)

        grid.addWidget(QLabel("Koha e qëndrimit"), 1, 0)
        slider, readout = self._slider("dwell_ms", 300, 3000, s.dwell_ms, " ms")
        grid.addWidget(slider, 1, 1)
        grid.addWidget(readout, 1, 2)

        grid.addWidget(self._checkbox("Përsërit tastin kur mbahet i shtypur",
                                      s.hold_to_repeat, "hold_to_repeat"), 2, 0, 1, 3)

        grid.addWidget(QLabel("Vonesa para përsëritjes"), 3, 0)
        slider, readout = self._slider("repeat_delay_ms", 150, 2000,
                                       s.repeat_delay_ms, " ms")
        grid.addWidget(slider, 3, 1)
        grid.addWidget(readout, 3, 2)

        grid.addWidget(QLabel("Shpejtësia e përsëritjes"), 4, 0)
        slider, readout = self._slider("repeat_rate_ms", 20, 400, s.repeat_rate_ms, " ms")
        grid.addWidget(slider, 4, 1)
        grid.addWidget(readout, 4, 2)
        return box

    def _appearance_group(self) -> QGroupBox:
        box = QGroupBox("Pamja")
        grid = QGridLayout(box)
        s = self.settings

        grid.addWidget(QLabel("Ngjyrat"), 0, 0)
        grid.addWidget(self._combo("theme", [("dark", "E errët"),
                                             ("light", "E çelët")], s.theme), 0, 1)

        grid.addWidget(QLabel("Ngjyra e theksit"), 1, 0)
        grid.addWidget(self._combo(
            "accent", [(key, label) for key, (label, _l, _d) in theme.ACCENTS.items()],
            s.accent), 1, 1)

        grid.addWidget(QLabel("Madhësia e shkronjave"), 2, 0)
        slider, readout = self._slider("key_font_scale", 6, 20,
                                       int(round(s.key_font_scale * 10)), "×", 0.1)
        grid.addWidget(slider, 2, 1)
        grid.addWidget(readout, 2, 2)

        grid.addWidget(QLabel("Tejdukshmëria"), 3, 0)
        slider, readout = self._slider("opacity", 25, 100,
                                       int(round(s.opacity * 100)), "%", 0.01,
                                       display_scale=1.0)
        grid.addWidget(slider, 3, 1)
        grid.addWidget(readout, 3, 2)

        grid.addWidget(QLabel("Tejdukshmëria kur zbehet"), 4, 0)
        slider, readout = self._slider("faded_opacity", 15, 100,
                                       int(round(s.faded_opacity * 100)), "%", 0.01,
                                       display_scale=1.0)
        grid.addWidget(slider, 4, 1)
        grid.addWidget(readout, 4, 2)

        grid.addWidget(self._checkbox("Trego panelin e navigimit", s.nav_visible,
                                      "nav_visible"), 5, 0, 1, 3)
        grid.addWidget(self._checkbox("Fiksuar në fund të ekranit", s.docked,
                                      "docked"), 6, 0, 1, 3)
        return box


def help_html() -> str:
    p = theme.palette()
    return f"""
<style>
  h2 {{ color: {p.accent}; margin-bottom: 2px; }}
  h3 {{ color: {p.accent}; margin-top: 18px; margin-bottom: 4px; }}
  li {{ margin-bottom: 5px; }}
</style>
<h2>{APP_NAME} {__version__}</h2>
<p>Tastierë shqipe në ekran me parashikim të fjalëve. Shkruan në çdo program —
Word, shfletuesin, email, chat — sepse dërgon shtypje tastesh të vërteta te
dritarja që keni të hapur.</p>

<h3>Shkrimi</h3>
<ul>
<li>Tastiera <b>nuk e merr fokusin</b>: kursori mbetet aty ku po shkruani.</li>
<li>Shkronjat <b>Ë</b> dhe <b>Ç</b> shkruhen edhe nëse në kompjuter nuk është
instaluar tastiera shqipe.</li>
<li><b>Shift, Ctrl, Alt, AltGr</b> janë ngjitëse: shtypini një herë për tastin
tjetër, dy herë për t'i mbyllur (shfaqet një pikë e bardhë), tri herë për t'i
liruar. Kështu Ctrl+C bëhet me një gisht të vetëm.</li>
<li><b>Fn</b> ndërron rreshtin e numrave me F1–F12.</li>
</ul>

<h3>Parashikimi i fjalëve</h3>
<ul>
<li>Ndërsa shkruani, rreshtat e sipërm ju ofrojnë fjalë të plota; klikoni njërën
dhe fjala shkruhet e tëra.</li>
<li>Pas çdo fjale, tastiera parashikon <b>fjalën e radhës</b> nga konteksti.</li>
<li>Numrin e rreshtave (1–3) dhe të fjalëve për rresht i caktoni te
<b>Opsionet → Parashikimi i fjalëve</b>. Rreshti i parë përmban hamendjen më të
mirë; rreshtat e tjerë kapin fjalët që ai nuk i gjen.</li>
<li>Nuk keni nevojë të shkruani theksat: <i>shqiperi</i> ju ofron
<i>Shqipëri</i>.</li>
<li>Gabimet e vogla falen: një shkronjë e tepërt ose e ndërruar prapëseprapë
gjen fjalën.</li>
<li>Tastiera <b>mëson fjalët tuaja</b> — emrat, vendet, shprehjet që përdorni —
dhe i ngre lart në listë. Gjithçka ruhet vetëm në kompjuterin tuaj.</li>
</ul>

<h3>Për përdorim me lëvizje të kufizuar</h3>
<ul>
<li><b>Zgjedhja me qëndrim</b> (Opsionet → Qasshmëria) shtyp tastin duke mbajtur
kursorin mbi të, pa klikuar fare. E dobishme me mouse me kokë ose me sy.</li>
<li>Madhësia e shkronjave dhe koha e qëndrimit rregullohen te Opsionet.</li>
<li>Nëse ngjyra e theksit nuk dallohet mirë, ndryshojeni te
<b>Opsionet → Pamja → Ngjyra e theksit</b>.</li>
</ul>

<h3>Dritarja</h3>
<ul>
<li><b>Tërhiqeni</b> nga shiriti i sipërm për ta lëvizur kudo në ekran.</li>
<li><b>Ndryshoni madhësinë</b> duke tërhequr çdo anë ose cep të saj.</li>
<li>Dy klikime mbi shiritin e sipërm e fiksojnë ose e lirojnë nga fundi i
ekranit.</li>
<li><b>◧</b> fikson / liron, <b>◑</b> e zbeh, <b>☼</b> ndërron të errëtën me të
çelëtën, <b>⚙</b> hap Opsionet.</li>
<li><b>Mv Up / Mv Dn</b> — ngre ose ul tastierën që të mos mbulojë tekstin.</li>
<li><b>Nav</b> — fsheh ose tregon panelin e djathtë.</li>
</ul>
"""


class HelpDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Ndihmë")
        self.resize(640, 580)
        layout = QVBoxLayout(self)
        view = QTextBrowser()
        view.setHtml(help_html())
        view.setOpenExternalLinks(True)
        layout.addWidget(view)
        layout.addWidget(close_box(self))
