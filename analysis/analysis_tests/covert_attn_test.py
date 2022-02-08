# TODO:
#   look at the psd of the whole signal & just occipital electrodes to find the peak alpha
#   make sure you're actually including this in the filter
#   Run this through the NFB auto - freq detection to see if it detects it
#   Also run through with CSP to see if it detects left/right attn
#   look at nfb alpha lateralisation for each block with the different electrode setups



import mne
import numpy as np

from pynfb.signal_processing.filters import ExponentialSmoother, FFTBandEnvelopeDetector
from utils.load_results import load_data
import pandas as pd
import plotly_express as px
import plotly.graph_objs as go
import analysis.analysis_functions as af
from mne.preprocessing import (ICA, create_eog_epochs, create_ecg_epochs,
                               corrmap)

task_data = {}
# h5file = "/Users/christopherturner/Documents/EEG_Data/system_testing/ksenia_cvsa/cvsa_02-05_15-39-15/experiment_data.h5" # Ksenia cvsa tasks 1
h5file = "/Users/christopherturner/Documents/EEG_Data/system_testing/ksenia_cvsa/cvsa_02-05_15-47-03/experiment_data.h5" # Ksenia cvsa tasks 2

# Put data in pandas data frame
df1, fs, channels, p_names = load_data(h5file)
df1['sample'] = df1.index

channels.append("signal_AAI")

df2 = pd.melt(df1, id_vars=['block_name', 'block_number', 'sample', 'choice', 'probe', 'answer', 'reward'],
                  value_vars=channels, var_name="channel", value_name='data')
aai_sc_data = df2.loc[df2['channel'] == "signal_AAI"].reset_index(drop=True)

left_electrode = df2.loc[df2['channel'] == "PO7"].reset_index(drop=True)
right_electrode = df2.loc[df2['channel'] == "PO8"].reset_index(drop=True)

fig = px.line(aai_sc_data, x=aai_sc_data.index, y="data", color='block_name', title=f"scalp aai")
fig.show()
fig = px.box(aai_sc_data, x='block_name', y="data", title="scalp aai")
fig.show()
pass

# ------- NFB LAB FILTERING
# Get left attention condition
eeg_data_pl = df1.loc[df1['block_name'] == 'probe_left']
drop_cols = [x for x in df1.columns if x not in channels]
drop_cols.extend(['MKIDX', 'EOG', 'ECG', 'signal_AAI'])
eeg_data_pl = eeg_data_pl.drop(columns=drop_cols)
# Get right attention condition
eeg_data_pr = df1.loc[df1['block_name'] == 'probe_right']
drop_cols = [x for x in df1.columns if x not in channels]
drop_cols.extend(['MKIDX', 'EOG', 'ECG', 'signal_AAI'])
eeg_data_pr = eeg_data_pr.drop(columns=drop_cols)

# Rescale the data (units are microvolts - i.e. x10^-6
eeg_data_pl = eeg_data_pl * 1e-6
eeg_data_pr = eeg_data_pr * 1e-6

bandpass = (8, 14) # TODO - get this right
smoothing_factor = 0.7
smoother = ExponentialSmoother(smoothing_factor)
n_samples = 1000
signal_estimator = FFTBandEnvelopeDetector(bandpass, fs, smoother, n_samples)

left_alpha_chs = "PO7=1"#;P5=1;O1=1"
right_alpha_chs = "PO8=1"
channel_labels = eeg_data_pl.columns

left_derived_pl = af.get_nfb_derived_sig(eeg_data_pl, left_alpha_chs, fs, channel_labels, signal_estimator)
right_derived_pl = af.get_nfb_derived_sig(eeg_data_pl, right_alpha_chs, fs, channel_labels, signal_estimator)
left_derived_pr = af.get_nfb_derived_sig(eeg_data_pr, left_alpha_chs, fs, channel_labels, signal_estimator)
right_derived_pr = af.get_nfb_derived_sig(eeg_data_pr, right_alpha_chs, fs, channel_labels, signal_estimator)

fig = px.line()
fig.add_scatter(y=left_derived_pl, name=f"left channels, left probe")
fig.add_scatter(y=right_derived_pl, name="right channels, left probe")
# fig.add_scatter(y=df1['signal_Alpha_Left'][:10000] * 1e-6, name="nfb")
fig.show()

