#!/usr/bin/env python
##############################################################################
#
# xpdacq            by Billinge Group
#                   Simon J. L. Billinge sb2896@columbia.edu
#                   (c) 2016 trustees of Columbia University in the City of
#                        New York.
#                   All rights reserved
#
# File coded by:    Timothy Liu
#
# See AUTHORS.txt for a list of people who contributed.
# See LICENSE.txt for license information.
#
##############################################################################
import os
import sys
import yaml
import shutil
import tarfile as tar
import uuid
import warnings
from time import strftime
from shutil import ReadError
from IPython import get_ipython


import pandas as pd

from .glbl import glbl
from .beamtime import Beamtime, Sample, ScanPlan
from .tools import validate_dict_key

def _check_obj(obj_name, error_msg=None):
    """ function to check if an object exists in current namespace

    Parameter
    ---------
    obj_name : str
        object name in string format
    error_msg : str
        error msg when target object can't be found in current
        namespace
    """
    if error_msg is None:
        error_msg = "Required object {} doesn't exist in"\
                    "current namespace".format(obj_name)
    ips = get_ipython()
    if not ips.ns_table['user_global'].get(obj_name, None):
        raise NameError(error_msg)
    return

def _timestampstr(timestamp):
    """ convert timestamp to strftime formate """
    timestring = datetime.datetime.fromtimestamp(float(timestamp)).strftime(
        '%Y%m%d-%H%M%S')
    return timestring


def _graceful_exit(error_message):
    try:
        raise RuntimeError(error_message)
        return 0
    except Exception as err:
        sys.stderr.write('WHOOPS: {}'.format(str(err)))
        return 1


def composition_analysis(compstring):
    """Pulls out elements and their ratios from the config file.

    compstring   -- chemical composition of the sample, e.g.,
                    "NaCl", "H2SO4", "La0.5 Ca0.5 Mn O3".  Blank
                    characters are ignored, unit counts can be omitted.
                    It is critical to use proper upper-lower case for atom
                    symbols as this is used to delimit them in the formula.

    Returns a list of atom symbols and a corresponding list of their counts.
    """
    import re
    # remove all blanks
    compbare = re.sub('\s', '', compstring)
    # reusable error message
    # make sure there is at least one uppercase character in the compstring
    upcasechars = any(str.isupper(c) for c in compbare)
    if not upcasechars and compbare:
        emsg = 'invalid chemical composition "%s"' % compstring
        raise ValueError(emsg)
    # split at every upper-case letter, possibly followed by a lower case
    # one and charge specification
    namefracs = re.split('([A-Z][a-z]?(?:[1-8]?[+-])?)', compbare)[1:]
    names = namefracs[0::2]
    # use unit count when empty, convert to float otherwise
    getfraction = lambda s: (s == '' and 1.0 or float(s))
    fractions = [getfraction(w) for w in namefracs[1::2]]
    return names, fractions


def _RE_state_wrapper(RE_obj):
    """ a wrapper to check state of bluesky runengine object after pausing

        it provides control to stop/abort/resume runengine under current package structure
    """
    usr_input = input('')
    # while loop gives chance to iteratively confirm user's input
    while RE_obj.state == 'paused':
        if usr_input in 'resume()':
            RE_obj.resume()
        elif usr_input in 'abort()':
            abort_all = input(
                '''current scan will be aborted. Do you want to abort all successive scans (if you are running a script)? y/[n]  ''')
            while True:
                if abort_all in ('y', 'yes'):
                    sys.exit(_graceful_exit(
                        '''INFO: All successive scans are aborted'''))
                elif abort_all in ('n', 'no'):
                    print(
                        '''INFO: Current scan is aborted and successive ones are kept''')
                    RE_obj.abort()
                else:
                    print('please reenter your input')
        elif usr_input in 'stop()':
            RE_obj.stop()
        else:
            print('please renter your input')


