import os
import sys
import uuid
import time
import yaml
import shutil
import inspect
import datetime
from time import strftime

from mock import MagicMock
from collections import ChainMap
import bluesky.plans as bp
import numpy as np

from .glbl import glbl
from .yamldict import YamlDict, YamlChainMap
from .validated_dict import ValidatedDictLike
from .beamtime import *
from .utils import _graceful_exit

def _start_beamtime(PI_last, saf_num, experimenters=[], *,
                    wavelength=None):
    """ function for start beamtime """
    # TODO - allow config file later

    if not os.path.exists(glbl.home):
        raise RuntimeError("WARNING: fundamental directory {} does not"
                           "exist. Please contact beamline staff immediately"
                           .format(glbl.home))

    dir_list = os.listdir(glbl.home)
    if len(dir_list) != 0:
        raise FileExistsError("There are more than one files/directories"
                              "under {}, have you 'run _end_beamtime()' yet?"
                              .format(glbl.home))
    elif len(dir_list) == 0:
        print("INFO: initiating requried directories for experiment")
        _make_clean_env()
        bt = Beamtime(PI_last, saf_num, experimenters,
                wavelength=wavelength)
        os.chdir(glbl.home)
        return bt


def _make_clean_env():
    '''Make a clean environment for a new user
    '''
    out = []
    for d in glbl.allfolders:
        os.makedirs(d, exist_ok=True)
        out.append(d)
    return out


def start_xpdacq():
    """ function to reload beamtime """
    try:
        bt_list = [f for f in os.listdir(glbl.yaml_dir) if
                   f.startswith('bt') and
                   os.path.isfile(os.path.join(glbl.yaml_dir, f))]
    except FileNotFoundError:
        return _no_beamtime()

    if len(bt_list) == 1:
        bt_f = bt_list[-1]
        bt = load_beamtime()
        return bt

    elif len(bt_list) > 1:
        print("WARNING: There are more than one beamtime objects:"
              "{}".format(bt_list))
        print("Please contact beamline staff immediately")

    else:
       return _no_beamtime()


def _no_beamtime():
    print("INFO: No beamtime object has been found")
    print("INFO: Please run 'bt=_start_beamtime(<PI_last>, <saf_num>,"
          "<experimenter_list>, wavelength=<wavelength_num>)'"
          "to initiate beamtime")


def load_beamtime(directory=None):
    """
    Load a Beamtime and associated objects.

    Expected directory structure:

    <glbl.yaml_dir>/
      beamtime.yml
      samples/
      scanplans/
      experiments/
    """
    if directory is None:
        directory = glbl.yaml_dir # leave room for future multi-beamtime
    known_uids = {}
    beamtime_fn = os.path.join(directory, 'bt_bt.yml')
    experiment_fns = os.listdir(os.path.join(directory, 'experiments'))
    sample_fns = os.listdir(os.path.join(directory, 'samples'))
    scanplan_fns = os.listdir(os.path.join(directory, 'scanplans'))

    with open(beamtime_fn, 'r') as f:
        bt = load_yaml(f, known_uids)

    for fn in experiment_fns:
        with open(os.path.join(directory, 'experiments', fn), 'r') as f:
            load_yaml(f, known_uids)

    for fn in scanplan_fns:
        with open(os.path.join(directory, 'scanplans', fn), 'r') as f:
            load_yaml(f, known_uids)

    # Samples are not part of the heirarchy, but all beamtimes know about
    # all Samples.
    for fn in sample_fns:
        with open(os.path.join(directory, 'samples', fn), 'r') as f:
            data = yaml.load(f)
            bt.samples.append(data)

    return bt


def load_yaml(f, known_uids=None):
    """
    Recreate a ScanPlan, Experiment, or Beamtime object from a YAML file.

    If its linked objects have already been created, re-link to them.
    If they have not yet been created, create them now.
    """
    if known_uids is None:
        known_uids = {}
    data = yaml.load(f)
    # If f is a file handle, 'rewind' it so we can read it again.
    if not isinstance(f, str):
        f.seek(0)
    if isinstance(data, dict) and 'beamtime_uid' in data:
        obj = Beamtime.from_yaml(f)
        known_uids[obj['beamtime_uid']] = obj
        return obj
    elif isinstance(data, list) and len(data) == 2:
        beamtime = known_uids.get(data[1]['beamtime_uid'])
        obj = Experiment.from_yaml(f, beamtime=beamtime)
        known_uids[obj['experiment_uid']] = obj
    elif isinstance(data, list) and len(data) == 3:
        experiment = known_uids.get(data[1]['experiment_uid'])
        beamtime = known_uids.get(data[2]['beamtime_uid'])
        obj = ScanPlan.from_yaml(f, experiment=experiment, beamtime=beamtime)
        known_uids[obj['scanplan_uid']] = obj
    else:
        raise ValueError("File does not match a recognized specification.")
    return obj