fig = px.line()
fig.add_scatter(y=left_derived_pr, name=f"left channels, right probe")
fig.add_scatter(y=right_derived_pr, name="right channels, right probe")
# fig.add_scatter(y=df1['signal_Alpha_Left'][:10000] * 1e-6, name="nfb")
fig.show()




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
# # High pass filter
# m_high = m_raw.copy()
# # Take out the first 10 secs - TODO: figure out if this is needed for everyone
# m_high.crop(tmin=10)
# m_high.filter(l_freq=1., h_freq=40)
# # Drop bad channels
# m_high.drop_channels(['TP9', 'TP10'])
# # get baseline data
# # baseline_raw_data = df1.loc[df1['block_name'] == 'baseline']
# # baseline_raw_start = baseline_raw_data['sample'].iloc[0] / fs
# # baseline_raw_end = baseline_raw_data['sample'].iloc[-1] / fs
# # baseline = m_high.copy()
# # baseline.crop(tmin=baseline_raw_start, tmax=baseline_raw_end)
# # visualise the eog blinks
# # eog_evoked = create_eog_epochs(baseline, ch_name=['EOG', 'ECG']).average()
# # eog_evoked.apply_baseline(baseline=(None, -0.2))
# # eog_evoked.plot_joint()
# # do ICA
# # baseline.drop_channels(['EOG', 'ECG'])
# # ica = ICA(n_components=15, max_iter='auto', random_state=97)
# # ica.fit(baseline)
# m_high.drop_channels(['EOG', 'ECG'])
# ica = ICA(n_components=15, max_iter='auto', random_state=97)
# ica.fit(m_high)
# # Visualise
# m_high.load_data()
# ica.plot_sources(m_high, show_scrollbars=False)
# ica.plot_components()
# # Set ICA to exclued
# ica.exclude = [2]  # ,14]
# reconst_raw = m_raw.copy()
# ica.apply(reconst_raw)
#-------------------------



# Get the epoch object
m_filt = m_raw.copy()
m_filt.filter(8, 14, n_jobs=1,  # use more jobs to speed up.
               l_trans_bandwidth=1,  # make sure filter params are the same
               h_trans_bandwidth=1)  # in each band and skip "auto" option.

events = mne.find_events(m_raw, stim_channel='STI')
reject_criteria = dict(eeg=100e-6)

epochs = mne.Epochs(m_filt, events, event_id=event_dict, tmin=-2, tmax=7, baseline=(-1.5, -0.5),
                    preload=True, detrend=1, reject=reject_criteria)
# epochs.drop([19,22,27,32]) # Drop bads for 1st dataset
epochs.drop([7,17,27,28,29]) # Drop bads for 2nd dataset

fig = epochs.plot(events=events)

probe_left = epochs['left_probe'].average()
probe_right = epochs['right_probe'].average()
# fig2 = probe_left.plot(spatial_colors=True,  picks=['PO7', 'PO8'])
# fig2 = probe_right.plot(spatial_colors=True,  picks=['PO7', 'PO8'])

# # plot topomap#
# fig2 = probe_left.plot_joint()

# TODO Look at PSD of left and right channels for the left and right probes

# ----Look at the power for the epochs in the left and right channels for left and right probes
e_mean1, e_std1 = af.get_nfb_epoch_power_stats(epochs['left_probe'], fband=(8, 14), fs=1000, channel_labels=epochs.info.ch_names, chs=["PO7=1"])
e_mean2, e_std2 = af.get_nfb_epoch_power_stats(epochs['left_probe'], fband=(8, 14), fs=1000, channel_labels=epochs.info.ch_names,  chs=["PO8=1"])
af.plot_nfb_epoch_stats(e_mean1, e_std1, e_mean2, e_std2, name1="left_chs", name2="right_chs", title="left_probe")


e_mean1, e_std1 = af.get_nfb_epoch_power_stats(epochs['right_probe'], fband=(8, 14), fs=1000, channel_labels=epochs.info.ch_names, chs=["PO7=1"])
e_mean2, e_std2 = af.get_nfb_epoch_power_stats(epochs['right_probe'], fband=(8, 14), fs=1000, channel_labels=epochs.info.ch_names,  chs=["PO8=1"])
af.plot_nfb_epoch_stats(e_mean1, e_std1, e_mean2, e_std2, name1="left_chs", name2="right_chs", title='right_probe')

