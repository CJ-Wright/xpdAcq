# functional test on notebook server (analysis side)
import os
import datetime
from time import strftime
import numpy as np
import tifffile as tif
import matplotlib as plt
#from xpdacq.glbl import glbl 
# no xpdAcq installed on notebook server

_fname_field = ['sa_name','sc_name']
home_dir = os.path.expanduser('~/xpdUser')
w_dir = os.path.join(home_dir, 'tiff_base')
W_DIR = w_dir # in case of crashes in old codes

def _feature_gen(header):
    ''' generate a human readable file name. 

    file name is generated by metadata information in header 
    '''
    uid = header.start.uid[:6]
    feature_list = []
    
    field = header['start']
    for key in _fname_field:

        # get special label
        try:
            if header.start['xp_isdark']:
                feature_list.append('dark')
        except KeyError:
            pass

        try:
            el = field[key]
            # truncate string length
            if len(el)>12:
                value = el[:12]
            else:
                value = el
            # clear space
            feature = [ ch for ch in list(el) if ch!=' ']
            feature_list.append(''.join(feature))
        except KeyError:
            pass # protection to allow missing required fields. This should not happen
    f_name = "_".join(feature_list)
    return f_name

def _timestampstr(timestamp):
    ''' convert timestamp to strftime formate '''
    timestring = datetime.datetime.fromtimestamp(float(timestamp)).strftime('%Y%m%d-%H%M')
    return timestring

def save_last_tiff(dark_subtraction=True, max_count_num=None):
    if not max_count_num:
        save_tiff(db[-1], dark_subtraction, max_count = max_count_num)
    else:
        save_tiff(db[-1], dark_subtraction)

def save_tiff(headers, dark_subtraction = True, *, max_count = None):
    ''' save images obtained from dataBroker as tiff format files. It returns nothing.

    arguments:
        headers - list - a list of header objects obtained from a query to dataBroker
    '''
    F_EXTEN = '.tiff'
    e = '''Can not find a proper dark image applied to this header.
        Files will be saved but not no dark subtraction will be applied'''
    is_dark_subtracted = False # assume not has been done
    
    # prepare header
    if type(list(headers)[1]) == str:
        header_list = list()
        header_list.append(headers)
    else:
        header_list = headers

    for header in header_list:
        print('Saving your image(s) now....')
        # information at header level
        img_field = _identify_image_field(header)
        for ev in get_events(header):
            img = ev['data'][img_field]
            ind = ev['seq_num']
            f_name = _feature_gen(header)
            event_timestamp = ev['timestamps']['pe1_image'] # time when triggering area detector
            
            # dark subtration logic 
            if dark_subtraction:
                try:
                    dark_uid_appended = header.start['sc_params']['dk_field_uid']
                    try:
                        # bluesky only looks for uid it defines
                        dark_search = {'group':'XPD','xp_dark_uid':dark_uid_appended} # this should be refine later
                        dark_header = db(**dark_search)
                        dark_img = np.array(get_images(dark_header, img_field)).squeeze()
                    except ValueError: 
                        print(e) # protection. Should not happen
                        dark_img = np.zeros_like(light_imgs)
                    img -= dark_img
                    is_dark_subtracted = True # label it only if it is successfully done
                except KeyError:
                    print(e) # backward support. For scans with auto_dark turned off
                    pass
            # complete file name
            f_name = f_name +_timestampstr(event_timestamp)
            if is_dark_subtracted:
                f_name = 'sub_' + f_name
            if 'temperature' in ev['data']:
                f_name = f_name + '_'+str(ev['data']['temperature'])+'K'
            # index is still needed as we don't want timestamp in file name down to seconds
            combind_f_name = '{}_{}{}'.format(f_name, ind, F_EXTEN)
            w_name = os.path.join(W_DIR, combind_f_name)
            print(w_name)
            #tif.imsave(w_name, img) 
            #if os.path.isfile(w_name):
                #print('image "%s" has been saved at "%s"' % (combind_f_name, W_DIR))
            #else:
                #print('Sorry, something went wrong with your tif saving')
                #return
            if max_count is not None and ind >= max_count:
                break # break the loop if max_count reach or already collect all images
    print('||********Saving process FINISHED********||')
def _identify_image_field(header):
    ''' small function to identify image filed key words in header
    '''
    try:
        img_field =[el for el in header.descriptors[0]['data_keys'] if el.endswith('_image')][0]
        print('Images are pulling out from %s' % img_field)
        return img_field
    except IndexError:
        uid = header.start.uid
        print('This header with uid = %s does not contain any image' % uid)
        print('Was area detector correctly mounted then?')
        print('Stop here')
        return


## functional tests on notebook server ##
def main():
    try:
        # at notebook server
        from dataportal import DataBroker as db
        from dataportal import get_events, get_images
    except:
        # at XPD
        from databroker import DataBroker as db
        from databroker import get_events, get_images

    save_tiff(db['ded100bc-66d4-4b3c-a441-ba3a37fe3730']) # Temperature ramp scan
    save_tiff(db['4674074a-d6e8-459f-a5c4-3bd505f2e867']) # 'auto_dark = off' scan
    save_tiff(db['8bec2649-6b66-4859-b6cd-00b3761d2d0d']) # time series scan

if __name__ == '__main__':
    main()