def export_userScriptsEtc():
    """ function that exports user defined objects/scripts stored under
        config_base and userScript.

        This function will create a uncompressed tarball under xpdUser/Export

    Return
    ------
        archive_path : str
        path to archive file just created
    """
    F_EXT = '.tar'
    root_dir = glbl.home
    os.chdir(root_dir)
    f_name = strftime('userScriptsEtc_%Y-%m-%dT%H%M') + F_EXT
    # extra work to avoid comple directory structure in tarball
    tar_f_name = os.path.join(glbl.home, f_name)
    export_dir_list = list(
        map(lambda x: os.path.basename(x), glbl._export_tar_dir))
    with tar.open(tar_f_name, 'w') as f:
        for el in export_dir_list:
            f.add(el)
    archive_path = os.path.join(glbl.home, f_name)
    if os.path.isfile(archive_path):
        return archive_path
    else:
        _graceful_exit(
            'Did you accidentally change write privilege to {}'.format(
                glbl.home))
        print(
            'Please check your setting and try `export_userScriptsEtc()` again at command prompt')
        return


def import_userScriptsEtc():
    """Import user files that have been placed in xpdUser/Import

    Allowed files are python user-script files (extension .py),
    detector-image mask files (.npy) or files containing xpdAcq objects
    (extension .yml). Files created by running export_userScriptsEtc() are
    also allowed.  Unallowed files (anything not in the previous list) will
    be ignored.

    After import, all files in the xpdUser/import directory will be deleted
    The user can run `export_userScriptsEtc` to revert them.

    Return
    ------
        moved_list : list
        a list of file names that have been moved successfully
    """
    _f_ext_dst_dict = ['py', 'npy', 'yml']
    src_dir = glbl.import_dir
    f_list = os.listdir(src_dir)
    if len(f_list) == 0:
        print(
            'INFO: There is no predefined user objects in {}'.format(src_dir))
        return
    # unpack every archived file in Import/
    for f in f_list:
        try:
            # shutil should handle all compressed cases
            tar_full_path = os.path.join(src_dir, f)
            shutil.unpack_archive(tar_full_path, src_dir)
        except ReadError:
            pass
    f_list = os.listdir(src_dir)  # new f_list, after unpack
    moved_list = []
    failure_list = []
    for f_name in f_list:
        if os.path.isfile(os.path.join(src_dir, f_name)):
            src_full_path = os.path.join(src_dir, f_name)
            (root, ext) = os.path.splitext(f_name)
            if ext == '.yml':
                dst_dir = glbl.yaml_dir
                yml_dst_name = _copy_and_delete(f_name, src_full_path, dst_dir)
                moved_list.append(yml_dst_name)
            elif ext == '.py':
                dst_dir = glbl.usrScript_dir
                py_dst_name = _copy_and_delete(f_name, src_full_path, dst_dir)
                moved_list.append(py_dst_name)
            elif ext == '.npy':
                dst_dir = glbl.config_base
                npy_dst_name = _copy_and_delete(f_name, src_full_path, dst_dir)
                moved_list.append(npy_dst_name)
            elif ext in ('.tar', '.zip', '.gztar'):
                pass
            else:
                print('{} is not a supported format'.format(f_name))
                failure_list.append(f_name)
                pass
        else:
            # don't expect user to have directory
            print("I can only import files, not directories."
                  "Please place in the import directory either:\n"
                  "(1) all your files such as scripts, masks and xpdAcq "
                  "object yaml files\n"
                  "(2) a tar or zipped-tar archive file containing "
                  "those files".format(f_name))
            failure_list.append(f_name)
            pass
    if failure_list:
        print("Finished importing. Failed to move {}"
              "but they will leave in Import/".format(failure_list))
    return moved_list