e_mean1, e_std1 = af.get_nfb_epoch_power_stats(epochs['centre_probe'], fband=(8, 14), fs=1000, channel_labels=epochs.info.ch_names, chs=["PO7=1"])
e_mean2, e_std2 = af.get_nfb_epoch_power_stats(epochs['centre_probe'], fband=(8, 14), fs=1000, channel_labels=epochs.info.ch_names,  chs=["PO8=1"])
af.plot_nfb_epoch_stats(e_mean1, e_std1, e_mean2, e_std2, name1="left_chs", name2="right_chs", title='centre_probe')


e_mean1, e_std1 = af.get_nfb_epoch_power_stats(epochs['right_probe'], fband=(8, 14), fs=1000, channel_labels=epochs.info.ch_names, chs=["PO7=1"])
e_mean2, e_std2 = af.get_nfb_epoch_power_stats(epochs['left_probe'], fband=(8, 14), fs=1000, channel_labels=epochs.info.ch_names,  chs=["PO7=1"])
af.plot_nfb_epoch_stats(e_mean1, e_std1, e_mean2, e_std2, name1="right_probe", name2="left_probe", title='left channels')

e_mean1, e_std1 = af.get_nfb_epoch_power_stats(epochs['right_probe'], fband=(8, 14), fs=1000, channel_labels=epochs.info.ch_names, chs=["PO8=1"])
e_mean2, e_std2 = af.get_nfb_epoch_power_stats(epochs['left_probe'], fband=(8, 14), fs=1000, channel_labels=epochs.info.ch_names,  chs=["PO8=1"])
af.plot_nfb_epoch_stats(e_mean1, e_std1, e_mean2, e_std2, name1="right_probe", name2="left_probe", title='right channels')


# - Get the power for each epoch

# - Average all the epochs for the PO7 channel - get the mean, and std for each point

# - plot the averaged epochs mean + stds

# LOOK AT ENVELOPE
probe_left.drop_channels(x for x in channels if x not in ['O1', 'O2', 'P3', 'P4', 'PO7', 'PO8'])
probe_left.apply_hilbert(picks=['O1', 'O2', 'P3', 'P4', 'PO7', 'PO8'], envelope=True, n_jobs=1, n_fft='auto', verbose=None)
probe_right.apply_hilbert(picks=['O1', 'O2', 'P3', 'P4', 'PO7', 'PO8'], envelope=True, n_jobs=1, n_fft='auto', verbose=None)
fig2 = probe_left.plot(spatial_colors=True)
fig2 = probe_right.plot(spatial_colors=True)

# Look at left and right evoked
left_chs = ['O1', 'P3', 'PO7']#['O1', 'PO3', 'PO7', 'P1', 'P3', 'P5', 'P7', 'P9', 'PZ', 'P0Z']
right_chs = ['O2', 'P4', 'PO8']#['O2', 'PO4', 'PO8', 'P2', 'P3', 'P6', 'P7', 'P10', 'PZ', 'P0Z']
picks = left_chs# + right_chs
# picks = ['P7', 'PO7', 'O1', 'OZ', 'PO8', 'P8', 'PO3', 'POZ', 'PO4', 'PO8']
evokeds = dict(left_probe=list(epochs_l['left_probe'].iter_evoked()),
               right_probe=list(epochs_l['right_probe'].iter_evoked()))
mne.viz.plot_compare_evokeds(evokeds, combine='mean')#, picks=picks)

# Look at left side vs right side for left probe
left_ix = mne.pick_channels(probe_left.info['ch_names'], include=right_chs)
right_ix = mne.pick_channels(probe_left.info['ch_names'], include=left_chs)
roi_dict = dict(left_ROI=left_ix, right_ROI=right_ix)
roi_evoked = mne.channels.combine_channels(probe_left, roi_dict, method='mean')
print(roi_evoked.info['ch_names'])
roi_evoked.plot()


# # Get signal envelope of left and right chans
# m_env = m_raw.copy()
#
# # Get alpha
# m_env.filter(8, 14, n_jobs=1,  # use more jobs to speed up.
#                l_trans_bandwidth=1,  # make sure filter params are the same
#                h_trans_bandwidth=1)  # in each band and skip "auto" option.
#
# m_env.drop_channels([ch for ch in m_info.ch_names if ch not in ['O2', 'O1']])
# m_env.apply_hilbert(picks=['O2', 'O1'], envelope=True, n_jobs=1, n_fft='auto', verbose=None)
pass

# TODO: ICA (to remove blinks etc)
#   source analysis on epochs