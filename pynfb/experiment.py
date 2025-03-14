import os
import platform
import re
from datetime import datetime
import logging
import random as r
import numpy as np
from PyQt5 import QtCore
from itertools import zip_longest, chain
import time

from PyQt5.QtWidgets import QDesktopWidget

from pynfb.inlets.montage import Montage
from pynfb.postprocessing.plot_all_fb_bars import plot_fb_dynamic
from pynfb.widgets.channel_trouble import ChannelTroubleWarning
from pynfb.widgets.helpers import WaitMessage
from pynfb.outlets.signals_outlet import SignalsOutlet
from .generators import run_eeg_sim, stream_file_in_a_thread, stream_generator_in_a_thread
from .inlets.ftbuffer_inlet import FieldTripBufferInlet
from .inlets.lsl_inlet import LSLInlet
from .inlets.channels_selector import ChannelsSelector
from .serializers.hdf5 import save_h5py, load_h5py, save_signals, load_h5py_protocol_signals, save_xml_str_to_hdf5_dataset, \
    save_channels_and_fs
from .serializers.xml_ import params_to_xml_file, params_to_xml, get_lsl_info_from_xml
from .serializers import read_spatial_filter
from .protocols import BaselineProtocol, FeedbackProtocol, ThresholdBlinkFeedbackProtocol, VideoProtocol, \
    ParticipantInputProtocol, ParticipantChoiceProtocol, ExperimentStartProtocol, FixationCrossProtocol, ImageProtocol, \
    GaborFeedbackProtocolWidgetPainter, ParticipantChoiceWidgetPainter, EyeCalibrationProtocol, \
    EyeCalibrationProtocolWidgetPainter, BaselineProtocolWidgetPainter, FixationCrossProtocolWidgetPainter, \
    PlotFeedbackWidgetPainter, BarFeedbackProtocolWidgetPainter, PosnerCueProtocol, PosnerCueProtocolWidgetPainter, \
    PosnerFeedbackProtocolWidgetPainter, ExperimentStartWidgetPainter, EyeTrackFeedbackProtocolWidgetPainter
from .signals import DerivedSignal, CompositeSignal, BCISignal
from .windows import MainWindow
from ._titles import WAIT_BAR_MESSAGES
import pandas as pd
import mne

import pylink

# helpers
def int_or_none(string):
    return int(string) if len(string) > 0 else None


