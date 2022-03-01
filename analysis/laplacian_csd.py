
import os
import mne

import platform

from pynfb.signal_processing.filters import ExponentialSmoother, FFTBandEnvelopeDetector
from utils.load_results import load_data
import pandas as pd
import plotly_express as px
import plotly.graph_objs as go
import analysis.analysis_functions as af
from mne.preprocessing import (ICA, create_eog_epochs, create_ecg_epochs,
                               corrmap)
from mne.datasets import fetch_fsaverage
from mne.minimum_norm import make_inverse_operator, apply_inverse_raw, apply_inverse, apply_inverse_epochs

from pynfb.helpers import roi_spatial_filter as rsf
from philistine.mne import savgol_iaf

if platform.system() == "Windows":
    userdir = "2354158T"
else:
    userdir = "christopherturner"

task_data = {}

h5file = f"/Users/{userdir}/Documents/EEG_Data/system_testing/ksenia_cvsa/cvsa_02-15_15-21-37/experiment_data.h5" # Ksenia cvsa 3 **

# Put data in pandas data frame
df1, fs, channels, p_names = load_data(h5file)
df1['sample'] = df1.index

# --- Get the probe events and MNE raw objects
# Get start of blocks as different types of epochs (1=start, 2=right, 3=left, 4=centre)
df1['protocol_change'] = df1['block_number'].diff()
df1['choice_events'] = df1.apply(lambda row: row.protocol_change if row.block_name == "start" else
                                 row.protocol_change * 2 if row.block_name == "probe_right" else
                                 row.protocol_change * 3 if row.block_name == "probe_left" else
                                 row.protocol_change * 4 if row.block_name == "probe_centre" else 0, axis=1)

# Create the events list for the protocol transitions
probe_events = df1[['choice_events']].to_numpy()
right_probe = 2
left_probe = 3
centre_probe = 4
event_dict = {'right_probe': right_probe, 'left_probe': left_probe, 'centre_probe': centre_probe}

# Drop non eeg data
drop_cols = [x for x in df1.columns if x not in channels]
drop_cols.extend(['MKIDX', 'EOG', 'ECG', "signal_AAI", 'protocol_change', 'choice_events'])
eeg_data = df1.drop(columns=drop_cols)

# Rescale the data (units are microvolts - i.e. x10^-6
eeg_data = eeg_data * 1e-6

# create an MNE info
m_info = mne.create_info(ch_names=list(eeg_data.columns), sfreq=fs, ch_types=['eeg' for ch in list(eeg_data.columns)])

# Set the montage (THIS IS FROM roi_spatial_filter.py)
standard_montage = mne.channels.make_standard_montage(kind='standard_1020')
standard_montage_names = [name.upper() for name in standard_montage.ch_names]
for j, channel in enumerate(eeg_data.columns):
    try:
        # make montage names uppercase to match own data
        standard_montage.ch_names[standard_montage_names.index(channel.upper())] = channel.upper()
    except ValueError as e:
        print(f"ERROR ENCOUNTERED: {e}")
m_info.set_montage(standard_montage, on_missing='ignore')

# Create the mne raw object with eeg data
m_raw = mne.io.RawArray(eeg_data.T, m_info, first_samp=0, copy='auto', verbose=None)

# set the reference to average
m_raw.set_eeg_reference(projection=True)

# Create the stim channel
info = mne.create_info(['STI'], m_raw.info['sfreq'], ['stim'])
stim_raw = mne.io.RawArray(probe_events.T, info)
m_raw.add_channels([stim_raw], force_update_info=True)


