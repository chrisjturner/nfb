"""
This is a script to analyse pilot data for the first experiment

following procedures here:
Müller, J. A., Wendt, D., Kollmeier, B., & Brand, T. (2016). Comparing eye tracking with electrooculography for measuring individual sentence comprehension duration. PLoS ONE, 11(10), 1–22. https://doi.org/10.1371/journal.pone.0164627
"""
import matplotlib.pyplot as plt
import numpy as np
from pynfb.serializers.hdf5 import load_h5py_all_samples, load_h5py_protocol_signals, load_h5py_protocols_raw, load_h5py
from utils.load_results import load_data
import os
import glob
import pandas as pd
import plotly.express as px
from scipy.signal import butter, lfilter, freqz
import mne

# low pass filter
def butter_lowpass(cutoff, fs, order=5):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    return b, a
def butter_lowpass_filter(data, cutoff, fs, order=5):
    b, a = butter_lowpass(cutoff, fs, order=order)
    y = lfilter(b, a, data)
    return y

h5file = "/Users/christopherturner/Documents/EEG Data/ChrisPilot20220110/0-pre_task_ct01_01-10_16-07-00/experiment_data.h5"

# Put data in pandas data frame
df1, fs, channels, p_names = load_data(h5file)
df1['sample'] = df1.index

# Extract the individual protocols
protocol_data = {}
block_numbers = df1['block_number'].unique()
protocol_names = [f"{a_}{b_}"for a_, b_ in zip(p_names, block_numbers)]
channels_signal = channels.copy()
channels_signal.append("signal_AAI")
df2 = pd.melt(df1, id_vars=['block_name', 'block_number', 'sample', 'choice', 'probe', 'answer'], value_vars=channels_signal, var_name="channel", value_name='data')

for protocol_n in block_numbers:
    protocol_data[protocol_names[protocol_n-1]] = df2.loc[df2['block_number'] == protocol_n]


# --- Pre/Post tests----
# - Prepare EOG and ECG signals

# get raw eog data
eog_data = protocol_data['EyeCalib2'].loc[protocol_data['EyeCalib2']['channel'].isin(["ECG", "EOG"])]

# get samples for onset of each calibration stage (probe: left=10, right=11, top=12, bottom=13, cross=14)
eog_data['probe_change'] = eog_data['probe'].diff()
calibration_samples = eog_data[eog_data['probe_change'] != 0]
calibration_samples = calibration_samples.loc[protocol_data['EyeCalib2']['channel'].isin(["EOG"])][['sample', 'probe']]
calibration_samples['probe'] = calibration_samples['probe'].replace({14: 'cross', 10: 'left', 11: 'right', 12: 'top', 13: 'bottom'})

# fig = px.line(eog_data, x="sample", y="data", color='channel')
# for index, row in calibration_samples.iterrows():
#     fig.add_vline(x=row['sample'], line_dash="dot",
#                   annotation_text=row['probe'],
#                   annotation_position="bottom right")
# fig.show()

# Low pass filter (20Hz)
cutoff = 20
eog_data['filtered_data'] = butter_lowpass_filter(eog_data['data'], cutoff, fs)

# Get the offsets for each calibration point
calibration_delay = 400 # 500ms to react to probe # TODO: find a way to automate this
previous_offset = 0
calibration_offsets_ecg = {}
calibration_offsets_eog = {}
for idx in range(len(calibration_samples)):
    offset = calibration_samples.iloc[idx].loc['sample']
    type = calibration_samples.iloc[idx].loc['probe']
    if idx == 0:
        previous_offset = offset
        previous_type = type
    else:
        second_EOG = eog_data[eog_data['sample'].between(previous_offset + calibration_delay, offset + calibration_delay, inclusive="neither")]
        calibration_offsets_ecg[previous_type] = second_EOG.loc[second_EOG['channel'] == "EOG"]['filtered_data'].median()
        calibration_offsets_eog[previous_type] = second_EOG.loc[second_EOG['channel'] == "ECG"]['filtered_data'].median()
        previous_offset = offset
        previous_type = type

    if idx == len(calibration_samples)-1:
        type = 'cross2'
        second_EOG = eog_data[eog_data['sample'].between(offset + calibration_delay, eog_data['sample'].iloc[-1], inclusive="neither")]
        calibration_offsets_ecg[type] = second_EOG.loc[second_EOG['channel'] == "EOG"]['filtered_data'].median()
        calibration_offsets_eog[type] = second_EOG.loc[second_EOG['channel'] == "ECG"]['filtered_data'].median()

fig = px.line(eog_data, x="sample", y=eog_data["filtered_data"], color='channel')
for index, row in calibration_samples.iterrows():
    fig.add_vline(x=row['sample']+calibration_delay, line_dash="dot",
                  annotation_text=row['probe'],
                  annotation_position="bottom right")
for type, value in calibration_offsets_eog.items():
    fig.add_hline(y=value, line_color='red',
                      annotation_text=f"{type}: MEDIAN",
                      annotation_position="bottom right")
for type, value in calibration_offsets_ecg.items():
    fig.add_hline(y=value, line_color='blue',
                      annotation_text=f"{type}: MEDIAN",
                      annotation_position="bottom right")
fig.show()

pass

# Plot calibration location on spatial grid
# Plot eye tracking data on spatial grid definied by calibration

# Calculate fixation bias for each trial
# Average fixation bias over all trials
# Get change in fixation bias between pre and post sessions
# Do permutation test for individual data
# Average change in fb for all participants
# do t-test with all participants



#--- NFB trials ----
# Prepare EEG signals
# Get source activation for left and right parietal and occipital for each trial
# plot time course of source activation over all trials

# Look at probe responses

# average AAI over 4 periods
# look at change in AAI over each period
# Look at correct trials over time for participant
# plot score over time for participant