def _copy_and_delete(f_name, src_full_path, dst_dir):
    shutil.copy(src_full_path, dst_dir)
    dst_name = os.path.join(dst_dir, f_name)
    if os.path.isfile(dst_name):
        print('{} has been successfully moved to {}'.format(f_name, dst_dir))
        os.remove(src_full_path)
        return dst_name
    else:
        print("We had a problem moving {}.\n"
              "Most likely it is not a supported file type "
              "(e.g., .yml, .py, .npy, .tar, .gz).\n"
              "It will not be available for use in xpdAcq, "
              "but it will be left in the xpdUser/Import/ directory"
              .format(f_name))
        return


class ExceltoYaml:
    # maintain regularly, aligned with spreadsheet header
    NAME_FIELD = ['Collaborators', 'Sample Maker', 'Lead Experimenter', ]
    COMMA_SEP_FIELD = ['cif name(if exists)', 'User supplied tags']
    PHASE_FIELD = ['Phase Info [required]']
    SAMPLE_NAME_FIELD = ['Sample Name [required]']
    BKGD_SAMPLE_NAME_FIELD = ['Sample-name of sample background']
    DICT_LIKE_FIELD = ['structural database ID for phases'] # return a dict
    # special key for high-dimensional sample phase mapping
    HIGH_D_MD_MAP_KEYWORD = ['gridscan_mappedin']

    # real fields goes into metadata store
    _NAME_FIELD = list(map(lambda x: x.lower().replace(' ', '_'),
                           NAME_FIELD))
    _COMMA_SEP_FIELD = list(map(lambda x: x.lower().replace(' ', '_'),
                                COMMA_SEP_FIELD))
    _SAMPLE_NAME_FIELD = list(map(lambda x: x.lower().replace(' ', '_'),
                                  SAMPLE_NAME_FIELD))
    _BKGD_SAMPLE_NAME_FIELD = list(map(lambda x: x.lower().replace(' ', '_'),
                                       BKGD_SAMPLE_NAME_FIELD))
    _PHASE_FIELD = list(map(lambda x: x.lower().replace(' ', '_'),
                            PHASE_FIELD))
    _DICT_LIKE_FIELD = list(map(lambda x: x.lower().replace(' ', '_'),
                                DICT_LIKE_FIELD))

    def __init__(self, src_dir):
        self.pd_dict = None
        self.sa_md_list = None
        self.src_dir = src_dir

    def load(self, saf_num):
        xl_f = [f for f in os.listdir(self.src_dir) if
                f in (str(saf_num)+'_sample.xls',
                      str(saf_num)+'_sample.xlsx')]
        if not xl_f:
            raise FileNotFoundError("no spreadsheet exists in {}\n"
                                    "have you put it in with correct "
                                    "naming scheme: '<SAF_num>_sample.xlsx'"
                                    "yet?".format(self.src_dir))

        self.pd_dict = pd.read_excel(os.path.join(self.src_dir,
                                                  xl_f.pop()),
                                     skiprows=[1])

        self.sa_md_list = self._pd_dict_to_dict_list(self.pd_dict.to_dict())

    def parse_sample_md(self):
        """parse a list of sample metadata into desired format"""
        parsed_sa_md_list = []
        for sa_md in self.sa_md_list:
            parsed_sa_md = {}
            for k, v in sa_md.items():
                k = str(k).lower()
                v = str(v)
                k = k.strip().replace(' ', '_')
                v = v.replace('/', '_')  # make sure yaml path correct

                # name fields
                if k in self._NAME_FIELD:
                    try:
                        comma_sep_list = self._comma_separate_parser(v)
                        parsed_name = []
                        for el in comma_sep_list:
                            parsed_name.extend(self._name_parser(el))
                    except ValueError:
                        parsed_name = v
                    parsed_sa_md.setdefault(k, [])
                    parsed_sa_md.get(k).extend(parsed_name)

                # phase fields
                elif k in self._PHASE_FIELD:
                    try:
                        (composition_dict,
                         phase_dict,
                         composition_str) = self._phase_parser(v)
                    except ValueError:
                        composition_dict = v
                        phase_dict = v
                    finally:
                        parsed_sa_md.update({'sample_composition':
                                             composition_dict})
                        parsed_sa_md.update({'sample_phase':
                                             phase_dict})
                        parsed_sa_md.update({'composition_string':
                                             composition_str})

                # comma separated fields
                elif k in self._COMMA_SEP_FIELD:
                    try:
                        comma_sep_list = self._comma_separate_parser(v)
                        # print("successfully parsed comma-sep-field {} -> {}"
                        #      .format(v, comma_sep_list))
                    except ValueError:
                        comma_sep_list = v
                    parsed_sa_md.setdefault(k, [])
                    parsed_sa_md.get(k).extend(comma_sep_list)

                # sample name field
                elif k in self._SAMPLE_NAME_FIELD:
                    _k = 'sample_name' # normalized name
                    parsed_sa_md.update({_k: v.replace(' ','_')})

                # bkgd name field
                elif k in self._BKGD_SAMPLE_NAME_FIELD:
                    _k = 'bkgd_sample_name'
                    parsed_sa_md.update({_k:
                                         v.strip().replace(' ', '_')})

                # dict-like field
                elif k in self._DICT_LIKE_FIELD:
                    parsed_sa_md.update({k: self._dict_like_parser(v)})

                # other fields don't need to be parsed
                else:
                    parsed_sa_md.update({k: v})

            parsed_sa_md_list.append(parsed_sa_md)
        self.parsed_sa_md_list = parsed_sa_md_list

    def create_yaml(self, bt):
        """instantiate xpdacq.beamtime.Sample objects based on parsed md

        it also validate if bkgd_sample_name has already appeared as a
        sample_name. If not, it issues a warning

        Parameters
        ----------
        bt : xpdacq.Beamtime object
            an object carries SAF, PI_last and other information

        Returns
        -------
        None
        """
        sample_name_set = set([d['sample_name'] for d in
                               self.parsed_sa_md_list])
        for d in self.parsed_sa_md_list:
            bkgd_name = d.get('bkgd_sample_name')
            sample_name = d.get('sample_name')
            if bkgd_name not in sample_name_set:
                warnings.warn("Bkgd Sample Name `{}` of Smaple `{}` "
                              "does not appear as any of sample_name "
                              "defined in spreadsheet.\n"
                              "This will degrade the workflow of "
                              "auto-reduction. It is recommended to"
                              "enter it correctly\n"
                              "(please ignore if this Sample is "
                              "intentionally created as background"
                              .format(bkgd_name,sample_name),
                              UserWarning)
            Sample(bt, d)
        print("*** End of import Sample object ***")


    def _pd_dict_to_dict_list(self, pd_dict):
        """ parser of pd generated dict to a list of valid sample dicts

        Parameters
        ----------
        pd_dict : dict
            dict generated from pandas.to_dict method

        Return:
        -------
        sa_md_list : list
            a list of dictionaries. Each element is a sample dictionary
        """

        row_num = len(list(pd_dict.values())[0])
        sa_md_list = []
        for i in range(row_num):
            sa_md = {}
            for key in pd_dict.keys():
                sa_md.update({key: pd_dict[key][i]})
            sa_md_list.append(sa_md)

        return sa_md_list

    def _dict_like_parser(self, input_str):
        """ parser for dictionary output"""
        output_dict = {}
        dict_meta = input_str.split(',')
        for el in dict_meta:
            if len(el.split(':')) == 1:
                key = el.split(':').pop()
                val = 'N/A'  # capture default
            else:
                key, val = el.split(':')
            output_dict.update({key.strip(): val.strip()})

        return output_dict

    def _comma_separate_parser(self, input_str):
        """ parser for comma separated fields

        Parameters
        ----------
        input_str : str
            a string contains a series of units that are separated by
            commas.

        Returns
        -------
        output_list : list
            a list contains comma separated element parsed strings.
        """
        element_list = input_str.split(',')
        output_list = list(map(lambda x: x.strip(), element_list))
        return output_list

    def _name_parser(self, name_str):
        """assume a name string

        Returns
        -------
        name_list : list
            a list of strings in [<first_name>, <last_name>] form
        """
        name_list = name_str.split(' ')
        if len(name_list) > 2:
            name_list = [name_str]
        return name_list  # [first, last]

    def _phase_parser(self, phase_str):
        """parser for field with <chem formula>: <phase_amount>

        Parameters
        ----------
        phase_str : str
            a string contains a series of <chem formula> : <phase_amount>.
            Each phase is separated by a comma.

        Returns
        -------
        composition_dict : dict
            a dictionary contains {element: stoichiometry}.
        phase_dict : dict
            a dictionary contains relative ratio of phases.
        composition_str : str
            a string with the format PDF transfomation software
            takes. default is pdfgetx

        Examples
        --------
        rv = cls._phase_parser('NaCl:1, Si:2')
        rv[0] # {'Na':0.33, 'Cl':0.33, 'Si':0.67}
        rv[1] # {'Nacl':0.33, 'Si':0.67}
        rv[2] # 'Na0.33Cl0.5Si0.5'

        Raises:
        -------
        ValueError
            if ',' is not specified between phases
        """
        phase_dict = {}
        composition_dict = {}
        composition_str = ''

        compound_meta = phase_str.split(',')
        # figure out ratio between phases
        for el in compound_meta:
            el = el.strip()
            # there is no ":" in the string            
            if ':' not in el:
                # take whatever alpha numeric string before symbol
                # to be the chemical element
                symbl = [char for char in el if not char.isalnum()]
                if symbl:
                    # take the first symbol
                    symbl_ind = el.find(symbl[0])
                    com = el[:symbl_ind]
                else:
                    # simply take whole string
                    com = el
                amount = 1.0
            else:
                meta = el.split(':')
                # there is a ":" but nothing follows
                if len(meta[1])==0:
                    com = meta[0]
                    amount = 1.0
                # presumably valid input
                else:
                    com, amount = meta
            # construct phase dict
            # special case: mapping 
            if com in self.HIGH_D_MD_MAP_KEYWORD:
                print("INFO: you assigned customized mapping {} for"
                      " high dimensional sample mapping scheme {}"
                      .format(amount, com))
                phase_dict.update({com.strip(): amount.strip()})
                composition_str = 'N/A'
                composition_dict = {}
            # normal case, e.g. {'Ni':0.5, 'NaCl':0.5}
            elif isinstance(amount, str):
                amount = amount.strip()
                amount = amount.replace('%', '')

            # construct the not normalized phase dict
            phase_dict.update({com.strip(): float(amount)})

        # normalize phase ratio for composition dict
        total = sum(phase_dict.values())
        for k, v in phase_dict.items():
            ratio = round(v/total, 2)
            phase_dict[k] = ratio

        # construct composition_dict
        for k, v in phase_dict.items():
            el_list, sto_list = composition_analysis(k.strip())
            for el, sto in zip(el_list, sto_list):
                # element appears in different phases, adds up
                if el in composition_dict:
                    val = composition_dict.get(el)
                    val += sto * ratio
                    composition_dict.update({el: val})
                else:
                    # otherwise, just update it
                    composition_dict.update({el: sto * ratio})

        # finally, construct composition_str
        for k,v in sorted(composition_dict.items()):
            composition_str += str(k)+str(v)

        return composition_dict, phase_dict, composition_str

