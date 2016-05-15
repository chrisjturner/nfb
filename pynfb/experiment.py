from pynfb.signals import DerivedSignal
from pynfb.lsl_stream import LSLStream, LSL_STREAM_NAMES
from pynfb.protocols import BaselineProtocol, FeedbackProtocol
from PyQt4 import QtGui, QtCore
import sys
from pynfb.windows import MainWindow
import numpy as np


# helpers
def int_or_none(string):
    return int(string) if len(string) > 0 else None


class Experiment():
    def __init__(self, app, params):
        # inlet frequency
        self.freq = 500

        # number of channels (select first n_channels channels)
        self.n_channels = 32

        # signals
        if 'vSignals' in params:
            self.signals = [DerivedSignal(bandpass_high=int_or_none(signal['fBandpassHighHz']),
                                          bandpass_low=int_or_none(signal['fBandpassLowHz']),
                                          name=signal['sSignalName'],
                                          n_channels=self.n_channels)
                            for signal in params['vSignals']]
        else:
            pass
        self.current_samples = np.zeros_like(self.signals)

        # protocols
        if 'vProtocols' in params:
            self.protocols = []
            for protocol in params['vProtocols']:
                if protocol['sFb_type'] == '':
                    self.protocols.append(BaselineProtocol(self.signals,
                                                           duration=int_or_none(protocol['fDuration']),
                                                           name=protocol['sProtocolName']))
                else:
                    self.protocols.append(FeedbackProtocol(self.signals,
                                                           duration=int_or_none(protocol['fDuration']),
                                                           name=protocol['sProtocolName']))
        else:
            pass

        # protocols sequence
        if 'vPSequence' in params:
            names = [protocol.name for protocol in self.protocols]
            self.protocols_sequence = []
            for name in params['vPSequence']:
                self.protocols_sequence.append(self.protocols[names.index(name)])
            print(self.protocols_sequence)
        else:
            pass

        # current protocol index
        self.current_protocol_index = 0

        # samples counter for protocol sequence
        self.samples_counter = 0

        # current protocol number of samples ('frequency' * 'protocol duration')
        self.current_protocol_n_samples = self.freq * self.protocols_sequence[self.current_protocol_index].duration

        # experiment number of samples
        experiment_n_samples = sum([self.freq * p.duration for p in self.protocols_sequence])

        # windows
        self.main = MainWindow(signals=self.signals,
                               parent=None,
                               current_protocol=self.protocols_sequence[self.current_protocol_index],
                               n_signals=len(self.signals),
                               experiment_n_samples = experiment_n_samples)
        self.subject = self.main.subject_window
        self.stream = LSLStream(n_channels=self.n_channels)

        # timer
        main_timer = QtCore.QTimer(app)
        main_timer.timeout.connect(self.update)
        main_timer.start(1000 * 1. / self.freq)
        pass

    def update(self):
        """
        Experiment main update action
        :return: None
        """
        # get next chunk
        chunk = self.stream.get_next_chunk()
        if chunk is not None:
            # update samples counter
            self.samples_counter += chunk.shape[0]
            # update and collect current samples
            for i, signal in enumerate(self.signals):
                signal.update(chunk)
                self.current_samples[i] = signal.current_sample
            # redraw signals and raw data
            self.main.redraw_signals(self.current_samples, chunk)
            # redraw protocols
            self.subject.update_protocol_state(self.current_samples, chunk_size=chunk.shape[0])
            # change protocol if current_protocol_n_samples has been reached
            if self.samples_counter >= self.current_protocol_n_samples:
                self.next_protocol()

    def next_protocol(self):
        """
        Change protocol
        :return: None
        """
        # reset samples counter
        self.samples_counter = 0
        if self.current_protocol_index < len(self.protocols_sequence) - 1:
            # close previous protocol
            self.protocols_sequence[self.current_protocol_index].close_protocol()
            # reset buffer if previous protocol has true value in update_statistics_in_the_end
            if self.protocols_sequence[self.current_protocol_index].update_statistics_in_the_end:
                self.main.signals_buffer *= 0
            # update current protocol index and n_samples
            self.current_protocol_index += 1
            self.current_protocol_n_samples = self.freq * self.protocols_sequence[self.current_protocol_index].duration
            # change protocol widget
            self.subject.change_protocol(self.protocols_sequence[self.current_protocol_index])
        else:
            # action in the end of protocols sequence
            self.current_protocol_n_samples = np.inf
            self.subject.close()
            np.save('results/raw', self.main.raw_recorder)
            np.save('results/signals', self.main.signals_recorder)