class Experiment():
    def __init__(self, app, params):
        self.app = app
        self.params = params
        self.main_timer = None
        self.stream = None
        self.thread = None
        self.catch_channels_trouble = True
        self.mock_signals_buffer = None
        self.activate_trouble_catching = False
        self.main = None
        self.gabor_theta = r.choice(range(20, 180, 20)) # Init the gabor theta with a random angle
        self.rn_offset = r.choice([-5, 5, 0, 0]) # Init Random offset between +/- 5 degrees and 0 for Gabor orientation
        self.probe_loc = r.choice(["RIGHT", "LEFT"])
        self.probe_vis = r.choices([1,0], weights=[0.8, 0.2], k=1)[0] # 80% chance to show the probe
        self.cue_cond = r.choice([1])#[1, 2, 3]) # Even choice of 1=left, 2=right, 3=centre cue
        self.cue_random_start = 1 + r.uniform(0, 1) # random start between 1 and 2 seconds
        self.cue_duration = 1 # Duration of the cue (s)
        self.posner_stim = r.choice([1, 2]) # 1=left, 2=right
        self.posner_stim_time = None #6 + r.uniform(0, 2) # timing of posner stim
        # self.probe_dur = 0.05#32 # seconds # TODO: make this depend on screen refresh rate
        self.probe_random_start = 1 + r.uniform(0, 1) # TODO change the start of the probe
        # self.test_signal = (np.sin(2*np.pi*np.arange(1000*100)*0.5/1000)).astype(np.float32) #Test signal to be used for posner distractor colour
        self.test_signal = self.Randomwalk1D(100000)[1] #self.get_aai_from_pickle() #
        self.test_start = r.randint(0, int(len(self.test_signal)/2)) # randomly start somewhere in the test signal
        self.mean_reward_signal = 0
        self.median_eye_signal = 0
        self.fb_score = None
        self.cum_score = None
        self.calc_score = True
        self.choice_fb = None
        self.nfb_samps = 0
        self.percent_score = 0
        self.block_score = {}
        self.block_score_left = {}
        self.block_score_right = {}
        self.dir_name = "results_data"
        self.eye_session_folder = "eye_data"
        self.dummy_mode = not self.params['bUseEyeTracking']
        self.restart()
        self.el_tracker = self.init_eyelink()
        logging.info(f"{__name__}: ")
        pass

    def init_eyelink(self):
        print(f'INIT EYELINK')
        # Set this variable to True to run the script in "Dummy Mode"

        # get the screen resolution natively supported by the monitor
        scn_width, scn_height = 1280, 1024

        edf_fname = 'eye_nfb'

        # Set up a folder to store the EDF data files and the associated resources
        # e.g., files defining the interest areas used in each trial
        # results_folder = 'results'
        # if not os.path.exists(results_folder): #TODO: make a dialog to get the results path to use here (same as with posner task)
        #     os.makedirs(results_folder)
        results_folder = self.dir_name

        # We download EDF data file from the EyeLink Host PC to the local hard
        # drive at the end of each testing session, here we rename the EDF to
        # include session start date/time
        time_str = time.strftime("_%Y_%m_%d_%H_%M", time.localtime())
        session_identifier = edf_fname + time_str

        # create a folder for the current testing session in the "results" folder
        self.eye_session_folder = os.path.join(results_folder, session_identifier)
        print(f"ATTEMPTING TO CREATE SESSION FOLDER: {self.eye_session_folder}")
        if not os.path.exists(self.eye_session_folder):
            os.makedirs(self.eye_session_folder)
            print(f"CREATED SESSION FOLDER")

        if self.dummy_mode:
            el_tracker = pylink.EyeLink(None)
        else:
            try:
                el_tracker = pylink.EyeLink("100.1.1.1")
            except RuntimeError as error:
                print('ERROR:', error)

        # Step 2: Open an EDF data file on the Host PC
        self.edf_file = edf_fname + ".EDF"
        try:
            el_tracker.openDataFile(self.edf_file)
        except RuntimeError as err:
            print('ERROR:', err)
            # close the link if we have one open
            if el_tracker.isConnected():
                el_tracker.close()

        preamble_text = 'RECORDED BY %s' % os.path.basename(__file__)
        el_tracker.sendCommand("add_file_preamble_text '%s'" % preamble_text)

        el_tracker.setOfflineMode()
        eyelink_ver = 0  # set version to 0, in case running in Dummy mode
        if not self.dummy_mode:
            vstr = el_tracker.getTrackerVersionString()
            eyelink_ver = int(vstr.split()[-1].split('.')[0])
            # print out some version info in the shell
            print('Running experiment on %s, version %d' % (vstr, eyelink_ver))
        # File and Link data control
        # what eye events to save in the EDF file, include everything by default
        file_event_flags = 'LEFT,RIGHT,FIXATION,SACCADE,BLINK,MESSAGE,BUTTON,INPUT'
        # what eye events to make available over the link, include everything by default
        link_event_flags = 'LEFT,RIGHT,FIXATION,SACCADE,BLINK,BUTTON,FIXUPDATE,INPUT'
        # what sample data to save in the EDF data file and to make available
        # over the link, include the 'HTARGET' flag to save head target sticker
        # data for supported eye trackers
        if eyelink_ver > 3:
            file_sample_flags = 'LEFT,RIGHT,GAZE,HREF,RAW,AREA,HTARGET,GAZERES,BUTTON,STATUS,INPUT'
            link_sample_flags = 'LEFT,RIGHT,GAZE,GAZERES,AREA,HTARGET,STATUS,INPUT'
        else:
            file_sample_flags = 'LEFT,RIGHT,GAZE,HREF,RAW,AREA,GAZERES,BUTTON,STATUS,INPUT'
            link_sample_flags = 'LEFT,RIGHT,GAZE,GAZERES,AREA,STATUS,INPUT'
        el_tracker.sendCommand("file_event_filter = %s" % file_event_flags)
        el_tracker.sendCommand("file_sample_data = %s" % file_sample_flags)
        el_tracker.sendCommand("link_event_filter = %s" % link_event_flags)
        el_tracker.sendCommand("link_sample_data = %s" % link_sample_flags)

        print('EYETRACKER TRIAL SETUP')
        # get a reference to the currently active EyeLink connection
        el_tracker = pylink.getEYELINK()

        # put the tracker in the offline mode first
        el_tracker.setOfflineMode()

        # clear the host screen before we draw the backdrop
        el_tracker.sendCommand('clear_screen 0')

        # EYE TRACKER STUFF
        print('EYETRACKER TRIAL SETUP')
        # get a reference to the currently active EyeLink connection
        el_tracker = pylink.getEYELINK()

        # put the tracker in the offline mode first
        el_tracker.setOfflineMode()

        # clear the host screen before we draw the backdrop
        el_tracker.sendCommand('clear_screen 0')
        # OPTIONAL: draw landmarks and texts on the Host screen
        # In addition to backdrop image, You may draw simples on the Host PC to use
        # as landmarks. For illustration purpose, here we draw some texts and a box
        # For a list of supported draw commands, see the "COMMANDS.INI" file on the
        # Host PC (under /elcl/exe)
        # OPTIONAL: draw landmarks and texts on the Host screen
        # Draw the centre cue area (roughly)
        left = int(scn_width / 2.0) - 33
        top = int(scn_height / 2.0) - 33
        right = int(scn_width / 2.0) + 33
        bottom = int(scn_height / 2.0) + 33
        draw_cmd = 'draw_filled_box %d %d %d %d 1' % (left, top, right, bottom)
        el_tracker.sendCommand(draw_cmd)

        # draw the left target
        left = int(scn_width / 2.0) - 230
        top = int(scn_height / 2.0) - 17
        right = int(scn_width / 2.0) - 108
        bottom = int(scn_height / 2.0) + 105
        draw_cmd = 'draw_filled_box %d %d %d %d 1' % (left, top, right, bottom)
        el_tracker.sendCommand(draw_cmd)

        # draw the right target
        left = int(scn_width / 2.0) + 108
        top = int(scn_height / 2.0) - 17
        right = int(scn_width / 2.0) +230
        bottom = int(scn_height / 2.0) + 105
        draw_cmd = 'draw_filled_box %d %d %d %d 1' % (left, top, right, bottom)
        el_tracker.sendCommand(draw_cmd)
        # put tracker in idle/offline mode before recording
        el_tracker.setOfflineMode()

        # Start recording
        # arguments: sample_to_file, events_to_file, sample_over_link,
        # event_over_link (1-yes, 0-no)
        try:
            el_tracker.startRecording(1, 1, 1, 1)
        except RuntimeError as error:
            print("ERROR:", error)
            # abort_trial()
            return pylink.TRIAL_ERROR

        # Allocate some time for the tracker to cache some samples
        pylink.pumpDelay(100)
        return el_tracker

    def terminate_eyelink(self):
        """ Terminate the task gracefully and retrieve the EDF data file

        file_to_retrieve: The EDF on the Host that we would like to download
        win: the current window used by the experimental script
        """

        el_tracker = pylink.getEYELINK()

        if el_tracker.isConnected():
            # Terminate the current trial first if the task terminated prematurely
            error = el_tracker.isRecording()
            if error == pylink.TRIAL_OK:
                if el_tracker.isRecording():
                    # add 100 ms to catch final trial events
                    pylink.pumpDelay(100)
                    el_tracker.stopRecording()
                # send a message to mark trial end
                el_tracker.sendMessage('TRIAL_RESULT %d' % pylink.TRIAL_ERROR)

            # Put tracker in Offline mode
            el_tracker.setOfflineMode()

            # Clear the Host PC screen and wait for 500 ms
            el_tracker.sendCommand('clear_screen 0')
            pylink.msecDelay(500)

            # Close the edf data file on the Host
            el_tracker.closeDataFile()

            # Show a file transfer message on the screen
            msg = 'EDF data is transferring from EyeLink Host PC...'
            logging.info(msg)
            print(msg)

            # Download the EDF data file from the Host PC to a local data folder
            # parameters: source_file_on_the_host, destination_file_on_local_drive
            local_edf = os.path.join(self.eye_session_folder, 'eye_data' + '.EDF')
            print(f'EDF FILE PATH: {local_edf}')
            try:
                el_tracker.receiveDataFile(self.edf_file, local_edf)
            except RuntimeError as error:
                print('ERROR:', error)

            # Close the link to the tracker.
            el_tracker.close()


    def Randomwalk1D(self, n):  # n here is the no. of steps that we require
        # ADAPTED FROM: https://www.geeksforgeeks.org/random-walk-implementation-python/
        # TODO: put this in a more appropriate place
        x = 0
        y = 0
        step_size = 0.025
        avg_chunk_size = 20
        xposition = [0]  # starting from origin (0,0)
        yposition = [0]
        upp = 0.5
        for i in range(1, n + 1):
            step = np.random.uniform(0, 1)
            if step <= upp:  # if step is less than 0.5 we move up
                y += step_size  # moving up in u direction
            else:  # if step > upp:  # if step is greater than 0.5 we move down
                y += -step_size  # moving down in y direction
            x += 1

            xposition.append(x)
            # yposition.append(y)
            yposition += [y * l for l in list(np.ones(avg_chunk_size))]
            if 0.5 > yposition[-1] > 0.0:
                upp = 0.5
            elif -0.5 < yposition[-1] < 0.0:
                upp = 0.5
            elif 0.75 > yposition[-1] > 0.5:
                upp = 0.4
            elif -0.75 < yposition[-1] < -0.5:
                upp = 0.6
            elif 0.9 > yposition[-1] > 0.75:
                upp = 0.1
            elif -0.9 < yposition[-1] < -0.75:
                upp = 0.9
            elif yposition[-1] > 0.9:
                upp = 0.0
            elif yposition[-1] < -0.9:
                upp = 1
        return [xposition, yposition]

    def get_aai_from_pickle(self):
        if platform.system() == "Windows":
            userdir = "Chris" #"2354158T"
        else:
            userdir = "christopherturner"
        return pd.read_pickle(f'/Users/{userdir}/Documents/GitHub/nfb/analysis/cvsa_scripts/aai.pkl').to_list()

    def update(self):
        """
        Experiment main update action
        :return: None
        """
        # get next chunk
        # self.stream is a ChannelsSelector instance!
        chunk, other_chunk, timestamp = self.stream.get_next_chunk() if self.stream is not None else (None, None)
        if chunk is not None and self.main is not None:

            # update and collect current samples
            for i, signal in enumerate(self.signals):
                signal.update(chunk)
                # self.current_samples[i] = signal.current_sample

            # push current samples
            sample = np.vstack([np.array(signal.current_chunk) for signal in self.signals]).T.tolist()
            self.signals_outlet.push_chunk(sample)

            # record data
            if self.main.player_panel.start.isChecked():
                if self.samples_counter == 0:
                    # ------------- MORE EYE TRACKER STUFF -----------------------------------------

                    self.el_tracker.sendMessage(f'PROTOCOL_{self.current_protocol_index}-{self.protocols_sequence[self.current_protocol_index].name}_START')

                    # record_status_message : show some info on the Host PC
                    # here we show how many trial has been tested
                    status_msg = f'PROTOCOL {self.current_protocol_index}-{self.protocols_sequence[self.current_protocol_index].name}'
                    self.el_tracker.sendCommand("record_status_message '%s'" % status_msg)

                    # ------------------------------------------------------------------------------
                if self.params['bShowSubjectWindow']:
                    self.subject.figure.update_reward(self.reward.get_score())
                if self.samples_counter < self.experiment_n_samples:
                    chunk_slice = slice(self.samples_counter, self.samples_counter + chunk.shape[0])
                    self.raw_recorder[chunk_slice] = chunk[:, :self.n_channels]
                    self.raw_recorder_other[chunk_slice] = other_chunk
                    self.timestamp_recorder[chunk_slice] = timestamp
                    # for s, sample in enumerate(self.current_samples):
                    self.signals_recorder[chunk_slice] = sample
                    self.samples_counter += chunk.shape[0]

                    # Save the chunk size for data analysis
                    self.chunk_recorder[self.samples_counter - chunk.shape[0]:self.samples_counter] = 0
                    self.chunk_recorder[self.samples_counter - 1] = chunk.shape[0]
                    # logging.debug(f"SAMPLE COUNTER: {self.samples_counter}, CHUNK SIZE: {chunk.shape[0]}, TIME: {time.time()*1000}")

                    # catch channels trouble

                    if self.activate_trouble_catching:
                        if self.samples_counter > self.seconds:
                            self.seconds += 2 * self.freq
                            raw_std_new = np.std(self.raw_recorder[int(self.samples_counter - self.freq):
                                                                   self.samples_counter], 0)
                            if self.raw_std is None:
                                self.raw_std = raw_std_new
                            else:
                                if self.catch_channels_trouble and any(raw_std_new > 7 * self.raw_std):
                                    w = ChannelTroubleWarning(parent=self.main)
                                    w.pause_clicked.connect(self.handle_channels_trouble_pause)
                                    w.closed.connect(
                                        lambda: self.enable_trouble_catching(w)
                                    )
                                    w.show()
                                    self.catch_channels_trouble = False
                                self.raw_std = 0.5 * raw_std_new + 0.5 * self.raw_std

            # redraw signals and raw data
            self.main.redraw_signals(sample, chunk, self.samples_counter, self.current_protocol_n_samples)
            if self.params['bPlotSourceSpace']:
                self.source_space_window.update_protocol_state(chunk)

            # redraw protocols
            is_half_time = self.samples_counter >= self.current_protocol_n_samples // 2
            current_protocol = self.protocols_sequence[self.current_protocol_index]
            if current_protocol.mock_previous > 0:
                samples = [signal.current_chunk[-1] for signal in current_protocol.mock]
            elif current_protocol.mock_samples_file_path is not None:
                samples = self.mock_signals_buffer[self.samples_counter % self.mock_signals_buffer.shape[0]]
            else:
                samples = sample[-1]

            # self.reward.update(samples[self.reward.signal_ind], chunk.shape[0])
            if (self.main.player_panel.start.isChecked() and
                    self.samples_counter - chunk.shape[0] < self.experiment_n_samples):
                self.reward_recorder[
                self.samples_counter - chunk.shape[0]:self.samples_counter] = self.reward.get_score()

            if self.main.player_panel.start.isChecked():
                # subject update
                if self.params['bShowSubjectWindow']:
                    mark = self.subject.update_protocol_state(samples, self.reward, chunk_size=chunk.shape[0],
                                                              is_half_time=is_half_time)
                    # if no offset, correct answer is YES, otherwise, correct answer is NO
                    # TODO: make this more generic - i.e. doesn't just depend on rn_offset (gabor theta angle) - combine with other similar recorders like posner one
                    answer = 0
                    choice = None
                    if current_protocol.input_protocol:
                        # Make sure choice is only shown for short duration
                        if isinstance(current_protocol.widget_painter, ParticipantChoiceWidgetPainter):
                            current_protocol.widget_painter.current_sample_idx = self.samples_counter
                        answer = 1
                        if self.rn_offset:
                            answer = 2
                        # 'yes' response = 1, 'no' response = 2, lack of response = 0
                        choice = current_protocol.response_key
                        # print(f"ANS: {answer}, OFF: {self.rn_offset}, CHOICE: {choice}")

                        # If there is a response key, change the text to a green tick or red cross
                        if choice:
                            self.choice_fb = "✔" if choice == answer else "✖"
                else:
                    mark = None
                    choice = None
                    answer = None
                self.mark_recorder[self.samples_counter - chunk.shape[0]:self.samples_counter] = 0
                self.mark_recorder[self.samples_counter - 1] = int(mark or 0)

                self.choice_recorder[self.samples_counter - chunk.shape[0]:self.samples_counter] = 0
                self.choice_recorder[self.samples_counter - 1] = int(choice or 0)
                self.answer_recorder[self.samples_counter - chunk.shape[0]:self.samples_counter] = answer
                # self.answer_recorder[self.samples_counter - 1] = int(answer or 0)

            # If posner cue, update the cue after random delay
            cue_cond = None
            if isinstance(current_protocol.widget_painter, PosnerCueProtocolWidgetPainter):
                cue_dur_samp = self.freq * (self.cue_duration) # Cue duration is 100ms
                cue_start_samp = round(self.freq * self.cue_random_start)
                cue_end_samp = round(cue_start_samp + cue_dur_samp)
                self.current_protocol_n_samples = cue_end_samp # End the cue after the cue is displayed
                if cue_start_samp <= self.samples_counter < cue_end_samp:
                    cue_cond = 0
                    if self.cue_cond == 1:
                        cue_cond = 1
                        # print("CUE LEFT")
                        current_protocol.widget_painter.left_cue()
                    if self.cue_cond == 2:
                        cue_cond = 2
                        # print("CUE RIGHT")
                        current_protocol.widget_painter.right_cue()
                    if self.cue_cond == 3:
                        cue_cond = 3
                        # print("CUE CENTER")
                        current_protocol.widget_painter.center_cue()
                    # logging.info(
                    #     f"CUE COND: {self.cue_cond}, CUE DURATION (samps): {cue_dur_samp}, CUE START (time): {self.cue_random_start}, CUE START (samp) {cue_start_samp}, CUE END (samp): {cue_end_samp}, CUE ACTUAL SAMP START: {self.samples_counter}")

            self.cue_recorder[self.samples_counter - chunk.shape[0]:self.samples_counter] = 0
            self.cue_recorder[self.samples_counter - 1] = int(cue_cond or 0)


            if isinstance(current_protocol.widget_painter, ExperimentStartWidgetPainter):
                # finish the start protocol when the participant presses space
                if current_protocol.hold == False:
                                        # End the protocol immediately if the participant presses a key
                                        self.current_protocol_n_samples = self.samples_counter


            # Update the posner feedback task based on the previous cue

            self.response_recorder[self.samples_counter - chunk.shape[0]:self.samples_counter] = 0

            posner_stim = None
            posner_stim_time = None
            if isinstance(current_protocol.widget_painter, PosnerFeedbackProtocolWidgetPainter):
                current_protocol.widget_painter.train_side = self.cue_cond
                # Remove the stim cross on either the valid or invalid side
                stim_samp = round(self.freq * self.posner_stim_time)
                test_samp_idx = int((self.test_start + self.samples_counter))
                current_test_samp = self.test_signal[test_samp_idx]
                current_protocol.widget_painter.test_signal_sample = current_test_samp
                stimuli_duration = 0.1 # Duration of posner stimuli (s)
                if self.samples_counter >= stim_samp:
                    posner_stim = self.posner_stim
                    if current_protocol.enable_posner:
                        current_protocol.widget_painter.stim = True
                    if self.samples_counter > stim_samp + stimuli_duration * self.freq:
                        current_protocol.widget_painter.stim_side = 0
                        posner_stim_time = int(0)
                    else:
                        posner_stim_time = int(0)#int(time.time()*1000)
                        current_protocol.widget_painter.stim_side = self.posner_stim
                    # logging.debug(f"POSNER SAMPLE START (samp): {stim_samp}, ACTUAL STRT SAMP: {self.samples_counter}")
                    stim_response_period = 2 # time allowed for the participant to react to the stimulus
                    if not current_protocol.widget_painter.kill:
                        current_protocol.widget_painter.kill = True
                        # self.current_protocol_n_samples = self.samples_counter + (self.freq * stim_response_period) # Allow the protocol to end after the stimulus is displayed
                    if self.samples_counter >= self.current_protocol_n_samples:
                        # end the protocol if the participant hasn't responded in time
                        # NOTE: Must have the max experiment samples larger than the posner feedback + 2 otherwise can get stuck todo: fix this
                        self.current_protocol_n_samples = self.samples_counter
                        current_protocol.hold = False
                        posner_stim_time = int(current_protocol.widget_painter.stim_onset_time) # Make sure to record the posner stim time if the participant doesn't get it
                    elif current_protocol.hold == False:
                        # End the protocol immediately if the participant presses a key
                        self.current_protocol_n_samples = self.samples_counter
                        posner_stim_time = int(current_protocol.widget_painter.stim_onset_time)
                        logging.debug(f"HOLD DISABLED AT {time.time()*1000}")
                        logging.debug(f"KEY PRESS TIME: {self.subject.key_press_time}")
                        self.response_recorder[self.samples_counter - 1] = int(self.subject.key_press_time or 0)
                else:
                    current_protocol.hold = True


            self.posnerstim_recorder[self.samples_counter - chunk.shape[0]:self.samples_counter] = 0
            self.posnerstim_recorder[self.samples_counter - 1] = int(posner_stim_time or 0)

            self.posnerdir_recorder[self.samples_counter - chunk.shape[0]:self.samples_counter] = 0
            self.posnerdir_recorder[self.samples_counter - 1] = int(posner_stim or 0)

            # If probe, display probe at random time after beginning of delay
            probe_val = None
            if current_protocol.show_probe and self.probe_vis:
                #get probe duration in samples
                if current_protocol.probe_duration == 0:
                    probe_dur_samp = self.current_protocol_n_samples
                else:
                    probe_dur_samp = self.freq * (current_protocol.probe_duration * 1e-3)
                probe_start_samp = round(self.freq * self.probe_random_start)
                # probe_dur_start = probe_dur_samp + probe_start_samp
                probe_end_samp = round(probe_start_samp + probe_dur_samp)
                if probe_start_samp <= self.samples_counter < probe_end_samp:
                    # display probe
                    logging.debug(f"PROBE COMMANDED TIME: {time.time() * 1000}")
                    current_protocol.widget_painter.probe = True
                    current_protocol.widget_painter.probe_loc = self.probe_loc
                    # Add probe to probe recorder - Left probe = 2, RIght probe = 1, no probe = 0 or nan
                    probe_val = 0
                    if self.probe_loc == "RIGHT":
                        probe_val = 1
                    elif self.probe_loc == "LEFT":
                        probe_val = 2
                    logging.info(f"{__name__}: PROTOCOL: {current_protocol.name}, PROBE_DUR[ms]: {current_protocol.probe_duration}, PROBE LOC: {self.probe_loc} = {int(probe_val)}, SAMP = {self.samples_counter}, PROBEST: {probe_start_samp}, PROBEEND: {probe_end_samp}, CHUNK SHAPE: {chunk.shape[0]}")
                else:
                    current_protocol.widget_painter.probe = False

            # Update the probe for the eye calibration stage
            if isinstance(current_protocol.widget_painter, EyeCalibrationProtocolWidgetPainter):
                current_protocol.widget_painter.current_sample_idx = self.samples_counter
                current_probe_loc = current_protocol.widget_painter.probe_loc[current_protocol.widget_painter.position_no]
                probe_positions = ["LT", "MT", "RT", 'LM', 'MM', 'RM', 'LB', 'MB', 'RB', 'CROSS']
                # Get the value to save in the data: left=10, right=11, top=12, bottom=13, cross=14
                probe_val = probe_positions.index(current_probe_loc) + 10
                self.probe_recorder[self.samples_counter - chunk.shape[0]:self.samples_counter] = probe_val
            else:
                self.probe_recorder[self.samples_counter - chunk.shape[0]:self.samples_counter] = 0
            self.probe_recorder[self.samples_counter - 1] = int(probe_val or 0)

            # change protocol if current_protocol_n_samples has been reached
            if self.samples_counter >= self.current_protocol_n_samples and not self.test_mode:
                # If baseline protocol, calculate average of reward signal
                if isinstance(current_protocol, BaselineProtocol):
                    reward_signal_id = current_protocol.reward_signal_id
                    reward_sig = self.signals_recorder[~np.isnan(self.signals_recorder).any(axis=1)]
                    reward_sig = reward_sig[:,reward_signal_id]
                    self.mean_reward_signal = np.median(reward_sig)
                    print(f"len signal: {len(reward_sig)}, mean: {reward_sig.mean()}, median: {np.median(reward_sig)}, signal: {reward_sig}")

                # If fixation cross, calculate the median of the eye movement signal (assuming this is EOG-ECG)
                if isinstance(current_protocol, FixationCrossProtocol):
                    if current_protocol.m_signal_id:
                        eye_signal_id = current_protocol.m_signal_id
                        eye_signal = self.signals_recorder[~np.isnan(self.signals_recorder).any(axis=1)]
                        eye_signal = eye_signal[:,eye_signal_id]
                        self.median_eye_signal = np.median(eye_signal)
                        logging.info(f"MEDIAN EYE SIGNAL: {self.median_eye_signal}")

                if isinstance(current_protocol.widget_painter, EyeTrackFeedbackProtocolWidgetPainter):
                    current_protocol.widget_painter.centre_fixation = self.median_eye_signal
                    current_protocol.widget_painter.eye_range = current_protocol.eye_range


                # Record the reward from feedback only for the current protocol
                if isinstance(current_protocol, FeedbackProtocol):
                    if self.calc_score:
                        self.calc_score = False # Only calculate the score once, just after the feedback protocol finishes
                        self.nfb_samps = self.current_protocol_n_samples
                        print(f"SCORE CALC - SAMP: {self.samples_counter}")
                        if self.fb_score is not None:
                            logging.info("fb-cum score")
                            self.fb_score = self.reward.get_score() - self.cum_score
                            self.cum_score = self.reward.get_score()
                        else:
                            logging.info("fbscore reset")
                            self.cum_score = self.reward.get_score()
                            self.fb_score = self.reward.get_score()
                        logging.debug(f"SAMP: {self.samples_counter}, fBSCORE: {self.fb_score}, CUMSCORE: {self.cum_score}, SELF.REWARD: {self.reward.get_score()}")

                        # Calculate the percent score for the feedback block
                        nfb_duration = self.nfb_samps
                        max_reward = round(nfb_duration / self.freq / self.reward.rate_of_increase)
                        self.percent_score = round((self.fb_score / max_reward) * 100)
                        if self.cue_cond in [1, 2]:
                            # Only append the score for averaging if it is not a center condition
                            self.block_score[self.current_protocol_index] = self.percent_score
                        if self.cue_cond == 1:
                            self.block_score_left[self.current_protocol_index] = self.percent_score
                        elif self.cue_cond == 2:
                            self.block_score_right[self.current_protocol_index] = self.percent_score
                        logging.debug(
                            f"PROTOCOL: {self.current_protocol_index}, MAX SCORE: {max_reward}, n_SAMPS: {nfb_duration}, freq: {self.freq}, rateInc: {self.reward.rate_of_increase}, SCORE: {self.fb_score}, PERCENT SCORE: {self.percent_score}")
                        logging.debug(f"BLOCK SCORE: {self.block_score}")
                        logging.debug(f"LEFT SCORE: {self.block_score_left}")
                        logging.debug(f"RIGHT SCORE: {self.block_score_right}")
                # only change if not a pausing protocol
                if current_protocol.hold:
                    # don't switch protocols if holding
                    pass
                else:
                    # Reset the hold flag on hold protocols
                    if current_protocol.input_protocol:
                        current_protocol.hold = True
                    # reset the flag to calculate the score at end of FB protocol
                    self.calc_score = True
                    # Take into account any extra accumulated score due to holding
                    self.cum_score = self.reward.get_score()
                    logging.debug(
                        f"!! END !! - SAMP: {self.samples_counter}, fBSCORE: {self.fb_score}, CUMSCORE: {self.cum_score}, SELF.REWARD: {self.reward.get_score()},"
                        f"TIMESTAMP: {self.timestamp_recorder[self.samples_counter]}, PROTOCOL_{self.current_protocol_index}-{self.protocols_sequence[self.current_protocol_index].name}")
                    self.el_tracker.sendMessage(f'PROTOCOL_{self.current_protocol_index}-{self.protocols_sequence[self.current_protocol_index].name}_END')
                    self.next_protocol()

    def enable_trouble_catching(self, widget):
        self.catch_channels_trouble = not widget.ignore_flag

    def start_test_protocol(self, protocol):
        print('Experiment: test')
        if not self.main_timer.isActive():
            self.main_timer.start(1000 * 1. / self.freq)
        self.samples_counter = 0
        self.main.signals_buffer *= 0
        self.test_mode = True

        if self.params['bShowSubjectWindow']:
            self.subject.change_protocol(protocol)

    def close_test_protocol(self):
        if self.main_timer.isActive():
            self.main_timer.stop()
        self.samples_counter = 0
        self.main.signals_buffer *= 0
        self.test_mode = False

    def handle_channels_trouble_pause(self):
        print('pause clicked')
        if self.main.player_panel.start.isChecked():
            self.main.player_panel.start.click()

    def handle_channels_trouble_continue(self, pause_enabled):
        print('continue clicked')
        if not pause_enabled and not self.main.player_panel.start.isChecked():
            self.main.player_panel.start.click()

    def next_protocol(self):
        """
        Change protocol
        :return: None
        """
        logging.debug(
            f"NEXT PROTOCOL START TIMESTAMP: {self.timestamp_recorder[self.samples_counter]}, PROTOCOL_{self.current_protocol_index}-{self.protocols_sequence[self.current_protocol_index].name}")
        # save raw and signals samples asynchronously
        protocol_number_str = 'protocol' + str(self.current_protocol_index+1)

        # descale signals:
        signals_recordings = np.array([signal.descale_recording(data)
                                       for signal, data in
                                       zip(self.signals, self.signals_recorder[:self.samples_counter].T)]).T

        # close previous protocol
        self.protocols_sequence[self.current_protocol_index].close_protocol(
            raw=self.raw_recorder[:self.samples_counter],
            signals=signals_recordings,
            protocols=self.protocols,
            protocols_seq=[protocol.name for protocol in self.protocols_sequence[:self.current_protocol_index + 1]],
            raw_file=self.dir_name + 'experiment_data.h5',
            marks=self.mark_recorder[:self.samples_counter])

        save_signals(self.dir_name + 'experiment_data.h5', self.signals, protocol_number_str,
                     raw_data=self.raw_recorder[:self.samples_counter],
                     timestamp_data=self.timestamp_recorder[:self.samples_counter],
                     raw_other_data=self.raw_recorder_other[:self.samples_counter],
                     signals_data=signals_recordings,
                     reward_data=self.reward_recorder[:self.samples_counter],
                     protocol_name=self.protocols_sequence[self.current_protocol_index].name,
                     mock_previous=self.protocols_sequence[self.current_protocol_index].mock_previous,
                     mark_data=self.mark_recorder[:self.samples_counter],
                     choice_data=self.choice_recorder[:self.samples_counter],
                     answer_data=self.answer_recorder[:self.samples_counter],
                     posner_stim_data = self.posnerdir_recorder[:self.samples_counter],
                     posner_stim_time = self.posnerstim_recorder[:self.samples_counter],
                     response_data = self.response_recorder[:self.samples_counter],
                     cue_data=self.cue_recorder[:self.samples_counter], # TODO: make this an attribute not a dataset
                     probe_data=self.probe_recorder[:self.samples_counter],
                     chunk_data=self.chunk_recorder[:self.samples_counter])

        logging.debug(
            f"NEXT PROTOCOL SIG SAVED TIMESTAMP: {self.timestamp_recorder[self.samples_counter]}")

        # reset samples counter
        previous_counter = self.samples_counter
        self.samples_counter = 0
        if self.protocols_sequence[self.current_protocol_index].update_statistics_in_the_end:
            self.main.time_counter1 = 0
            self.main.signals_viewer.reset_buffer()
        self.seconds = self.freq

        # list of real fb protocols (number in protocol sequence)
        if isinstance(self.protocols_sequence[self.current_protocol_index], FeedbackProtocol):
            if self.protocols_sequence[self.current_protocol_index].mock_previous == 0:
                self.real_fb_number_list += [self.current_protocol_index + 1]
        elif self.protocols_sequence[self.current_protocol_index].as_mock:
            self.real_fb_number_list += [self.current_protocol_index + 1]

        if self.current_protocol_index < len(self.protocols_sequence) - 1:

            # update current protocol index and n_samples
            self.current_protocol_index += 1
            current_protocol = self.protocols_sequence[self.current_protocol_index]
            self.current_protocol_n_samples = self.freq * (
                    self.protocols_sequence[self.current_protocol_index].duration +
                    np.random.uniform(0, self.protocols_sequence[self.current_protocol_index].random_over_time))

            # Reset participant key
            current_protocol.response_key = None
            # Update gabor patch angle for next gabor
            # TODO: make this more generic (only dependant on the protocol)
            bc_threshold = None
            if isinstance(current_protocol.widget_painter, (GaborFeedbackProtocolWidgetPainter, PlotFeedbackWidgetPainter, BarFeedbackProtocolWidgetPainter, PosnerFeedbackProtocolWidgetPainter)):
                self.gabor_theta = r.choice(range(20, 180, 20))
                logging.info(f"GABOR THETA: {self.gabor_theta}")
                current_protocol.widget_painter.gabor_theta = self.gabor_theta

                # Only update the threshold if we aren't doing mock/sham
                if current_protocol.mock_samples_file_path is None:
                    if self.params['bUseBCThreshold']:
                        # update the threshold for the Gabor feedback protocol with variable percentage
                        # TODO: also make this more generic (for all feedback protocols - not just Gabor)
                        reward_bound = self.params['dBCThresholdAdd'] # percent to add to the bias #
                        # TODO: how to handle negative bias (currently it makes the test easier if they have a negative bias)
                        bc_threshold = self.mean_reward_signal + (reward_bound)# * self.mean_reward_signal)
                        logging.info(f"MEAN REWARD SIG: {self.mean_reward_signal}, R THRESHOLD: {bc_threshold}, BC ADD: {reward_bound}")
                        current_protocol.widget_painter.r_threshold = bc_threshold
                    elif self.params['bUseAAIThreshold'] and isinstance(current_protocol.widget_painter, (PosnerFeedbackProtocolWidgetPainter)):
                        # Update the AAI mean and max threshold settings
                        current_protocol.widget_painter.r_threshold = self.params['dAAIThresholdMean']
                        current_protocol.widget_painter.max_th = self.params['dAAIThresholdMax']
                else:
                    # TODO: create a mock baseline threshold gui field
                    bc_threshold = current_protocol.mock_reward_threshold
                    logging.info(f"MOCK R THRESHOLD: {bc_threshold}")
                    current_protocol.widget_painter.r_threshold = bc_threshold

            # if self.nfb_samps and self.fb_score !=None:
            #     nfb_duration = self.nfb_samps
            #     max_reward = round(nfb_duration / self.freq / self.reward.rate_of_increase)
            #     self.percent_score = round((self.fb_score/max_reward )* 100)
            #     self.block_score.append(self.percent_score)
            #     logging.info(f"PROTOCOL: {self.current_protocol_index}, MAX SCORE: {max_reward}, n_SAMPS: {nfb_duration}, freq: {self.freq}, rateInc: { self.reward.rate_of_increase}, SCORE: {self.fb_score}, PERCENT SCORE: {self.percent_score}")
            # if current_protocol.widget_painter.show_reward and isinstance(current_protocol.widget_painter, BaselineProtocolWidgetPainter):
            #     current_protocol.widget_painter.set_message( f'{self.percent_score} %')

            # update the movement threshold for feedback protocol
            if isinstance(current_protocol.widget_painter, (PosnerFeedbackProtocolWidgetPainter)):
                eye_threshold = self.median_eye_signal + current_protocol.eye_range/2 * 0.1 # TODO - calibrate this
                logging.info(f"MED EYE SIGNAL: {self.median_eye_signal}, THRESHOLD: {eye_threshold}")
                current_protocol.widget_painter.m_threshold = eye_threshold

            # Update the choice gabor angle, score, and sample idx
            if isinstance(current_protocol.widget_painter, ParticipantChoiceWidgetPainter):
                self.rn_offset = r.choice([-5, 5, 0, 0])
                logging.info(f"CHOICE THETA: {self.gabor_theta + self.rn_offset}")
                current_protocol.widget_painter.gabor_theta = self.gabor_theta + self.rn_offset
                current_protocol.widget_painter.previous_score = self.percent_score
                # current_protocol.widget_painter.redraw_state(0,0)
                current_protocol.widget_painter.current_sample_idx = 0

            # Get the start of the test signal (random value between 0 and 100000-cur protocol length - buffer(1000)
            logging.debug(f"test_sig start: {0}, test_sig end: {100000-self.current_protocol_n_samples}, cur samps: {self.current_protocol_n_samples}")
            # if isinstance(current_protocol, BaselineProtocol):
            #     self.test_start = 0
            # else:
            #     #TODO: fix this test signal
            #     self.test_start = r.randrange(0, 100000 - self.current_protocol_n_samples, 1)

            # Update the posner cue side
            if isinstance(current_protocol.widget_painter, PosnerCueProtocolWidgetPainter):
                if current_protocol.posner_test:
                    self.cue_cond = r.choice([1])#, 2, 3]) # Only have the middle condition for the test blocks
                else:
                    self.cue_cond = r.choice([1])#, 2])
                self.cue_random_start = 1 + r.uniform(0, 1)  # random start between 1 and 2 seconds
                cue_dict = {1:"LEFT", 2:"RIGHT", 3:"CENTER"}
                logging.info(f"CUE CONDITION: {cue_dict[self.cue_cond]}")
                # Update the reward to flip the calculation (if on the right side) - NOTE: this assumes a leftward AAI
                # TODO: make all this more generic!! (maybe pull out the ability to cue to the top level and randomly generate the directions outside the experiment)
                if self.cue_cond in [1, 3]:
                    self.reward.reward_factor = 1
                elif self.cue_cond == 2:
                    self.reward.reward_factor = -1

            # Update the next stim (left or right)
            if isinstance(current_protocol.widget_painter, PosnerFeedbackProtocolWidgetPainter):
                current_protocol.widget_painter.stim = False
                # Have weights for valid and invalid cues
                valid_cue_weight = 70
                if self.cue_cond == 1:
                    self.posner_stim = r.choices([1, 2], weights=(valid_cue_weight, 100-valid_cue_weight))[0]
                elif self.cue_cond == 2:
                    self.posner_stim = r.choices([1, 2], weights=(100-valid_cue_weight, valid_cue_weight))[0]
                else:
                    self.posner_stim = r.choice([1,2])
                reaction_buffer = 5
                max_stim_var_time = 2
                self.posner_stim_time = current_protocol.duration - reaction_buffer + r.uniform(0, max_stim_var_time) # NOTE: the actual nfb duration will be specified duration - reaction_buffer + rand(0,max_stim_var_time). the reaction buffer needs to be bigger than (max_stim_var_time+posner_duration) otherwise can just end
                current_protocol.hold = True

            # Update the probe location, visibility, and start time
            if current_protocol.show_probe:
                if current_protocol.probe_loc == "RAND":
                    self.probe_loc = r.choice(["RIGHT", "LEFT"])
                    self.probe_vis = r.choices([1, 0], weights=[0.8, 0.2], k=1)[0]
                    self.probe_random_start = 1 + r.uniform(0, 1)
                else:
                    self.probe_loc = current_protocol.probe_loc
                    self.probe_vis = 1
                    self.probe_random_start = 0

            # Update participant choice fb (only do this if there is feedback to display
            if self.choice_fb:
                if isinstance(current_protocol.widget_painter, FixationCrossProtocolWidgetPainter):
                    current_protocol.widget_painter.text = self.choice_fb
                    print(f"PARTICIPANT FB: {self.choice_fb}")
                    color = "#00FF00" if self.choice_fb == "✔" else "#FF0000"
                    current_protocol.widget_painter.text_color = color
                    self.choice_fb = None

            if current_protocol.show_pc_score_after:
                # display the previous percent score if fixation cross protocol
                if isinstance(current_protocol.widget_painter, FixationCrossProtocolWidgetPainter):
                    block_average_score = round(np.mean(list(self.block_score.values())))
                    block_average_score_left = round(np.mean(list(self.block_score_left.values())))
                    block_average_score_right = round(np.mean(list(self.block_score_right.values())))
                    # current_protocol.widget_painter.text = f"{self.percent_score} %"
                    block_best_score = round(np.max(list(self.block_score.values())))
                    current_protocol.widget_painter.text = f"Total average score: {block_average_score} % <br> left avg: {block_average_score_left} % <br> right avg: {block_average_score_right} <br> Best: {block_best_score}"
                    logging.info(f"BLOCK AVERAGE SCORE: {block_average_score}")


            # prepare mock from raw if necessary
            if current_protocol.mock_previous:
                random_previos_fb = None
                if len(self.real_fb_number_list) > 0:
                    random_previos_fb = self.real_fb_number_list[np.random.randint(0, len(self.real_fb_number_list))]
                if current_protocol.shuffle_mock_previous:
                    current_protocol.mock_previous = random_previos_fb
                print('MOCK from protocol # current_protocol.mock_previous')
                if current_protocol.mock_previous == self.current_protocol_index:
                    mock_raw = self.raw_recorder[:previous_counter]
                    mock_signals = self.signals_recorder[:previous_counter]
                else:
                    mock_raw = load_h5py(self.dir_name + 'experiment_data.h5',
                                         'protocol{}/raw_data'.format(current_protocol.mock_previous))
                    mock_signals = load_h5py(self.dir_name + 'experiment_data.h5',
                                             'protocol{}/signals_data'.format(current_protocol.mock_previous))
                # print(self.real_fb_number_list)

                current_protocol.prepare_raw_mock_if_necessary(mock_raw, random_previos_fb, mock_signals)

            # change protocol widget
            if self.params['bShowSubjectWindow']:
                self.subject.change_protocol(current_protocol)
            if current_protocol.mock_samples_file_path is not None:
                logging.info(f"mockpath: {current_protocol.mock_samples_file_path}, mockprotocol: {current_protocol.mock_samples_protocol}, actual_mock_protocol: protocol{self.current_protocol_index}")
                self.mock_signals_buffer = load_h5py_protocol_signals(
                    current_protocol.mock_samples_file_path,
                    f"protocol{self.current_protocol_index+1}") # TODO: [ ]fix this - it only works if there are the same number of protocols in sham and real (study must be identical)
                    # current_protocol.mock_samples_protocol)
            self.main.status.update()

            if bc_threshold:
                # if using a baseline-corrected threshold
                self.reward.threshold = bc_threshold
            else:
                self.reward.threshold = self.params['dAAIThresholdMean']#current_protocol.reward_threshold

            logging.info(f"BC THRESHOLD: {bc_threshold}, RW THRESHOLD: {self.reward.threshold}")
            reward_signal_id = current_protocol.reward_signal_id
            print(self.signals)
            print(reward_signal_id)
            if current_protocol.mock_samples_file_path is not None:
                self.reward.signal = self.mock_signals_buffer[reward_signal_id]
            else:
                self.reward.signal = self.signals[reward_signal_id]  # TODO: REward for MOCK
            self.reward.set_enabled(isinstance(current_protocol, FeedbackProtocol))

        else:
            # status
            self.main.status.finish()
            # action in the end of protocols sequence
            self.current_protocol_n_samples = np.inf
            self.is_finished = True
            if self.params['bShowSubjectWindow']:
                self.subject.close()
            if self.params['bPlotSourceSpace']:
                self.source_space_window.close()
            self.terminate_eyelink()
            print("FINISHED!!")
            # plot_fb_dynamic(self.dir_name + 'experiment_data.h5', self.dir_name)
            # np.save('results/raw', self.main.raw_recorder)
            # np.save('results/signals', self.main.signals_recorder)

            # save_h5py(self.dir_name + 'raw.h5', self.main.raw_recorder)
            # save_h5py(self.dir_name + 'signals.h5', self.main.signals_recorder)

        logging.debug(
            f"NEXT PROTOCOL END TIMESTAMP: {self.timestamp_recorder[self.samples_counter]} PROTOCOL_{self.current_protocol_index}-{self.protocols_sequence[self.current_protocol_index].name}")

    def restart(self):

        self.block_score = {}
        self.block_score_left = {}
        self.block_score_right = {}

        timestamp_str = datetime.strftime(datetime.now(), '%m-%d_%H-%M-%S')
        self.dir_name = 'results/{}_{}/'.format(self.params['sExperimentName'], timestamp_str)
        os.makedirs(self.dir_name)
        logging.basicConfig(filename=os.path.join(self.dir_name, f"{timestamp_str}.log"), format='%(asctime)s> %(message)s', level=logging.DEBUG, filemode='w')
        logging.info(f"START OF SCRIPT")
        logging.info(f"results_dir: {self.dir_name}")

        wait_bar = WaitMessage(WAIT_BAR_MESSAGES['EXPERIMENT_START']).show_and_return()

        self.test_mode = False
        if self.main_timer is not None:
            self.main_timer.stop()
        if self.stream is not None:
            self.stream.disconnect()
        if self.thread is not None:
            self.thread.terminate()

        # timer
        self.main_timer = QtCore.QTimer(self.app)

        self.is_finished = False

        # current protocol index
        self.current_protocol_index = 0

        # samples counter for protocol sequence
        self.samples_counter = 0

        # run file lsl stream in a thread
        self.thread = None
        if self.params['sInletType'] == 'lsl_from_file':
            self.restart_lsl_from_file()

        # run simulated eeg lsl stream in a thread
        elif self.params['sInletType'] == 'lsl_generator':
            self.thread = stream_generator_in_a_thread(self.params['sStreamName'])

        # use FTB inlet
        aux_streams = None
        if self.params['sInletType'] == 'ftbuffer':
            hostname, port = self.params['sFTHostnamePort'].split(':')
            port = int(port)
            stream = FieldTripBufferInlet(hostname, port)

        # use LSL inlet
        else:
            stream_names = re.split(r"[,;]+", self.params['sStreamName'])
            print(f'STREAM NAME: {stream_names}')
            streams = [LSLInlet(name=name) for name in stream_names]
            stream = streams[0]
            aux_streams = streams[1:] if len(streams) > 1 else None

        # setup events stream by name
        events_stream_name = self.params['sEventsStreamName']
        events_stream = LSLInlet(events_stream_name) if events_stream_name else None
        print(f"EVENTS STREAM NAME: {events_stream_name}")

        # setup main stream
        self.stream = ChannelsSelector(stream, exclude=self.params['sReference'],
                                       subtractive_channel=self.params['sReferenceSub'],
                                       dc=self.params['bDC'], events_inlet=events_stream, aux_inlets=aux_streams,
                                       prefilter_band=self.params['sPrefilterBand'])
        self.stream.save_info(self.dir_name + 'stream_info.xml')
        save_channels_and_fs(self.dir_name + 'experiment_data.h5', self.stream.get_channels_labels(),
                             self.stream.get_frequency())

        save_xml_str_to_hdf5_dataset(self.dir_name + 'experiment_data.h5', self.stream.info_as_xml(), 'stream_info.xml')
        self.freq = self.stream.get_frequency()
        self.n_channels = self.stream.get_n_channels()
        self.n_channels_other = self.stream.get_n_channels_other()
        channels_labels = self.stream.get_channels_labels()
        montage = Montage(channels_labels)
        print(montage)
        self.seconds = 2 * self.freq
        self.raw_std = None

        # signals
        self.signals = [DerivedSignal.from_params(ind, self.freq, self.n_channels, channels_labels, signal,
                                                  avg_window=signal['dSmoothingWindow'],
                                                  enable_smoothing=signal['bSmoothingEnabled'],
                                                  stc_mode=signal['bSTCMode'])
                        for ind, signal in enumerate(self.params['vSignals']['DerivedSignal']) if
                        not signal['bBCIMode']]

        # composite signals
        self.composite_signals = [CompositeSignal([s for s in self.signals],
                                                  signal['sExpression'],
                                                  signal['sSignalName'],
                                                  ind + len(self.signals), self.freq,
                                                  avg_window=signal['dSmoothingWindow'],
                                                  enable_smoothing=signal['bSmoothingEnabled'])
                                  for ind, signal in enumerate(self.params['vSignals']['CompositeSignal'])]

        # bci signals
        self.bci_signals = [BCISignal(self.freq, channels_labels, signal['sSignalName'], ind)
                            for ind, signal in enumerate(self.params['vSignals']['DerivedSignal']) if
                            signal['bBCIMode']]

        self.signals += self.composite_signals
        self.signals += self.bci_signals
        # self.current_samples = np.zeros_like(self.signals)

        # signals outlet
        self.signals_outlet = SignalsOutlet([signal.name for signal in self.signals], fs=self.freq)

        # protocols
        self.protocols = []
        signal_names = [signal.name for signal in self.signals]

        for protocol in self.params['vProtocols']:
            # some general protocol arguments
            source_signal_id = None if protocol['fbSource'] == 'All' else signal_names.index(protocol['fbSource'])
            reward_signal_id = signal_names.index(protocol['sRewardSignal']) if protocol['sRewardSignal'] != '' else 0
            print(f"PROTOCOL: {protocol['sProtocolName']}, REWARD_SIG: {protocol['sRewardSignal']}, REWARD ID: {reward_signal_id}")
            mock_path = (protocol['sMockSignalFilePath'] if protocol['sMockSignalFilePath'] != '' else None,
                         protocol['sMockSignalFileDataset'])
            m_signal = protocol['sMSignal']
            m_signal_index = None if m_signal not in signal_names else signal_names.index(m_signal)

            # general protocol arguments dictionary
            kwargs = dict(
                source_signal_id=source_signal_id,
                name=protocol['sProtocolName'],
                duration=protocol['fDuration'],
                random_over_time=protocol['fRandomOverTime'],
                update_statistics_in_the_end=bool(protocol['bUpdateStatistics']),
                stats_type=protocol['sStatisticsType'],
                mock_samples_path=mock_path,
                show_reward=bool(protocol['bShowReward']),
                show_pc_score_after=bool(protocol['bShowPcScoreAfter']),
                reward_signal_id=reward_signal_id,
                reward_threshold=protocol['bRewardThreshold'],
                mock_reward_threshold=protocol['bMockRewardThreshold'],
                ssd_in_the_end=protocol['bSSDInTheEnd'],
                timer=self.main_timer,
                freq=self.freq,
                mock_previous=int(protocol['iMockPrevious']),
                drop_outliers=int(protocol['iDropOutliers']),
                experiment=self,
                pause_after=bool(protocol['bPauseAfter']),
                beep_after=bool(protocol['bBeepAfter']),
                reverse_mock_previous=bool(protocol['bReverseMockPrevious']),
                m_signal_index=m_signal_index,
                shuffle_mock_previous=bool(protocol['bRandomMockPrevious']),
                as_mock=bool(protocol['bMockSource']),
                auto_bci_fit=bool(protocol['bAutoBCIFit']),
                montage=montage,
                show_probe=protocol['bProbe'],
                probe_duration=protocol['iProbeDur'],
                probe_loc=protocol['sProbeLoc'],
                posner_test=protocol['bPosnerTest'],
                enable_posner=protocol['bEnablePosner'],
                eye_range=protocol['fEyeRange']
            )

            # type specific arguments
            if protocol['sFb_type'] == 'Baseline':
                self.protocols.append(
                    BaselineProtocol(
                        self.signals,
                        text=protocol['cString'] if protocol['cString'] != '' else 'Relax',
                        half_time_text=protocol['cString2'] if bool(protocol['bUseExtraMessage']) else None,
                        voiceover=protocol['bVoiceover'], **kwargs
                    ))
            elif protocol['sFb_type'] in ['Feedback', 'CircleFeedback']:
                self.protocols.append(
                    FeedbackProtocol(
                        self.signals,
                        gabor_theta=self.gabor_theta,
                        circle_border=protocol['iRandomBound'],
                        m_threshold=protocol['fMSignalThreshold'],
                        **kwargs))
            elif protocol['sFb_type'] == 'ThresholdBlink':
                self.protocols.append(
                    ThresholdBlinkFeedbackProtocol(
                        self.signals,
                        threshold=protocol['fBlinkThreshold'],
                        time_ms=protocol['fBlinkDurationMs'],
                        **kwargs))
            elif protocol['sFb_type'] == 'FixationCross':
                colour_dict = {'Black': (0, 0, 0), 'White': (255, 255, 255), 'Green': (0, 255, 0), 'Red': (255, 0, 0), 'None': (0,0,0,0),
                               'Blue': (0, 0, 255)}
                self.protocols.append(
                    FixationCrossProtocol(
                        self.signals,
                        text=protocol['cString'],
                        colour=colour_dict[protocol['tFixationCrossColour']],
                        **kwargs))
            elif protocol['sFb_type'] == 'Posner':
                  self.protocols.append(
                    PosnerCueProtocol(
                        self.signals,
                        **kwargs))
            elif protocol['sFb_type'] == 'EyeCalibration':
                self.protocols.append(
                    EyeCalibrationProtocol(
                        self.signals,
                        **kwargs))
            elif protocol['sFb_type'] == 'Video':
                self.protocols.append(
                    VideoProtocol(
                        self.signals,
                        video_path=protocol['sVideoPath'],
                        **kwargs))
            elif protocol['sFb_type'] == 'Image':
                self.protocols.append(
                    ImageProtocol(
                        self.signals,
                        image_path=protocol['sVideoPath'],
                        **kwargs))
            elif protocol['sFb_type'] == 'ParticipantInput':
                self.protocols.append(
                    ParticipantInputProtocol(
                        self.signals,
                        text=protocol['cString'] if protocol['cString'] != '' else 'Relax',
                        **kwargs))
            elif protocol['sFb_type'] == 'ParticipantChoice':
                self.protocols.append(
                    ParticipantChoiceProtocol(
                        self.signals,
                        gabor_theta= self.gabor_theta + self.rn_offset,
                        text=protocol['cString'] if protocol['cString'] != '' else 'Relax',
                        **kwargs))
            elif protocol['sFb_type'] == 'ExperimentStart':
                self.protocols.append(
                    ExperimentStartProtocol(
                        self.signals,
                        text=protocol['cString'] if protocol['cString'] != '' else 'Relax',
                        **kwargs))
            else:
                raise TypeError('Undefined protocol type \"{}\"'.format(protocol['sFb_type']))


        # protocols sequence
        names = [protocol.name for protocol in self.protocols]
        group_names = [p['sName'] for p in self.params['vPGroups']['PGroup']]
        print(group_names)
        self.protocols_sequence = []
        for name in self.params['vPSequence']:
            if name in names:
                self.protocols_sequence.append(self.protocols[names.index(name)])
            if name in group_names:
                group = self.params['vPGroups']['PGroup'][group_names.index(name)]
                subgroup = []
                if len(group['sList'].split(' ')) == 1:
                    subgroup.append([group['sList']] * int(group['sNumberList']))
                else:
                    for s_name, s_n in zip(group['sList'].split(' '), list(map(int, group['sNumberList'].split(' ')))):
                        subgroup.append([s_name] * s_n)
                if group['bShuffle']:
                    subgroup = np.concatenate(subgroup)
                    subgroup = list(subgroup[np.random.permutation(len(subgroup))])
                else:
                    subgroup = [k for k in chain(*zip_longest(*subgroup)) if k is not None]
                print(subgroup)
                for subname in subgroup:
                    self.protocols_sequence.append(self.protocols[names.index(subname)])
                    if len(group['sSplitBy']):
                        self.protocols_sequence.append(self.protocols[names.index(group['sSplitBy'])])

        # reward
        from pynfb.reward import Reward
        self.reward = Reward(self.protocols[0].reward_signal_id,
                             threshold=self.protocols[0].reward_threshold,
                             rate_of_increase=self.params['fRewardPeriodS'],
                             fs=self.freq)

        self.reward.set_enabled(isinstance(self.protocols_sequence[0], FeedbackProtocol))

        # timer
        # self.main_timer = QtCore.QTimer(self.app)
        self.main_timer.timeout.connect(self.update)
        self.main_timer.start(1000 * 1. / self.freq)

        # current protocol number of samples ('frequency' * 'protocol duration')
        self.current_protocol_n_samples = self.freq * (self.protocols_sequence[self.current_protocol_index].duration +
                                                       np.random.uniform(0, self.protocols_sequence[
                                                           self.current_protocol_index].random_over_time))

        # experiment number of samples
        max_protocol_n_samples = int(
            max([self.freq * (p.duration + p.random_over_time) for p in self.protocols_sequence]))

        # data recorders
        self.experiment_n_samples = max_protocol_n_samples
        self.samples_counter = 0
        self.raw_recorder = np.zeros((max_protocol_n_samples * 110 // 100, self.n_channels)) * np.nan
        self.timestamp_recorder = np.zeros((max_protocol_n_samples * 110 // 100)) * np.nan
        self.raw_recorder_other = np.zeros((max_protocol_n_samples * 110 // 100, self.n_channels_other)) * np.nan
        self.signals_recorder = np.zeros((max_protocol_n_samples * 110 // 100, len(self.signals))) * np.nan
        self.reward_recorder = np.zeros((max_protocol_n_samples * 110 // 100)) * np.nan # cumulative reward (int)
        self.mark_recorder = np.zeros((max_protocol_n_samples * 110 // 100)) * np.nan
        self.choice_recorder = np.zeros((max_protocol_n_samples * 110 // 100)) * np.nan
        self.answer_recorder = np.zeros((max_protocol_n_samples * 110 // 100)) * np.nan
        self.posnerstim_recorder = np.zeros((max_protocol_n_samples * 110 // 100)) * np.nan # The onset of stimlus (in ms)
        self.posnerdir_recorder = np.zeros((max_protocol_n_samples * 110 // 100)) * np.nan # The direction of posner stim
        self.response_recorder = np.zeros((max_protocol_n_samples * 110 // 100)) * np.nan # the user response (in ms)
        self.chunk_recorder = np.zeros((max_protocol_n_samples * 110 // 100)) * np.nan # the length of incoming chunks
        self.probe_recorder = np.zeros((max_protocol_n_samples * 110 // 100)) * np.nan # the onset sample of probes
        self.cue_recorder = np.zeros((max_protocol_n_samples * 110 // 100)) * np.nan # the cue direction for posner tasks

        # save init signals
        save_signals(self.dir_name + 'experiment_data.h5', self.signals,
                     group_name='protocol0')

        # save settings
        params_to_xml_file(self.params, self.dir_name + 'settings.xml')
        save_xml_str_to_hdf5_dataset(self.dir_name + 'experiment_data.h5', params_to_xml(self.params), 'settings.xml')

        # windows
        self.main = MainWindow(signals=self.signals,
                               protocols=self.protocols_sequence,
                               parent=None,
                               experiment=self,
                               current_protocol=self.protocols_sequence[self.current_protocol_index],
                               n_signals=len(self.signals),
                               max_protocol_n_samples=max_protocol_n_samples,
                               freq=self.freq,
                               n_channels=self.n_channels,
                               plot_raw_flag=self.params['bPlotRaw'],
                               plot_signals_flag=self.params['bPlotSignals'],
                               plot_source_space_flag=self.params['bPlotSourceSpace'],
                               show_subject_window=self.params['bShowSubjectWindow'],
                               channels_labels=channels_labels,
                               photo_rect=self.params['bShowPhotoRectangle'])
        self.subject = self.main.subject_window
        if self.params['bPlotSourceSpace']:
            self.source_space_window = self.main.source_space_window

        if self.params['sInletType'] == 'lsl_from_file':
            self.main.player_panel.start_clicked.connect(self.restart_lsl_from_file)


        # create real fb list
        self.real_fb_number_list = []

        wait_bar.close()

    def restart_lsl_from_file(self):
        if self.thread is not None:
            self.thread.terminate()

        file_path = self.params['sRawDataFilePath']
        reference = self.params['sReference']
        stream_name = self.params['sStreamName']

        self.thread = stream_file_in_a_thread(file_path, reference, stream_name)

    def destroy(self):
        if self.thread is not None:
            self.thread.terminate()
        self.main_timer.stop()
        del self.stream
        self.stream = None
        # del self
