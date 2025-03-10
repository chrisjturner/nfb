import os

import mne
import numpy as np
import pylab as plt
from mne.datasets import fetch_fsaverage
from mne.minimum_norm.inverse import _assemble_kernel

def _get_label_flip(labels, label_vertidx, src):
    """Get sign-flip for labels."""
    # do the import here to avoid circular dependency
    from mne.label import label_sign_flip
    # get the sign-flip vector for every label
    label_flip = list()
    for label, vertidx in zip(labels, label_vertidx):
        if label.hemi == 'both':
            raise ValueError('BiHemiLabel not supported when using sign-flip')
        if vertidx is not None:
            flip = label_sign_flip(label, src)[:, None]
        else:
            flip = None
        label_flip.append(flip)

    return label_flip

# get flip
def get_flip(label, vertno, inv):
    nvert = [len(vn) for vn in vertno]
    if label.hemi == 'both':
        sub_labels = [label.lh, label.rh]
    else:
        sub_labels = [label]
    this_vertidx = list()
    for slabel in sub_labels:
        if slabel.hemi == 'lh':
            this_vertno = np.intersect1d(vertno[0], slabel.vertices)
            vertidx = np.searchsorted(vertno[0], this_vertno)
        elif slabel.hemi == 'rh':
            this_vertno = np.intersect1d(vertno[1], slabel.vertices)
            vertidx = nvert[0] + np.searchsorted(vertno[1], this_vertno)
        else:
            raise ValueError('label %s has invalid hemi' % label.name)
        this_vertidx.append(vertidx)
    vertidx = np.concatenate(this_vertidx)
    label_flip = _get_label_flip([label], [vertidx], inv['src'][:2])
    label_flip = np.array(label_flip).flatten()
    return label_flip




def get_filter(K, vertno, inv, roi_label, noise_norm):
    label_flip = get_flip(roi_label, vertno, inv)
    w = np.dot(noise_norm.flatten() * label_flip / len(label_flip), K)
    return w

# setup roi
def get_roi_by_name(name):
    if type(name) == list:
        roi_label = mne.read_labels_from_annot('fsaverage',regexp=name[0], parc='aparc')[0]
        del name[0]
        for elem in name:
            roi_label = roi_label + mne.read_labels_from_annot('fsaverage',regexp=elem, parc='aparc')[0]
    else:
        labels = mne.read_labels_from_annot('fsaverage', parc='aparc')
        #print([label.name for label in labels])
        roi_label = labels[[label.name for label in labels].index(name)]
    return roi_label


def get_fwd_solution():
    import os
    path = os.path.dirname(os.path.realpath(__file__))
    mne.datasets.fetch_fsaverage(path)
    mne.utils.set_config("SUBJECTS_DIR", path, set_env=True)
    file_path = os.path.join(path, 'fsaverage-fwd-1005-2.fif')
    if not os.path.isfile(file_path):
        import urllib.request
        import zipfile
        print('fsaverage-fwd-1005-2.fif not found\nPlease wait, download is in progress')
        url = r'https://github.com/nikolaims/nfb_lab_files/raw/master/fsaverage-fwd-1005-2.zip'
        zipfile_path = os.path.join(path, 'fsaverage-fwd-1005-2.zip')
        urllib.request.urlretrieve(url, zipfile_path)
        print('Downloaded')
        with zipfile.ZipFile(zipfile_path, 'r') as f:
            f.extractall(path)
        print('Extracted')
    fwd = mne.read_forward_solution(file_path)
    fwd = mne.convert_forward_solution(fwd, surf_ori=True)
    return fwd


