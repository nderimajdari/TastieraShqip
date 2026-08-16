"""Options and Help dialogs.

The interface language is Albanian throughout: the people this keyboard is for
are writing in Albanian, and an assistive tool that explains itself in a foreign
language is one more barrier.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout,
    QGroupBox, QLabel, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox,
    QTextBrowser, QVBoxLayout, QWidget,
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
        self.setMinimumWidth(540)
        #: Explanatory labels, which are coloured by hand and so have to be
        #: recoloured by hand when a change in here repaints everything else.
        self._faint_labels: list[QLabel] = []

        # The settings run past the height of a small laptop screen, and a
        # dialog taller than the display is a dialog whose Close button cannot
        # be reached -- so the groups scroll and the button stays put below
        # them. The dialog still opens at its natural size when there is room.
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(12)
        layout.addWidget(self._prediction_group())
        layout.addWidget(self._sentence_group())
        layout.addWidget(self._accessibility_group())
        layout.addWidget(self._appearance_group())
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        inner.setAutoFillBackground(False)

        outer = QVBoxLayout(self)
        outer.addWidget(scroll, 1)
        outer.addWidget(close_box(self))

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            room = screen.availableGeometry().height() - 60
            self.resize(self.width(),
                        min(inner.sizeHint().height() + 70, room))

    # -- helpers -----------------------------------------------------------

    def _changed(self) -> None:
        self.settings_changed.emit()
        self._restyle_faint()

    def _faint(self, text: str) -> QLabel:
        """A dimmed explanatory label that follows later theme changes."""
        label = QLabel(text)
        label.setWordWrap(True)
        self._faint_labels.append(label)
        label.setStyleSheet(f"color:{theme.palette().text_faint};")
        return label

    def _restyle_faint(self) -> None:
        colour = theme.palette().text_faint
        for label in self._faint_labels:
            label.setStyleSheet(f"color:{colour};")

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
                display_scale: float | None = None,
                fmt=None) -> tuple[QSlider, QLabel]:
        """A slider whose stored value and displayed value may differ in unit.

        Opacity is stored as a fraction but read by people as a percentage, so
        the two scales are kept separate rather than dividing by a hundred twice.
        ``fmt`` takes that further for settings whose stored unit runs the wrong
        way round for a reader -- see the key repeat rate.
        """
        shown = scale if display_scale is None else display_scale

        def label_for(v: int) -> str:
            return fmt(v) if fmt else f"{v * shown:g}{suffix}"

        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(value)
        readout = QLabel(label_for(value))
        readout.setMinimumWidth(56)

        def on_move(v: int) -> None:
            setattr(self.settings, attr, v * scale if scale != 1.0 else v)
            readout.setText(label_for(v))
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

        grid.addWidget(self._checkbox("Sugjero dy-tri fjalë bashkë (p.sh. « do të »)",
                                      s.phrase_suggestions, "phrase_suggestions"),
                       3, 0, 1, 3)
        grid.addWidget(self._faint(
            "Kur fjala e radhës është e sigurt, jepet bashkë me të parën: "
            "një klikim në vend të dy."), 4, 0, 1, 3)

        grid.addWidget(QLabel("Fjalë për rresht"), 5, 0)
        grid.addWidget(self._spin("suggestion_count", 3, 10, s.suggestion_count), 5, 1)

        grid.addWidget(QLabel("Rreshta sugjerimesh"), 6, 0)
        grid.addWidget(self._spin("suggestion_rows", 1, 3, s.suggestion_rows), 6, 1)
        grid.addWidget(self._faint("Më shumë rreshta = më shumë fjalë për të\n"
                                   "zgjedhur, por edhe më shumë vend të zënë."), 6, 2)

        # The suggestion buttons are sized apart from the keys: they are read
        # rather than aimed at from memory, and somebody who enlarged the keys
        # to hit them may well want the words smaller to see more at once.
        grid.addWidget(QLabel("Lartësia e butonave"), 7, 0)
        slider, readout = self._slider("suggestion_height", 22, 96,
                                       s.suggestion_height, " px")
        grid.addWidget(slider, 7, 1)
        grid.addWidget(readout, 7, 2)

        grid.addWidget(QLabel("Madhësia e fjalëve"), 8, 0)
        slider, readout = self._slider("suggestion_font_scale", 6, 25,
                                       int(round(s.suggestion_font_scale * 10)),
                                       "×", 0.1)
        grid.addWidget(slider, 8, 1)
        grid.addWidget(readout, 8, 2)

        grid.addWidget(self._faint(
            "Të njëjtat rregullohen edhe me « − » dhe « + » në cepin e djathtë "
            "të rreshtit të sugjerimeve, pa hapur këtë dritare."), 9, 0, 1, 3)

        clear = QPushButton("Fshi fjalorin tim personal")
        clear.clicked.connect(self._clear_user_model)
        grid.addWidget(clear, 10, 0, 1, 3)

        words = self.engine.user.unigram
        grid.addWidget(self._faint(
            f"Fjalor personal: {len(words):,} fjalë  •  "
            f"Fjalor shqip: {self.engine.model.vocabulary_size:,} fjalë"),
            11, 0, 1, 3)
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

    def _sentence_group(self) -> QGroupBox:
        box = QGroupBox("Fjalitë e plota")
        grid = QGridLayout(box)
        s = self.settings

        grid.addWidget(self._checkbox(
            "Kujto fjalitë e mia dhe m'i ofro të plota",
            s.sentence_suggestions, "sentence_suggestions"), 0, 0, 1, 3)
        grid.addWidget(self._faint(
            "Butoni « Fjali » mbi tastierë hap një fletë me fjali të tëra. "
            "Një klikim shkruan gjithë fjalinë, sado e gjatë. Fjalitë që "
            "shkruani ruhen vetëm në këtë kompjuter."), 1, 0, 1, 3)

        grid.addWidget(QLabel("Fjali për fletë"), 2, 0)
        grid.addWidget(self._spin("sentence_count", 3, 8, s.sentence_count), 2, 1)

        self._sentence_status = self._faint("")
        grid.addWidget(self._sentence_status, 3, 0, 1, 3)

        clear = QPushButton("Fshi fjalitë e ruajtura")
        clear.clicked.connect(self._clear_sentences)
        grid.addWidget(clear, 4, 0, 1, 3)
        self._describe_sentences()
        return box

    def _describe_sentences(self) -> None:
        bank = self.engine.bank
        self._sentence_status.setText(
            f"Fjali të ruajtura nga shkrimi juaj: {len(bank):,}  •  "
            f"fjali të gatshme: {len(bank.builtin_texts()):,}")

    def _clear_sentences(self) -> None:
        answer = QMessageBox.question(
            self, "Fshi fjalitë",
            "Të fshihen të gjitha fjalitë e ruajtura nga shkrimi juaj?\n"
            "Fjalitë e gatshme mbeten.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.engine.bank.clear()
            self._describe_sentences()
            self._changed()

    def _accessibility_group(self) -> QGroupBox:
        box = QGroupBox("Qasshmëria")
        grid = QGridLayout(box)
        s = self.settings

        dwell_box = self._checkbox(
            "Zgjedhje me qëndrim — shtyp tastin duke mbajtur kursorin mbi të",
            s.dwell_enabled, "dwell_enabled")
        grid.addWidget(dwell_box, 0, 0, 1, 3)

        dwell_label = QLabel("Koha e qëndrimit")
        grid.addWidget(dwell_label, 1, 0)
        dwell, dwell_out = self._slider("dwell_ms", 300, 3000, s.dwell_ms, " ms")
        grid.addWidget(dwell, 1, 1)
        grid.addWidget(dwell_out, 1, 2)

        def sync_dwell(on: bool) -> None:
            for w in (dwell_label, dwell, dwell_out):
                w.setEnabled(on)

        dwell_box.toggled.connect(sync_dwell)
        sync_dwell(s.dwell_enabled)

        repeat_box = self._checkbox("Përsërit tastin kur mbahet i shtypur",
                                    s.hold_to_repeat, "hold_to_repeat")
        grid.addWidget(repeat_box, 2, 0, 1, 3)

        delay_label = QLabel("Vonesa para përsëritjes")
        grid.addWidget(delay_label, 3, 0)
        delay, delay_out = self._slider("repeat_delay_ms", 150, 2000,
                                        s.repeat_delay_ms, " ms")
        grid.addWidget(delay, 3, 1)
        grid.addWidget(delay_out, 3, 2)

        # Stored as the gap between repeats, which is what a timer wants and the
        # opposite of what a person reads: on a millisecond scale the bigger
        # number is the slower keyboard, and the slider runs backwards. Shown as
        # repeats per second instead, so that dragging right means faster.
        rate_label = QLabel("Shpejtësia e përsëritjes")
        grid.addWidget(rate_label, 4, 0)
        rate, rate_out = self._slider(
            "repeat_rate_ms", 20, 400, s.repeat_rate_ms,
            fmt=lambda ms: f"{1000.0 / ms:.0f} / sek")
        rate.setInvertedAppearance(True)
        grid.addWidget(rate, 4, 1)
        grid.addWidget(rate_out, 4, 2)

        hint = self._faint(
            "Mbani të shtypur një tast (p.sh. Backspace ose një shkronjë) dhe "
            "ai përsëritet vetë — më shpejt djathtas.")
        grid.addWidget(hint, 5, 0, 1, 3)

        # The three controls under the switch do nothing while it is off, and a
        # live control that does nothing is worse than one that is visibly out
        # of use -- particularly here, where the user may have turned repeat off
        # precisely because a tremor was triggering it.
        def sync_repeat(on: bool) -> None:
            for w in (delay_label, delay, delay_out, rate_label, rate, rate_out,
                      hint):
                w.setEnabled(on)

        repeat_box.toggled.connect(sync_repeat)
        sync_repeat(s.hold_to_repeat)

        # Both of these exist to remove trips across the keyboard, which is what
        # a sentence boundary otherwise costs: Backspace to close up the space
        # before the full stop, the stop, a space after it, and Shift for the
        # capital -- four presses that write one character.
        grid.addWidget(self._checkbox(
            "Shkronjë e madhe automatike pas pikës",
            s.auto_capitals, "auto_capitals"), 6, 0, 1, 3)
        grid.addWidget(self._checkbox(
            "Rregullo hapësirat rreth pikës dhe presjes",
            s.auto_punctuation, "auto_punctuation"), 7, 0, 1, 3)
        grid.addWidget(self._faint(
            "Pika ngjitet te fjala dhe hapësira pas saj vihet vetë, "
            "kështu që nuk duhet Backspace pas çdo fjalie."), 8, 0, 1, 3)
        return box

    def _appearance_group(self) -> QGroupBox:
        box = QGroupBox("Pamja")
        grid = QGridLayout(box)
        s = self.settings

        # The design comes first: it decides the colours, so the controls it
        # takes over should be the ones underneath it.
        grid.addWidget(QLabel("Dizajni i tastierës"), 0, 0)
        skins = self._combo(
            "skin", [(key, sk.label) for key, sk in theme.SKINS.items()], s.skin)
        grid.addWidget(skins, 0, 1, 1, 2)

        self._skin_note = self._faint("")
        grid.addWidget(self._skin_note, 1, 0, 1, 3)

        grid.addWidget(QLabel("Ngjyrat"), 2, 0)
        grid.addWidget(self._combo("theme", [("dark", "E errët"),
                                             ("light", "E çelët")], s.theme), 2, 1)

        grid.addWidget(QLabel("Ngjyra e theksit"), 3, 0)
        self._accent_combo = self._combo(
            "accent", [(key, label) for key, (label, _l, _d) in theme.ACCENTS.items()],
            s.accent)
        grid.addWidget(self._accent_combo, 3, 1)
        self._rgb_box = self._checkbox("Drita RGB të lëvizë", s.rgb_animation,
                                       "rgb_animation")
        grid.addWidget(self._rgb_box, 4, 0, 1, 3)

        skins.currentIndexChanged.connect(lambda _i: self._describe_skin())
        self._describe_skin()

        grid.addWidget(QLabel("Madhësia e shkronjave"), 5, 0)
        slider, readout = self._slider("key_font_scale", 6, 20,
                                       int(round(s.key_font_scale * 10)), "×", 0.1)
        grid.addWidget(slider, 5, 1)
        grid.addWidget(readout, 5, 2)

        grid.addWidget(QLabel("Tejdukshmëria"), 6, 0)
        slider, readout = self._slider("opacity", 25, 100,
                                       int(round(s.opacity * 100)), "%", 0.01,
                                       display_scale=1.0)
        grid.addWidget(slider, 6, 1)
        grid.addWidget(readout, 6, 2)

        grid.addWidget(QLabel("Tejdukshmëria kur zbehet"), 7, 0)
        slider, readout = self._slider("faded_opacity", 15, 100,
                                       int(round(s.faded_opacity * 100)), "%", 0.01,
                                       display_scale=1.0)
        grid.addWidget(slider, 7, 1)
        grid.addWidget(readout, 7, 2)

        grid.addWidget(self._checkbox("Trego panelin e navigimit", s.nav_visible,
                                      "nav_visible"), 8, 0, 1, 3)
        grid.addWidget(self._checkbox("Fiksuar në fund të ekranit", s.docked,
                                      "docked"), 9, 0, 1, 3)
        return box

    def _describe_skin(self) -> None:
        """Explain the chosen design, and say when it owns the accent colour.

        A designed keyboard sets its own accent -- that colour is most of what
        makes it recognisable -- so the accent control goes quiet rather than
        silently doing nothing, which is the worse of the two.
        """
        skin = theme.SKINS.get(self.settings.skin, theme.SKINS["standard"])
        note = skin.note
        if skin.accent_locked:
            note += "  (Ky dizajn e ka ngjyrën e vet të theksit.)"
        self._skin_note.setText(note)
        self._accent_combo.setEnabled(not skin.accent_locked)
        self._rgb_box.setEnabled(skin.rgb)


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
<li><b>Shift</b> jep shkronjën e madhe — edhe <b>Ë</b> dhe <b>Ç</b> — dhe
shenjën e dytë të tastit (p.sh. <i>;</i> mbi presje).</li>
<li><b>Caps</b> prek vetëm shkronjat: me të ndezur, presja mbetet presje.
Shift bashkë me Caps kthen shkronjën e vogël.</li>
<li><b>Fn</b> ndërron rreshtin e numrave me F1–F12.</li>
<li>Pas pikës, shkronja e parë bëhet <b>e madhe vetvetiu</b> — nuk ju duhet
Shift. Nëse shtypni vetë Shift ose Caps, urdhri juaj mbetet.</li>
<li><b>Pika dhe presja</b> ngjiten te fjala dhe hapësira pas tyre vihet vetë,
edhe kur fjala u zgjodh nga sugjerimet. Numrat si <i>3.14</i> nuk preken.
Të dyja hiqen te <b>Opsionet → Qasshmëria</b>.</li>
</ul>

<h3>Parashikimi i fjalëve</h3>
<ul>
<li>Ndërsa shkruani, rreshtat e sipërm ju ofrojnë fjalë të plota; klikoni njërën
dhe fjala shkruhet e tëra.</li>
<li>Pas çdo fjale, tastiera parashikon <b>fjalën e radhës</b> nga konteksti.</li>
<li>Kur fjala e radhës është e sigurt, jepet <b>bashkë me të parën</b> —
<i>do të</i>, <i>mund të</i>, <i>për shkak të</i> — kështu dy a tri fjalë
shkruhen me një klikim të vetëm. Hiqet te <b>Opsionet → Parashikimi</b>.</li>
<li>Numrin e rreshtave (1–3) dhe të fjalëve për rresht i caktoni te
<b>Opsionet → Parashikimi i fjalëve</b>. Rreshti i parë përmban hamendjen më të
mirë; rreshtat e tjerë kapin fjalët që ai nuk i gjen.</li>
<li><b>Butonat « − » dhe « + »</b> në cepin e djathtë të sugjerimeve i zmadhojnë
ose i zvogëlojnë ato aty për aty, pa hapur Opsionet. Madhësia e tyre është e
ndarë nga ajo e tasteve.</li>
<li>Nuk keni nevojë të shkruani theksat: <i>shqiperi</i> ju ofron
<i>Shqipëri</i>.</li>
<li>Gabimet e vogla falen: një shkronjë e tepërt ose e ndërruar prapëseprapë
gjen fjalën.</li>
<li>Tastiera <b>mëson fjalët tuaja</b> — emrat, vendet, shprehjet që përdorni —
dhe i ngre lart në listë. Gjithçka ruhet vetëm në kompjuterin tuaj.</li>
</ul>

<h3>Fjalitë e plota — një klikim për një fjali të tërë</h3>
<ul>
<li>Butoni <b>« Fjali »</b>, në cepin e djathtë të rreshtit të sugjerimeve, hap
një fletë me fjali të tëra mbi tastet. <b>Një klikim shkruan gjithë fjalinë</b>,
qoftë tri fjalë apo pesëmbëdhjetë. Fleta mbyllet vetë pas zgjedhjes.</li>
<li>Numri mbi butonin tregon sa fjali ju presin, që të mos e hapni kot.</li>
<li>Tastiera <b>i mban mend fjalitë tuaja</b>: sa herë mbaroni një fjali me
pikë, pikëçuditje, pikëpyetje ose me <b>Enter</b>, ajo ruhet dhe ju ofrohet
herën tjetër. Kështu ruhen edhe rreshtat pa pikë — adresa, përshëndetja e
fundit e një emaili.</li>
<li>Shkruani <b>dy-tri shkronjat e para</b> të një fjalie dhe fleta ju lë vetëm
atë: <i>« Fal »</i> gjen <i>« Faleminderit shumë për ndihmën. »</i>. Nuk duhen
theksat — <i>« pers »</i> gjen <i>« Përshëndetje… »</i>.</li>
<li>Fjalia që sapo keni shkruar del <b>e para</b>: zakonisht atë përsërisni.</li>
<li>Vijnë të gatshme edhe rreth <b>37 fjali të përditshme</b> — kërkesa për
ndihmë, përshëndetje, përgjigje — që fleta të jetë e dobishme që ditën e parë.</li>
<li>Fjalitë ruhen <b>vetëm në këtë kompjuter</b> dhe nuk dërgohen askund.
Fjalitë që përmbajnë numra të gjatë (kode, numra karte) nuk ruhen kurrë.
Gjithçka fshihet te <b>Opsionet → Fjalitë e plota</b>.</li>
</ul>

<h3>Dizajni</h3>
<ul>
<li>Gjashtë pamje të ndryshme: <b>Standarde</b>, <b>Slim aluminium</b>,
<b>Gaming — kuqezi</b>, <b>RGB neon</b>, <b>Mekanike</b> dhe
<b>Makinë shkrimi</b>.</li>
<li><b>RGB neon</b> i ndriçon tastet nga poshtë me dritë që rrjedh ngadalë nëpër
tastierë. Nëse ju shpërqendron, ndaleni te <b>Opsionet → Pamja → Drita RGB të
lëvizë</b>; ngjyrat mbeten, vetëm lëvizja ndalet.</li>
<li>Ndërrohen kurdo — nga <b>Opsionet → Pamja → Dizajni i tastierës</b>, ose me
butonin e dizajnit në shiritin e sipërm, që i kalon me radhë.</li>
<li>Secila ka variantin e vet të errët dhe të çelët; butoni <b>☼</b> i ndërron.
Dizajnet e veçanta e mbajnë ngjyrën e vet të theksit.</li>
<li>Pamjet janë punuar posaçërisht për këtë program dhe nuk kanë lidhje me asnjë
markë.</li>
</ul>

<h3>Për përdorim me lëvizje të kufizuar</h3>
<ul>
<li><b>Zgjedhja me qëndrim</b> (Opsionet → Qasshmëria) shtyp tastin duke mbajtur
kursorin mbi të, pa klikuar fare. E dobishme me mouse me kokë ose me sy. Vlen
edhe për sugjerimet dhe për fjalitë e plota.</li>
<li><b>Përsëritja e tastit</b>: mbajeni të shtypur një tast dhe ai përsëritet
vetë — Backspace fshin një rresht pa 40 klikime. Vonesën para se të nisë dhe
sa herë në sekondë përsëritet i caktoni te <b>Opsionet → Qasshmëria</b>.
Nëse dridhja e dorës e nis pa dashje, fikeni fare aty.</li>
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
çelëtën, <b>◈</b> ndërron dizajnin, <b>⚙</b> hap Opsionet.</li>
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
