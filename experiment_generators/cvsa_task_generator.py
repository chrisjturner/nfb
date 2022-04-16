#!/usr/bin/env python

from participant_generator import ParticipantTaskGenerator
import platform

if __name__ == "__main__":

    if platform.system() == "Windows":
        userdir = "2354158T"
        mock_file_path = f'/Users/{userdir}/Documents/EEG_Data/pilot_202201_sham/0-nfb_task_ct02_01-26_16-33-42/experiment_data.h5'
    else:
        userdir = "christopherturner"
        mock_file_path = f'/Users/{userdir}/Documents/EEG_Data/pilot_202201/sh/scalp/0-nfb_task_SH01_01-11_15-50-56/experiment_data.h5'
    nfb_types = {"circle": 1, "bar": 2, "gabor": 3, "plot": 4, "posner":5}

    # Common settings
    participant_no = "cvsa_test"
    stream_name = "BrainVision RDA"
    band_low = 8
    band_high = 12
    t_filt_type = 'fft'
    composite_signal = "AAI"
    number_nfb_tasks = 10
    nfb_type = nfb_types['posner']
    # nfb_template = "nfb_template_graph.xml" #"nfb_template_gabor.xml"
    test_template = "cvsa_feedback.xml"
    nfb_template = "cvsa_feedback.xml"
    use_baseline_correction = 0
    baseline_cor_threshold = 0.2
    smooth_window = 100 # THIS IS AAI SMOOTHING
    enable_smoothing = 1 # THIS IS AAI SMOOTHING
    fft_window = 1000
    mock_reward_threshold = 0.089

    # Generate the settings for each session
    # NOTE!!: don't forget to freeze these once generated (so as to not loose randomisation
    tasks = {"baseline": "baseline.xml",
             "eye_calibration": "eye_calibration.xml",
             "test_task": test_template,
             "nfb_task": nfb_template}

    task_info = {}

    left_spatial_filter_scalp = ""
    right_spatial_filter_scalp = ""
    source_fb = False
    posner_test = 0
    for session in [0, 1]:
        if session == 0:
            # scalp
            left_spatial_filter_scalp = "PO7=1"#"PO7=1;P5=1;O1=1"
            right_spatial_filter_scalp = "PO8=1"#"PO8=1;P6=1;O2=1"
            mock_file = ''
        elif session == 1:
            # sham
            left_spatial_filter_scalp = "PO7=1"#;P5=1;01=1"
            right_spatial_filter_scalp = "PO8=1"#;P6=1;02=1"
            mock_file = mock_file_path
        for task, template in tasks.items():
            if task == "test_task":
                number_nfb_tasks = 10
                posner_test = 1
            elif task == "nfb_task":
                number_nfb_tasks = 10
                posner_test = 0


            Tsk = ParticipantTaskGenerator(participant_no=participant_no,
                                           stream_name=stream_name,
                                           band_low=band_low,
                                           band_high=band_high,
                                           t_filt_type=t_filt_type,
                                           composite_signal=composite_signal,
                                           experiment_prefix=f"{session}-{task}",
                                           template_file=template,
                                           right_spatial_filter_scalp=right_spatial_filter_scalp,
                                           left_spatial_filter_scalp=left_spatial_filter_scalp,
                                           source_fb=source_fb,
                                           number_nfb_tasks=number_nfb_tasks,
                                           mock_file=mock_file,
                                           baseline_cor_threshold=baseline_cor_threshold,
                                           use_baseline_correction=use_baseline_correction,
                                           smooth_window=smooth_window,
                                           enable_smoothing=enable_smoothing,
                                           fft_window=fft_window,
                                           mock_reward_threshold=mock_reward_threshold,
                                           nfb_type=nfb_type,
                                           posner_test=posner_test)
            Tsk.create_task(participant=participant_no)