def get_fsaverage_fwd(info):
    """
    Gets the forward solution for the fsaverage head model
    """
    # TODO: save the forward solution, if it doesn't exist then calculate it (this is to speed it up)
    fs_dir = fetch_fsaverage(verbose=True)
    # --I think this 'trans' is like the COORDS2TRANSFORMATIONMATRIX
    trans = 'fsaverage'  # MNE has a built-in fsaverage transformation
    src = os.path.join(fs_dir, 'bem', 'fsaverage-ico-5-src.fif')
    bem = os.path.join(fs_dir, 'bem', 'fsaverage-5120-5120-5120-bem-sol.fif')
    print(info['ch_names'])
    fwd = mne.make_forward_solution(info, trans=trans, src=src,
                                    bem=bem, eeg=True, mindist=5.0, n_jobs=1)
    # The following is needed if reading forward solutions from disk (see note here: https://mne.tools/stable/generated/mne.write_forward_solution.html)
    # fwd = mne.convert_forward_solution(fwd, surf_ori=True)
    return fwd

def get_roi_filter(label_name, fs, channels, show=False, method='sLORETA', lambda2=1):
    standard_montage = mne.channels.make_standard_montage(kind='standard_1020') # TODO: make this setable (and make sure it is the right one)
    standard_montage_names = [name.upper() for name in standard_montage.ch_names]
    for j, channel in enumerate(channels):
        try:
            channels[j] = standard_montage.ch_names[standard_montage_names.index(channel.upper())]
        except ValueError as e:
            print(f"ERROR ENCOUNTERED: {e}")
    info = mne.create_info(ch_names=channels, sfreq=fs, ch_types=['eeg' for ch in channels])
    # drop the ECG and EOG channels #TODO: make this work for other amplifiers /caps other than brainVision (with ECG and EOG)
    keep_chs = [ elem for elem in info.ch_names if elem not in ['ECG', 'EOG', 'MKIDX']]
    info.pick_channels(keep_chs)
    info.set_montage(standard_montage, on_missing='ignore')
    print(f"2: {info.get('dig')}")
    noise_cov = mne.make_ad_hoc_cov(info, verbose=None)
    # fwd = get_fwd_solution()
    loc = info.get('chs')[0]['loc']
    print(f"ss: {np.isfinite(loc[:3]).all()}")
    fwd = get_fsaverage_fwd(info)
    inv = mne.minimum_norm.make_inverse_operator(info, fwd, noise_cov, fixed=True)
    inv = mne.minimum_norm.prepare_inverse_operator(inv, nave=1, lambda2=lambda2, method=method) # TODO: find out exactly what this does and if it is needed (not in the examples on MNE website)
    roi_label = get_roi_by_name(label_name)
    print(f"ROI: {roi_label}")
    K, noise_norm, vertno, source_nn = _assemble_kernel(inv, label=roi_label, method=method, pick_ori=None) # TODO: make sure this is really doing what you want it to
    w = get_filter(K, vertno, inv, roi_label, noise_norm)
    if show:
        mne.viz.plot_topomap(w, info)
    common_ref_proj = np.eye(len(w)) - np.ones((len(w), len(w)))/len(w) # TODO: this common ref projection - is it needed?
    w = common_ref_proj.dot(w)
    w /= np.linalg.norm(w)
    return w

def get_stc_params(label_name, channels, fs, method='sLORETA', lambda2=1):
    standard_montage = mne.channels.make_standard_montage(
        kind='standard_1020')  # TODO: make this setable (and make sure it is the right one)
    standard_montage_names = [name.upper() for name in standard_montage.ch_names]
    for j, channel in enumerate(channels):
        try:
            channels[j] = standard_montage.ch_names[standard_montage_names.index(channel.upper())]
        except ValueError as e:
            print(f"ERROR ENCOUNTERED: {e}")
    info = mne.create_info(ch_names=channels, sfreq=fs, ch_types=['eeg' for ch in channels])
    # drop the ECG and EOG channels #TODO: make this work for other amplifiers /caps other than brainVision (with ECG and EOG)
    keep_chs = [elem for elem in info.ch_names if elem not in ['ECG', 'EOG', 'MKIDX']]
    info.pick_channels(keep_chs)
    info.set_montage(standard_montage, on_missing='ignore')
    print(f"2: {info.get('dig')}")
    noise_cov = mne.make_ad_hoc_cov(info, verbose=None)
    # fwd = get_fwd_solution()
    loc = info.get('chs')[0]['loc']
    print(f"ss: {np.isfinite(loc[:3]).all()}")
    fwd = get_fsaverage_fwd(info)
    inv = mne.minimum_norm.make_inverse_operator(info, fwd, noise_cov, fixed=True)
    inv = mne.minimum_norm.prepare_inverse_operator(inv, nave=1, lambda2=lambda2,
                                                    method=method)  # TODO: find out exactly what this does and if it is needed (not in the examples on MNE website)
    roi_label = get_roi_by_name(label_name)
    return inv, info, roi_label

