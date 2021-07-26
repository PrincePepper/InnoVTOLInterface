from logging import getLogger

import uavcan
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QLabel, QSlider, QSpinBox, \
    QDoubleSpinBox, \
    QPlainTextEdit, QGroupBox, QPushButton

from interface.panels.functions import make_icon_button, get_monospace_font

PANEL_NAME = 'Vtol Panel'

logger = getLogger(__name__)

_singleton = None


class PercentSlider(QWidget):
    def __init__(self, parent, val):
        super(PercentSlider, self).__init__(parent)

        self._slider = QSlider(Qt.Vertical, self)
        self._slider.setMinimum(-1)
        self._slider.setMaximum(val)
        self._slider.setValue(-1)
        self._slider.setTickInterval(int(val / 4))
        self._slider.setTickPosition(QSlider.TicksBothSides)
        self._slider.valueChanged.connect(lambda: self._spinbox.setValue(self._slider.value()))

        self._spinbox = QSpinBox(self)
        self._spinbox.setMinimum(-1)
        self._spinbox.setMaximum(val)
        self._spinbox.setValue(-1)
        self._spinbox.valueChanged.connect(lambda: self._slider.setValue(self._spinbox.value()))

        self._zero_button = make_icon_button('hand-stop-o', 'Zero setpoint', self,
                                             on_clicked=self.zero)

        layout = QVBoxLayout(self)
        sub_layout = QHBoxLayout(self)
        sub_layout.addStretch()
        sub_layout.addWidget(self._slider)
        sub_layout.addStretch()
        layout.addLayout(sub_layout)
        layout.addWidget(self._spinbox)
        layout.addWidget(self._zero_button)
        self.setLayout(layout)

        from screeninfo import get_monitors
        for m in get_monitors():
            self.setMinimumHeight(int(m.height * 0.35))

    def zero(self):
        self._slider.setValue(-1)

    def get_value(self):
        return self._slider.value()

    def set_value(self, val):
        self._slider.setValue(val)


class ControlWidget(QGroupBox):
    DEFAULT_INTERVAL = 0.1

    CMD_BIT_LENGTH = uavcan.get_uavcan_data_type(
        uavcan.equipment.esc.RawCommand().cmd).value_type.bitlen
    CMD_MAX = 2 ** (CMD_BIT_LENGTH - 1) - 1
    CMD_MIN = -(2 ** (CMD_BIT_LENGTH - 1))

    def __init__(self, parent, node, CONFIG_CONTROL_WIDGET, save_file_func, restart_func):
        super(ControlWidget, self).__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)  # This is required to stop background timers!

        self._node = node
        self.save_file_func = save_file_func
        TEMP_AIRFRAME = CONFIG_CONTROL_WIDGET

        self._sliders = [PercentSlider(self, 8191) for _ in range(4)]
        self._sliders += [PercentSlider(self, 2000) for _ in range(4)]

        #
        # TODO: требуется привязать значения из json(TEMP_AIRFRAME), а также их привязка к слайдерам
        #
        try:
            self._sliders[4].set_value(int(TEMP_AIRFRAME['aileron_left']))
            self._sliders[5].set_value(int(TEMP_AIRFRAME['aileron_right']))
            self._sliders[6].set_value(int(TEMP_AIRFRAME['rudder_left']))
            self._sliders[7].set_value(int(TEMP_AIRFRAME['rudder_right']))
        except:
            logger.error("Your structure json kill program")
        self._bcast_interval = QDoubleSpinBox(self)
        self._bcast_interval.setMinimum(0.01)
        self._bcast_interval.setMaximum(1.0)
        self._bcast_interval.setSingleStep(0.1)
        self._bcast_interval.setValue(self.DEFAULT_INTERVAL)
        self._bcast_interval.valueChanged.connect(
            lambda: self._bcast_timer.setInterval(self._bcast_interval.value() * 1e3))

        self._stop_all = make_icon_button('hand-stop-o', 'Zero all channels', self, text='Stop All',
                                          on_clicked=self._do_stop_all)

        self._pause = make_icon_button('pause', 'Pause publishing', self, checkable=True,
                                       text='Pause')

        self._msg_viewer = QPlainTextEdit(self)
        self._msg_viewer.setReadOnly(True)
        self._msg_viewer.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._msg_viewer.setFont(get_monospace_font())
        self._msg_viewer.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._msg_viewer.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._msg_viewer.setFixedHeight(self.height() * 5)

        self._bcast_timer = QTimer(self)
        self._bcast_timer.start(self.DEFAULT_INTERVAL * 1e3)
        self._bcast_timer.timeout.connect(self._do_broadcast)

        layout = QVBoxLayout(self)

        self._save_button = QPushButton('Save airframe', self)
        self._save_button.setFocusPolicy(Qt.NoFocus)
        self._save_button.clicked.connect(self.create_dist_to_save_file_func)

        self._restart_button = QPushButton('Restart all', self)
        self._restart_button.setFocusPolicy(Qt.NoFocus)
        self._restart_button.clicked.connect(restart_func)

        box1 = QHBoxLayout(self)
        box1.addWidget(self._save_button)
        box1.addWidget(self._restart_button)
        layout.addLayout(box1)

        self._slider_layout = QHBoxLayout(self)
        for sl in self._sliders:
            self._slider_layout.addWidget(sl)
        layout.addLayout(self._slider_layout)

        layout.addWidget(self._stop_all)

        controls_layout = QHBoxLayout(self)
        controls_layout.addWidget(QLabel('Channels:', self))
        controls_layout.addWidget(QLabel('Broadcast interval:', self))
        controls_layout.addWidget(self._bcast_interval)
        controls_layout.addWidget(QLabel('sec', self))
        controls_layout.addStretch()
        controls_layout.addWidget(self._pause)
        layout.addLayout(controls_layout)

        layout.addWidget(QLabel('Generated message:', self))
        layout.addWidget(self._msg_viewer)

        self.setLayout(layout)
        self.resize(self.minimumWidth(), self.minimumHeight())

    def _do_broadcast(self):
        try:
            if not self._pause.isChecked():
                msg = uavcan.equipment.esc.RawCommand()
                for sl in self._sliders:
                    raw_value = sl.get_value() / 8191
                    value = (-self.CMD_MIN if raw_value < 0 else self.CMD_MAX) * raw_value
                    msg.cmd.append(int(value))
                self._node.broadcast(msg)
                self._msg_viewer.setPlainText(uavcan.to_yaml(msg))
            else:
                self._msg_viewer.setPlainText('Paused')
        except Exception as ex:
            self._msg_viewer.setPlainText('Publishing failed:\n' + str(ex))

    def _do_stop_all(self):
        for sl in self._sliders:
            sl.zero()

    def __del__(self):
        global _singleton
        _singleton = None

    def closeEvent(self, event):
        global _singleton
        _singleton = None
        super(ControlWidget, self).closeEvent(event)

    def create_dist_to_save_file_func(self):
        temp_dist = {"aileron_1": self._sliders[4].get_value(),
                     "aileron_2": self._sliders[5].get_value(),
                     "rudder_1": self._sliders[6].get_value(),
                     "rudder_2": self._sliders[7].get_value()}
        self.save_file_func(temp_dist)