excel_to_yaml = ExceltoYaml(glbl.import_dir)


def import_sample_info(saf_num=None, bt=None, validate_only=False):
    """ import sample metadata based on a spreadsheet

    this function expects a pre-populated '<SAF_number>_sample.xls' file
    located under `xpdUser/import` directory. Corresponding Sample objects
    will be created after information stored being parsed. Please go to
    http://xpdacq.github.io for parser rules.

    Parameters
    ----------
    saf_num : int, optional
        Safety Approval Form number of beamtime. default is read from
        current Beamtime object.
    bt : xpdacq.beamtime.Beamtime, optional
        beamtime object that is going to be linked with these samples.
        default is the Beamtime object in current ipython session.
    validate_only : bool, optional
        option of validating metadata entered in spreadsheet. if
        True, program will go through entire metadata and return
        keys with invalid character but not create Sample objects.
        default to False.
    """

    if bt is None:
        error_msg = "WARNING: Beamtime object does not exist in current"\
                    "ipython session. Please make sure:\n"\
                    "1. a beamtime has been started\n"\
                    "2. double check 'bt_bt.yml' exists under "\
                    "xpdUser/config_base/yml directory.\n"\
                    "\n"\
                    "If any of these checks fails or problem "\
                    "persists, please contact beamline staff immediately"
        _check_obj('bt', error_msg)  # raise NameError if bt is not alive
        ips = get_ipython()
        bt = ips.ns_table['user_global']['bt']

    # pass to core function
    _import_sample_info(saf_num=saf_num, bt=bt,
                        validate_only=validate_only)