def _end_beamtime(base_dir=None,archive_dir=None,bto=None, usr_confirm = 'y'):
    """ funciton to end a beamtime.

    It check if directory structure is correct and flush directories
    """
    _required_info = ['pi_name', 'saf_num', 'beamtime_uid']
    if archive_dir is None:
        archive_dir = glbl.archive_dir
    if base_dir is None:
        base_dir = glbl.base
    os.makedirs(glbl.home, exist_ok = True)
    # check env
    files = os.listdir(glbl.home)
    if len(files)==0:
        raise FileNotFoundError("It appears that end_beamtime may have been"
                                "run. If so, do not run again but proceed to"
                                "bt = _start_beamtime(pi_last, saf_num)")
    # laod bt yaml
    if not bto:
        bto = _load_bt(glbl.yaml_dir)
    # load bt info
    archive_name = _load_bt_info(bto, _required_info)
    # archive file
    archive_full_name = _tar_user_data(archive_name)
    # confirm archive
    _confirm_archive(archive_full_name)
    # flush
    _delete_home_dir_tree()


def _clean_info(obj):
    """ stringtify and replace space"""
    return str(obj).strip().replace(' ', '')


def _load_bt_info(bt_obj, required_fields):
    # grab information
    bt_info_list = []
    for el in required_fields:
        bt_info = bt_obj.get(el)
        if bt_info is None:
            print("WARNING: required beamtime information {} doesn't exit."
                  "User might have edited it during experiment."
                  "Please contact user for further inforamtion".format(el))
            sys.exit()
        bt_info_list.append(_clean_info(bt_info))
    bt_info_list.append(strftime('%Y-%m-%d-%H%M'))
    archive_name ='_'.join(bt_info_list)
    return archive_name


def _tar_user_data(archive_name, root_dir = None, archive_format ='tar'):
    """ Create a remote tarball of all user folders under xpdUser directory
    """
    archive_full_name = os.path.join(glbl.archive_dir, archive_name)
    if root_dir is None:
        root_dir = glbl.base
    cur_path = os.getcwd()
    try:
        os.chdir(glbl.base)
        print("INFO: Archiving your data now. That may take several"
              "minutes. please be patient :)" )
        tar_return = shutil.make_archive(archive_full_name,
                                         archive_format, root_dir=glbl.base,
                                         base_dir='xpdUser', verbose=1,
                                         dry_run=False)
    finally:
        os.chdir(cur_path)
    return archive_full_name


def _load_bt(bt_yaml_path):
    btoname = os.path.join(glbl.yaml_dir,'bt_bt.yml')
    if not os.path.isfile(btoname):
        sys.exit(_graceful_exit("{} does not exist in {}. User might have"
                                "deleted it accidentally.Please create it"
                                "based on user information or contect user"
                                .format(os.path.basename(btoname),
                                        glbl.yaml_dir)))
    with open(btoname, 'r') as fi:
        bto = yaml.load(fi)
    return bto


def  _get_user_confirmation():
    conf = input("Please confirm data are backed up. Are you ready to continue"
                 "with xpdUser directory contents deletion (y,[n])?: ")
    return conf


def _any_input_method(inp_func):
    return inp_func()


def _confirm_archive(archive_f_name):
    print("tarball archived to {}".format(archive_f_name))
    conf = _any_input_method(_get_user_confirmation)
    if conf in ('y','Y'):
        return
    else:
        sys.exit(_graceful_exit("xpdUser directory delete operation cancelled."
                                "at Users request"))

def _delete_home_dir_tree():
    os.chdir(glbl.base) # move out from xpdUser before deletion
    shutil.rmtree(glbl.home)
    os.makedirs(glbl.home, exist_ok=True)
    os.chdir(glbl.home)  # now move back into xpdUser
    return


""" hodding place
# advanced version, allowed multiple beamtime. but not used for now
def _start_xpdacq():
    dirs = [d for d in os.listdir(glbl.yaml_dir) if os.path.isdir(d)]
    # create sample dir if it doesn't exist yet
    if 'samples' not in dirs:
        sample_dir = os.path.join(glbl.xpdconfig, 'samples')
        os.makedirs(sample_dir, exist_ok=True)
    else:
        dirs.remove('samples')
    # now we have all dirs that are not samples;
    # only PI_name dirs left

    if len(dirs) == 1:
        load_dirs = dirs[-1]
        bt = load_beamtime(load_dirs)

    elif len(dirs) > 1:
        print("INFO: There are more than one PI_name dirs:"
              "{}".format(dirs))
        print("Please choose the one you want to use and run:"
              "bt = load_beamtime(<path to the PI name dir>)")

    else:
        print("INFO: No PI_name has been found")

"""