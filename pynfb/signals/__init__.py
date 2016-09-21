import numpy as np
from scipy.fftpack import rfft, irfft, fftfreq
from .composite import CompositeSignal
from pynfb.io import save_spatial_filter


class DerivedSignal():
    def __init__(self, ind, n_channels=50, n_samples=1000, bandpass_low=None, bandpass_high=None, spatial_filter=None,
                 source_freq=500, scale=False, name='Untitled', disable_spectrum_evaluation=False,
                 smoothing_factor=0.1):
        # n_samples hot fix:
        print('**** n_samples type is', type(n_samples))
        # id
        self.ind = ind
        self.n_samples = int(n_samples)
        # signal name
        self.name = name
        # signal buffer
        self.buffer = np.zeros((n_samples,))
        # signal statistics
        self.scaling_flag = scale
        self.mean = np.nan
        self.std = np.nan
        # signal statistics accumulators
        self.mean_acc = 0
        self.var_acc = 0
        self.std_acc = 0
        self.n_acc = 0

        # rejections matrices list
        self.ica_rejection = None
        self.rejections = []

        # spatial filter
        self.spatial_filter = np.zeros((n_channels,))
        self.spatial_filter_topography = None
        if spatial_filter is None:
            self.spatial_filter[0] = 0
        else:
            shape = min(spatial_filter.shape[0], n_channels)
            self.spatial_filter[:shape] = spatial_filter[:shape]

        # spatial matrix
        self.spatial_matrix = self.spatial_filter.copy()

        # current sample
        self.current_sample = 0
        self.previous_sample = 0
        # bandpass and exponential smoothing flsg
        self.disable_spectrum_evaluation = disable_spectrum_evaluation
        # bandpass filter settings
        self.w = fftfreq(2 * self.n_samples, d=1. / source_freq * 2)
        self.bandpass = (bandpass_low if bandpass_low else 0,
                         bandpass_high if bandpass_high else source_freq)

        # asymmetric gaussian window
        p = round(2 * n_samples * 2 / 4)  # maximum
        eps = 0.0001  # bounds value
        power = 2  # power of x
        left_c = - np.log(eps) / (p ** power)
        right_c = - np.log(eps) / (2 * n_samples - 1 - p) ** power
        samples_window = np.concatenate([np.exp(-left_c * abs(np.arange(p) - p) ** power),
                                         np.exp(-right_c * abs(np.arange(p, 2 * n_samples) - p) ** power)])
        self.samples_window = samples_window

        # exponential smoothing factor
        self.smoothing_factor = smoothing_factor
        pass

    def spatial_filter_is_zeros(self):
        return (self.spatial_filter == 0).all()

    def update(self, chunk):

        # spatial filter
        filtered_chunk = np.dot(chunk, self.spatial_matrix)

        # update buffer
        chunk_size = filtered_chunk.shape[0]
        if chunk_size <= self.n_samples:
            self.buffer[:-chunk_size] = self.buffer[chunk_size:]
            self.buffer[-chunk_size:] = filtered_chunk
        else:
            self.buffer = filtered_chunk[-self.n_samples:]

        if not self.disable_spectrum_evaluation:
            # bandpass filter and amplitude
            filtered_sample = self.get_bandpass_amplitude()
            # exponential smoothing
            if self.n_acc > 10:
                self.current_sample = (
                self.smoothing_factor * filtered_sample + (1 - self.smoothing_factor) * self.previous_sample)
            else:
                self.current_sample = filtered_sample
            self.previous_sample = self.current_sample
            # accumulate sum and sum^2
            self.mean_acc = (self.n_acc * self.mean_acc + chunk_size * self.current_sample) / (self.n_acc + chunk_size)
            self.var_acc = (self.n_acc * self.var_acc + chunk_size * (self.current_sample - self.mean_acc) ** 2) / (
                self.n_acc + chunk_size)
        else:
            # accumulate sum and sum^2
            self.current_sample = filtered_chunk
            self.mean_acc = (self.n_acc * self.mean_acc + self.current_sample.sum()) / (self.n_acc + chunk_size)
            self.var_acc = (self.n_acc * self.var_acc + (self.current_sample - self.mean_acc).sum() ** 2) / (
                self.n_acc + chunk_size)

        self.std_acc = self.var_acc ** 0.5
        self.n_acc += chunk_size

        if self.scaling_flag and self.std > 0:
            self.current_sample = (self.current_sample - self.mean) / self.std
        pass

    def get_bandpass_amplitude(self):
        f_signal = rfft(np.hstack((self.buffer, self.buffer[-1::-1])) * self.samples_window)
        cut_f_signal = f_signal.copy()
        cut_f_signal[(self.w < self.bandpass[0]) | (self.w > self.bandpass[1])] = 0  # TODO: in one row
        amplitude = np.abs(cut_f_signal).mean()
        return amplitude

    def update_statistics(self, mean=None, std=None, raw=None, emulate=False,
                          signals_recorder=None, stats_previous=None, drop_outliers=0):
        if raw is not None and emulate:
            signal_recordings = np.zeros_like(signals_recorder[:, self.ind])
            self.reset_statistic_acc()
            mean_chunk_size = 8
            for k in range(0, raw.shape[0] - mean_chunk_size, mean_chunk_size):
                chunk = raw[k:k + mean_chunk_size]
                self.update(chunk)
                signal_recordings[k:k + mean_chunk_size] = self.current_sample
        else:
            signal_recordings = signals_recorder[:, self.ind]
        mean_prev, std_prev = stats_previous[self.ind]
        if np.isfinite(mean_prev) and np.isfinite(std_prev):
            signal_recordings = signals_recorder * std_prev + mean_prev
        # drop outliers:
        if drop_outliers and signal_recordings.std() > 0:
                signal_recordings_clear = signal_recordings[
                    np.abs(signal_recordings - signal_recordings.mean()) < drop_outliers * signal_recordings.std()]
        else:
            signal_recordings_clear = signal_recordings
        self.mean = mean if (mean is not None) else signal_recordings_clear.mean()
        self.std = std if (std is not None) else signal_recordings_clear.std()
        return (signal_recordings - self.mean) / (self.std if self.std > 0 else 1)

    def update_spatial_filter(self, spatial_filter=None, topography=None):
        if spatial_filter is not None:
            self.spatial_filter = np.array(spatial_filter)
        self.spatial_matrix = self.spatial_filter
        for matrix in reversed(self.rejections):
            self.spatial_matrix = np.dot(matrix, self.spatial_matrix)
        if self.ica_rejection is not None:
            self.spatial_matrix = np.dot(self.ica_rejection, self.spatial_matrix)
        self.spatial_filter_topography = topography if topography is not None else self.spatial_filter_topography

    def append_spatial_matrix_list(self, matrix):
        self.rejections.append(matrix)
        self.update_spatial_filter()

    def update_rejections(self, rejections, append=False):
        if append:
            self.rejections += rejections
        else:
            self.rejections = rejections.copy()
        self.update_spatial_filter()

    def update_ica_rejection(self, rejection=None):
        self.ica_rejection = rejection
        self.update_spatial_filter()

    def update_bandpass(self, bandpass):
        self.bandpass = bandpass

    def reset_statistic_acc(self):
        self.mean_acc = 0
        self.var_acc = 0
        self.std_acc = 0
        self.n_acc = 0

    def enable_scaling(self):
        self.scaling_flag = True
        pass

    def save_spatial_matrix(self, file_path, channels_labels=None):
        """
        Save full spatial matrix: R1*R2*...*Rk*S, where R1,..Rk - rejections matrices, S - spatial filter
        :return:
        """
        save_spatial_filter(file_path, self.spatial_matrix, channels_labels=channels_labels)