def _import_sample_info(saf_num=None, bt=None, validate_only=False):
    """ core function to import sample metadata based on a spreadsheet

    this function expects a pre-populated '<SAF_number>_sample.xlxs' file
    located under `xpduser/import` directory. Corresponding Sample objects
    will be created after information stored being parsed. Please go to
    http://xpdacq.github.io for parser rules.

    Parameters
    ----------
    saf_num : int, optional
        Safety Approval Form number of beamtime. default is read from
        current Beamtime object.
    bt : xpdacq.beamtime.Beamtime, optional
        beamtime object that is going to be linked with these samples.
        default is the Beamtime object in current ipython session.
    validate_only : bool, optional
        option of validating metadata entered in spreadsheet. if
        True, program will go through entire metadata and return
        keys with invalid character but not create Sample objects.
        default to False.
    """

    # at core function level, bt should strictly be Beamtime,
    # raise if it is not this case
    if not isinstance(bt, Beamtime):
        raise TypeError("WARNING: illegal Beamtime object argument!.\n"
                        "input object {} has type = {}\n"
                        "Please make sure you are handing correct object\n"
                        "or double check if you already started a beamtime"
                        .format(bt, type(bt)))
        return

    if saf_num is None:
        try:
            saf_num = bt['bt_safN']
        except KeyError:
            print("WARNING: there is no SAF number information in this "
                  "beamtime object.\n Do you feed in a valid beamtime "
                  "object?")
            return
    else:
        # user input, test if saf_num is consistent with bt
        saf_num_from_bt = bt['bt_safN']
        saf_num = str(saf_num)
        if saf_num != saf_num_from_bt:
            raise ValueError("WARNING: you give a SAF number = {}, "
                             "while SAF number of current beamtime is = {}\n"
                             "Please make sure you are using the correct "
                             "SAF number/beamtime combination"
                             .format(saf_num, saf_num_from_bt))
            return
    print('INFO: using SAF_number = {}'.format(saf_num))

    bt.samples = []
    # exclude Sample objects from reference list
    # logic: only update Sample objects that are currently in bt.list
    sp_ref = [el for el in bt._referenced_by if isinstance(el, ScanPlan)]
    bt._referenced_by = sp_ref
    excel_to_yaml.src_dir = glbl.import_dir
    excel_to_yaml.load(saf_num)
    excel_to_yaml.parse_sample_md()
    if validate_only:
        for md_dict in excel_to_yaml.parsed_sa_md_list:
            validate_dict_key(md_dict, '.', ',')
        # no invalid keys were found
        print("INFO: all metadata entered are clean and good to go")
        print("INFO: please set 'validate_only=False' and "
              "run this commend again to create Sample objects")
        return
    else:
        excel_to_yaml.create_yaml(bt)
        return excel_to_yaml
