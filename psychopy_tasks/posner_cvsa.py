from psychopy.gui import DlgFromDict
from psychopy.visual import Window, TextStim, circle
from psychopy.core import Clock, quit
from psychopy.event import Mouse
from psychopy.hardware.keyboard import Keyboard
from psychopy.monitors import Monitor
from psychopy.data import TrialHandler, getDateStr, ExperimentHandler
from psychopy.constants import (NOT_STARTED, STARTED, PLAYING, PAUSED,
                                STOPPED, FINISHED, PRESSED, RELEASED, FOREVER)
import psychopy
import os
import typing
import random
from dataclasses import dataclass

from psychopy.visual.shape import ShapeStim


@dataclass
class PosnerComponent:
    component: typing.Any = object()
    start_time: float = 0.0
    duration: float = 1.0
    blocking: bool = False


class PosnerTask:
    def __init__(self):
        self.trial_reps = [4, 2, 2, 2]
        self.frameTolerance = 0.001  # how close to onset before 'same' frame
        self.expName = 'posner_task'
        self.exp_info = {'participant': "99", 'session': 'x'}
        self.thisExp = None
        # init the monitor
        self.mon = Monitor('eprime',
                           width=40,
                           distance=60,
                           autoLog=True)
        self.mon.setSizePix((1280, 1024))
        self.win = Window(fullscr=False, monitor=self.mon)
        self.start_components = []
        self.trial_components = []
        self.continue_components = []
        self.end_components = []

        # init the global keyboard
        self.kb = Keyboard()

        # Initialize clocks
        self.global_clock = Clock()
        self.trial_clock = Clock()

        # init component start times
        self.trial_duration = 6.5
        self.fc_duration = 1.0
        self.cue_duration = self.trial_duration - self.fc_duration
        self.stim_duration = 0.1
        self.probe_start_time = random.uniform(self.fc_duration + 3, self.trial_duration - self.stim_duration - 1)

    def update_exp_info(self):
        self.exp_info['date'] = getDateStr()  # add a simple timestamp
        self.exp_info['expName'] = self.expName
        self.exp_info['psychopyVersion'] = psychopy.__version__

    def set_experiment(self):
        _thisDir = os.path.dirname(os.path.abspath(__file__))
        os.chdir(_thisDir)
        filename = _thisDir + os.sep + u'data/%s_%s_%s' % (
            self.exp_info['participant'], self.expName, self.exp_info['date'])
        # An ExperimentHandler isn't essential but helps with data saving
        self.thisExp = ExperimentHandler(name=self.expName, version='',
                                         extraInfo=self.exp_info, runtimeInfo=None,
                                         originPath='C:\\Users\\2354158T\\Documents\\GitHub\\nfb\\psychopy\\posner_eyelink.py',
                                         savePickle=True, saveWideText=True,
                                         dataFileName=filename)

    def calculate_cue_side(self):
        """
        Calculate the direction the cue will be
        side: direction of the cue (1 = left, 2 = right, 3 = centre
        cue probability is equal for left, right, and centre
        """
        self.probe_start_time = random.uniform(self.fc_duration + 3, self.trial_duration - self.stim_duration - 1)
        cue_dir = random.choice([1, 2, 3])  # 1=l, 2=r, 3=n

        self.left_cue.component.opacity = 0.0
        self.right_cue.component.opacity = 0.0
        self.centre_cue1.component.opacity = 0.0
        self.centre_cue2.component.opacity = 0.0
        if cue_dir == 1:
            self.left_cue.component.opacity = 1.0
        elif cue_dir == 2:
            self.right_cue.component.opacity = 1.0
        elif cue_dir == 3:
            self.centre_cue1.component.opacity = 1.0
            self.centre_cue2.component.opacity = 1.0
        return cue_dir

    def calculate_stim_validity(self, cue_dir, valid_cue_weight=70):
        """
        Calculate if a stimulation is valid or not
        cue_dir: direction of cue
        valid_cue_weight: chance the stim is valid
        """
        neutral_side = random.choice([1, 2]) # side to display stim in case of neutral/centre cue
        valid_cue = random.choices([True, False], weights=(valid_cue_weight, 100 - valid_cue_weight))[0]
        if valid_cue:
            # valid cue
            if cue_dir == 1:
                stim_pos = (-5, -1)
            elif cue_dir == 2:
                stim_pos = (5, -1)
            elif cue_dir == 3:
                # 50% chance left or right
                if neutral_side == 1:
                    stim_pos = (-5, -1)
                elif neutral_side == 2:
                    stim_pos = (5, -1)
        else:
            # invalid cue
            if cue_dir == 1:
                stim_pos = (5, -1)
            elif cue_dir == 2:
                stim_pos = (-5, -1)
            elif cue_dir == 3:
                # 50% chance left or right
                if neutral_side == 1:
                    stim_pos = (-5, -1)
                elif neutral_side == 2:
                    stim_pos = (5, -1)
        self.stim.component.setPos(stim_pos)
        return valid_cue

    def init_start_components(self):
        self.start_text = PosnerComponent(
            TextStim(self.win, text="""Welcome to this experiment!
                                                 Press SPACE to start"""),
            duration=0.0,
            blocking=True)
        self.start_components = [self.start_text]

    def init_continue_components(self):
        self.continue_text = PosnerComponent(
            TextStim(self.win, text="""you've finished X blocks
                                                 Press SPACE to continue"""),
            duration=0.0,
            blocking=True)
        self.continue_components = [self.continue_text]

    def init_end_components(self):
        self.end_text = PosnerComponent(
            TextStim(self.win, text="""you've finished!"""),
            duration=0.0,
            blocking=True)
        self.end_components = [self.end_text]

    def init_trial_components(self):
        self.fc = PosnerComponent(
            circle.Circle(
                win=self.win,
                name='fc',
                units="deg",
                radius=0.1,
                fillColor='black',
                lineColor='black'
            ),
            duration=self.fc_duration,
            start_time=0.0)

        self.left_probe = PosnerComponent(
            circle.Circle(
                win=self.win,
                name='left_probe',
                units="deg",
                radius=3.5/2,
                fillColor='blue',
                lineColor='white',
                lineWidth=8,
                edges=128,
                pos=[-5, -1],
            ),
            duration=self.trial_duration,
            start_time=0.0)

        self.right_probe = PosnerComponent(
            circle.Circle(
                win=self.win,
                name='right_probe',
                units="deg",
                radius=3.5/2,
                fillColor='blue',
                lineColor='white',
                lineWidth=8,
                edges=256,
                pos=[5, -1],
            ),
            duration=self.trial_duration,
            start_time=0.0)

        self.stim = PosnerComponent(
            circle.Circle(
                win=self.win,
                name='stim',
                units="deg",
                radius=0.5,
                fillColor='white',
                lineColor='white',
                edges=256,
                pos=[-5, -1],
            ),
            duration=self.stim_duration,
            start_time=self.probe_start_time)

        self.left_cue = PosnerComponent(
            ShapeStim(
            win=self.win, name='left_cue', units='deg',
            size=(0.75, 0.75), vertices='triangle',
            ori=-90.0, pos=(0, 0), anchor='center',
            lineWidth=1.0, colorSpace='rgb', lineColor='white', fillColor='white',
            opacity=1.0, interpolate=True),
            duration=self.cue_duration,
            start_time=self.fc_duration)

        self.right_cue = PosnerComponent(
            ShapeStim(
            win=self.win, name='right_cue', units='deg',
            size=(0.75, 0.75), vertices='triangle',
            ori=90.0, pos=(0, 0), anchor='center',
            lineWidth=1.0, colorSpace='rgb', lineColor='white', fillColor='white',
            opacity=0.0, interpolate=True),
            duration=self.cue_duration,
            start_time=self.fc_duration)

        self.centre_cue1 = PosnerComponent(
            ShapeStim(
            win=self.win, name='centre_cue1', units='deg',
            size=(0.75, 0.75), vertices='triangle',
            ori=90.0, pos=(0.375, 0), anchor='center',
            lineWidth=1.0, colorSpace='rgb', lineColor='white', fillColor='white',
            opacity=0.0, interpolate=True),
            duration=self.cue_duration,
            start_time=self.fc_duration)

        self.centre_cue2 = PosnerComponent(
            ShapeStim(
            win=self.win, name='centre_cue2', units='deg',
            size=(0.75, 0.75), vertices='triangle',
            ori=-90.0, pos=(-0.375, 0), anchor='center',
            lineWidth=1.0, colorSpace='rgb', lineColor='white', fillColor='white',
            opacity=0.0, interpolate=True),
            duration=self.cue_duration,
            start_time=self.fc_duration)

        self.key_resp = Keyboard()

        self.trial_components = [self.fc,
                                 self.left_probe,
                                 self.right_probe,
                                 self.left_cue,
                                 self.right_cue,
                                 self.centre_cue1,
                                 self.centre_cue2,
                                 self.stim,
                                 self.key_resp]

    def handle_component(self, pcomp, tThisFlip, tThisFlipGlobal, t, duration=1):
        # Handle both the probes
        if pcomp.component.status == NOT_STARTED and tThisFlip >= pcomp.start_time - self.frameTolerance:
            # keep track of start time/frame for later
            pcomp.component.tStart = t  # local t and not account for scr refresh
            pcomp.component.tStartRefresh = tThisFlipGlobal  # on global time
            self.win.timeOnFlip(pcomp.component, 'tStartRefresh')  # time at next scr refresh
            # add timestamp to datafile
            self.thisExp.timestampOnFlip(self.win, f'{pcomp.component.name}.started')
            pcomp.component.setAutoDraw(True)
        if pcomp.component.status == STARTED:
            # is it time to stop? (based on global clock, using actual start)
            if tThisFlipGlobal > pcomp.component.tStartRefresh + duration - self.frameTolerance:
                if not pcomp.blocking:
                    pcomp.component.tStop = t  # not accounting for scr refresh
                    # add timestamp to datafile
                    self.thisExp.timestampOnFlip(self.win, f'{pcomp.component.name}.stopped')
                    pcomp.component.setAutoDraw(False)
                    pcomp.component.status = FINISHED

    def run_block(self, component_list, trial_reps, block_name='block'):
        trials = TrialHandler(nReps=trial_reps, method='sequential',
                              extraInfo=self.exp_info, originPath=-1,
                              trialList=[None],
                              seed=None, name='trials')
        self.thisExp.addLoop(trials)  # add the loop to the experiment
        thisTrial = trials.trialList[0]  # so we can initialise stimuli with some values

        # Do the trials
        for trial_index, thisTrial in enumerate(trials):
            print(f'STARTING TRIAL: {trials.thisN} OF BLOCK: {block_name}')

            # Calculate the side of the cue and stim validity
            cue_dir = self.calculate_cue_side()
            valid_cue = self.calculate_stim_validity(cue_dir=cue_dir)

            currentLoop = trials
            # abbreviate parameter names if possible (e.g. rgb = thisTrial.rgb)
            if thisTrial != None:
                for paramName in thisTrial:
                    exec('{} = thisTrial[paramName]'.format(paramName))

            continueRoutine = True

            # Reset the trial clock
            self.trial_clock.reset()

            for thisComponent in component_list:
                thisComponent.component.tStart = None
                thisComponent.component.tStop = None
                thisComponent.component.tStartRefresh = None
                thisComponent.component.tStopRefresh = None
                if hasattr(thisComponent.component, 'status'):
                    thisComponent.component.status = NOT_STARTED

            while continueRoutine:
                # get current time
                t = self.trial_clock.getTime()
                tThisFlip = self.win.getFutureFlipTime(clock=self.trial_clock)
                tThisFlipGlobal = self.win.getFutureFlipTime(clock=None)

                # Handle both the probes
                for thisComponent in component_list:
                    self.handle_component(thisComponent, tThisFlip, tThisFlipGlobal, t,
                                          duration=thisComponent.duration)
                    # check for blocking end (typically the Space key)
                    if self.kb.getKeys(keyList=["space"]):
                        thisComponent.blocking = False

                # check for quit (typically the Esc key)
                if self.kb.getKeys(keyList=["escape"]):
                    quit()

                continueRoutine = False  # will revert to True if at least one component still running
                for thisComponent in component_list:
                    if hasattr(thisComponent.component, "status") and thisComponent.component.status != FINISHED:
                        continueRoutine = True
                        break  # at least one component has not yet finished

                # refresh the screen
                if continueRoutine:  # don't flip if this routine is over or we'll get a blank screen
                    self.win.flip()

            # --- Ending Routine "cue" ---
            for thisComponent in component_list:
                if hasattr(thisComponent.component, "setAutoDraw"):
                    thisComponent.component.setAutoDraw(False)

            # Save extra data
            self.thisExp.addData('block_name', block_name)
            self.thisExp.addData('cue_dir', cue_dir)
            self.thisExp.addData('valid_cue', valid_cue)

            self.thisExp.nextEntry()

    def show_start_dialog(self):
        dlg = DlgFromDict(self.exp_info)
        # If pressed Cancel, abort!
        if not dlg.OK:
            quit()
        else:
            # Quit when either the participant nr or age is not filled in
            if not self.exp_info['participant'] or not self.exp_info['session']:
                quit()

            else:  # let's star the experiment!
                print(f"Started experiment for participant {self.exp_info['participant']} "
                      f"in session {self.exp_info['session']}.")

    def end_experiment(self):
        # Finish experiment by closing window and quitting
        self.win.close()
        quit()

    def run_experiment(self):
        self.show_start_dialog()
        self.update_exp_info()
        self.set_experiment()
        self.init_start_components()
        self.init_continue_components()
        self.init_end_components()
        self.init_trial_components()
        self.run_block(self.start_components, 1, block_name='start')
        self.run_block(self.trial_components, self.trial_reps[0], block_name='trials1')
        self.run_block(self.continue_components, 1, block_name='continue')
        self.run_block(self.trial_components, self.trial_reps[1], block_name='trials2')
        self.run_block(self.continue_components, 1, block_name='continue')
        self.run_block(self.trial_components, self.trial_reps[2], block_name='trials3')
        self.run_block(self.continue_components, 1, block_name='continue')
        self.run_block(self.trial_components, self.trial_reps[3], block_name='trials4')
        self.run_block(self.end_components, 1, block_name='end')


if __name__ == '__main__':
    pt = PosnerTask()
    pt.run_experiment()