def get_kernel_results(label_name, fs, channels, show=False, method='sLORETA', lambda2=1):
    standard_montage = mne.channels.make_standard_montage(
        kind='standard_1020')  # TODO: make this setable (and make sure it is the right one)
    standard_montage_names = [name.upper() for name in standard_montage.ch_names]
    for j, channel in enumerate(channels):
        try:
            channels[j] = standard_montage.ch_names[standard_montage_names.index(channel.upper())]
        except ValueError as e:
            print(f"ERROR ENCOUNTERED: {e}")
    info = mne.create_info(ch_names=channels, sfreq=fs, ch_types=['eeg' for ch in channels])
    # drop the ECG and EOG channels #TODO: make this work for other amplifiers /caps other than brainVision (with ECG and EOG)
    keep_chs = [elem for elem in info.ch_names if elem not in ['ECG', 'EOG', 'MKIDX']]
    info.pick_channels(keep_chs)
    info.set_montage(standard_montage, on_missing='ignore')
    print(f"2: {info.get('dig')}")
    noise_cov = mne.make_ad_hoc_cov(info, verbose=None)
    # fwd = get_fwd_solution()
    loc = info.get('chs')[0]['loc']
    print(f"ss: {np.isfinite(loc[:3]).all()}")
    fwd = get_fsaverage_fwd(info)
    inv = mne.minimum_norm.make_inverse_operator(info, fwd, noise_cov, fixed=True)
    inv = mne.minimum_norm.prepare_inverse_operator(inv, nave=1, lambda2=lambda2,
                                                    method=method)  # TODO: find out exactly what this does and if it is needed (not in the examples on MNE website)
    roi_label = get_roi_by_name(label_name)
    print(f"ROI: {roi_label}")
    K, noise_norm, vertno, source_nn = _assemble_kernel(inv, label=roi_label, method=method,
                                                        pick_ori=None)  # TODO: make sure this is really doing what you want it to
    return K, noise_norm, vertno, source_nn, inv, info


if __name__ == '__main__':
    from pynfb.protocols.ssd.topomap_selector_ica import ICADialog
    def get_some_data(real=False):
        if not real:
            channels = ['Fp1', 'Fp2', 'F7', 'F3', 'Fz', 'F4', 'F8', 'Ft9', 'Fc5', 'Fc1', 'Fc2', 'Fc6', 'Ft10', 'T7',
                        'C3', 'Cz',
                        'C4', 'T8', 'Tp9', 'Cp5', 'Cp1', 'Cp2', 'Cp6', 'Tp10', 'P7', 'P3', 'Pz', 'P4', 'P8', 'O1', 'Oz',
                        'O2']
            data = np.random.normal(loc=0, scale=0.00001, size=(5000, len(channels))).T
            fs = 500
        else:
            import h5py
            from pynfb.postprocessing.utils import get_info
            with h5py.File(r'D:\mu_ica\mu_ica\mu_ica_S1_D3_04-21_18-16-03\experiment_data.h5') as f:
                fs, channels, p_names = get_info(f, [])
                data = f['protocol{}/raw_data'.format(p_names.index('Baseline') + 1)][:].T
            from PyQt5.QtWidgets import QApplication
            a = QApplication([])
            rej, spatial, top = ICADialog.get_rejection(data.T, channels, fs, mode='ica', states=None)[:3]
            data = rej.apply(data.T).T
        return data, fs, channels

    # get data
    data, fs, channels = get_some_data(real=False)
    label_name = 'posteriorcingulate-rh'
    w = get_roi_filter(label_name, fs, channels, show=True)
    plt.figure()
    plt.plot(np.dot(w, data), 'k')
    plt.show()