# ----- ICA ON BASELINE RAW DATA
# High pass filter
m_high = m_raw.copy()
# Take out the first 10 secs - TODO: figure out if this is needed for everyone
m_high.crop(tmin=10)
m_high.filter(l_freq=1., h_freq=40)
# Drop bad channels
# m_high.drop_channels(['TP9', 'TP10'])
# get baseline data
baseline_raw_data = df1.loc[df1['block_number'] == 2]
baseline_raw_start = baseline_raw_data['sample'].iloc[0] / m_high.info['sfreq']
baseline_raw_end = baseline_raw_data['sample'].iloc[-1] / m_high.info['sfreq']
baseline = m_high.copy()
baseline.crop(tmin=baseline_raw_start, tmax=baseline_raw_end)
# visualise the eog blinks
# eog_evoked = create_eog_epochs(baseline, ch_name=['EOG', 'ECG']).average()
# eog_evoked.apply_baseline(baseline=(None, -0.2))
# eog_evoked.plot_joint()
# do ICA
# baseline.drop_channels(['EOG', 'ECG'])
ica = ICA(n_components=15, max_iter='auto', random_state=97)
ica.fit(baseline)
# m_high.drop_channels(['EOG', 'ECG'])
# ica = ICA(n_components=15, max_iter='auto', random_state=97)
# ica.fit(m_high)
# Visualise
m_high.load_data()
ica.plot_sources(m_high, show_scrollbars=False)
ica.plot_components()
# Set ICA to exclued
ica.exclude = [1]  # ,14]
reconst_raw = m_raw.copy()
ica.apply(reconst_raw)
#-------------------------

# Get the epoch object
m_filt = reconst_raw.copy()
m_filt.filter(8, 14, n_jobs=1,  # use more jobs to speed up.
               l_trans_bandwidth=1,  # make sure filter params are the same
               h_trans_bandwidth=1)  # in each band and skip "auto" option.

events = mne.find_events(m_raw, stim_channel='STI')
reject_criteria = dict(eeg=100e-6)

left_chs = ['PO7=1']
right_chs = ['PO8=1']

# - - DO baseline epochs
fig_bl_eo1, aai_baseline_eo1, bl_dataframe_eo1, bl_epochs_eo1 = af.do_baseline_epochs(df1, m_filt, left_chs, right_chs, fig=None, fb_type="active", baseline_name='bl_eo1', block_number=2)
fig_bl_ec1, aai_baseline_ec1, bl_dataframe_ec1, bl_epochs_ec1 = af.do_baseline_epochs(df1, m_filt, left_chs, right_chs, fig=None, fb_type="active", baseline_name='bl_ec1', block_number=4)
fig_bl_eo2, aai_baseline_eo2, bl_dataframe_eo2, bl_epochs_eo2 = af.do_baseline_epochs(df1, m_filt, left_chs, right_chs, fig=None, fb_type="active", baseline_name='bl_eo2', block_number=83)
fig_bl_ec2, aai_baseline_ec2, bl_dataframe_ec2, bl_epochs_ec2 = af.do_baseline_epochs(df1, m_filt, left_chs, right_chs, fig=None, fb_type="active", baseline_name='bl_ec2', block_number=85)

epochs = mne.Epochs(m_filt, events, event_id=event_dict, tmin=-2, tmax=7, baseline=None,
                    preload=True, detrend=1)#, reject=reject_criteria)

# Do the CSD on the raw data
raw_csd = mne.preprocessing.compute_current_source_density(m_raw)
raw_csd.plot()


# Do the CSD on the evoked data for left and right probes
# TODO: figure out what this is actually supposed to show...
stiffness = 3
lambda2 = 0.001
fig = epochs['left_probe'].plot(events=events)
probe_left = epochs['left_probe'].average()
probe_left_csd = mne.preprocessing.compute_current_source_density(probe_left, stiffness=stiffness, lambda2=lambda2)
probe_left_csd.plot_topomap()

fig = epochs['right_probe'].plot(events=events)
probe_right = epochs['right_probe'].average()
probe_right_csd = mne.preprocessing.compute_current_source_density(probe_right, stiffness=stiffness, lambda2=lambda2)
probe_right_csd.plot_topomap()
probe_right_csd.plot_joint(title='Current Source Density')