#!/usr/bin/env python2

"""
Created: 4 January 2017
Purpose: Generate visualisations of obs/sim ratios, PGA, PGV, PSA.
Authors: Viktor Polak <viktor.polak@canterbury.ac.nz>

USAGE:
Execute with python: "$ ./plot_stations.py" or "$ python2 plot_stations.py"
First parameter is the file to plot.

INPUT FORMAT:
File to plot must be in the following format:
Note numbers are lines of the file.
1. Plot Title (blank line for no title)
2. Legend Title for the colour palette scale
3. cpt source, station size
cpt source and station size can be followed by comma separated properties after a ':'
..::cpt source examples::..
hot:invert,t-40 will invert the hot palette and display with 40% transparency
hot:fg-black,bg-white set foreground and background colour
..::station size examples::..
0.2:shape-c will make the station size 0.2 with a circle shape
1k:g-nearneighbor will make grid spacing 1km and use the nearneighbor algorithm
4. min cpt, max cpt, cpt inc, cpt legend tick
all optionoal but cpt min and max must both be provided or none at all
optional parameters must be in order
5. number of data colums excluding longitude and latitude, optional label colour
6. comma separated column labels. placed inside top left corner of map.
Optional but must either be of length 0 or number of columns

7 - END. Data are longitude, latitude, col_1, col_2 ... col_N

ISSUES:
"""

from glob import glob
import multiprocessing as mp
import os
from shutil import copy, rmtree
import sys
sys.path.append('.')
from tempfile import mkdtemp
from time import time

import numpy as np

import qcore_path
from shared import get_corners
from gmt import *
from srf import srf2corners
try:
    import params_base as sim_params
    SIM_DIR = True
except ImportError:
    SIM_DIR = False
script_dir = os.path.abspath(os.path.dirname(__file__))
if not os.path.exists('params_plot.py'):
    copyfile('%s/params_plot.template.py' % (script_dir), 'params_plot.py')
import params_plot
statplot = params_plot.STATION

try:
    station_file = os.path.abspath(sys.argv[1])
    assert(os.path.exists(station_file))
except IndexError:
    print('First parameter must be input file. Parameter not found.')
    exit(1)
except AssertionError:
    print('Cannot find input file: %s' % (station_file))
    exit(1)

# all numerical values in input
val_pool = np.loadtxt(station_file, dtype = 'f', skiprows = 6)[:, 2:].flatten()

# process file header
print('Processing input header...')
with open(station_file) as statf:
    head = [next(statf).strip() for _ in xrange(6)]
    # 1st - title
    title = head[0]

    # 2nd line - legend title
    legend = head[1]

    # 3rd line - cpt description 1
    # src, point size, foreground colour, background colour
    cpt_info = head[2].split()
    cpt = cpt_info[0].split(':')[0]
    # default properties
    transparency = 0
    cpt_fg = None
    cpt_bg = None
    if os.path.exists(cpt):
        # assuming it is a built in cpt if not matching filename
        cpt = os.path.abspath(cpt)
    try:
        # src:invert will add the 'invert' property to invert cpt
        cpt_properties = cpt_info[0].split(':')[1].split(',')
        for p in cpt_properties:
            if p[:2] == 't-':
                transparency = p[2:]
            elif p[:3] == 'fg-':
                cpt_fg = p[3:]
            elif p[:3] == 'bg-':
                cpt_bg = p[3:]
    except IndexError:
        cpt_properties = []
    if len(cpt_info) > 1:
        stat_size = cpt_info[1].split(':')[0]
        # default properties
        shape = 't'
        grid = None
        try:
            stat_properties = cpt_info[1].split(':')[1].split(',')
            for p in stat_properties:
                if p[:6] == 'shape-':
                    shape = p[6]
                elif p[:2] == 'g-':
                    grid = p[2:]
        except IndexError:
            stat_properties = []

    # 4th line - cpt description 2
    # cpt_min, cpt_max, cpt_inc, cpt_tick
    cpt_info2 = head[3].split()
    if len(cpt_info2) > 1:
        cpt_min, cpt_max = map(float, cpt_info2[:2])
    else:
        cpt_max = np.percentile(val_pool, 99.5)
        # 2 significant figures
        cpt_max = round(cpt_max, 2 - int(np.floor(np.log10(cpt_max))) - 1)
        if val_pool.min() < 0:
            cpt_min = -cpt_max
        else:
            cpt_min = 0
    if len(cpt_info2) > 2:
        cpt_inc = float(cpt_info2[2])
    else:
        cpt_inc = cpt_max / 6.
    if len(cpt_info2) > 3:
        cpt_tick = float(cpt_info2[3])
    else:
        cpt_tick = cpt_inc * 2

    # 5th line ncols and optional column label prefix
    col_info = head[4].split()
    ncol = int(col_info[0])
    if len(col_info) > 1:
        label_colour = col_info[1]
    else:
        label_colour = 'black'

    # 6th line - column labels
    col_labels = map(str.strip, head[5].split(','))
    if col_labels == ['']:
        col_labels = []
    if len(col_labels) != ncol and len(col_labels) != 0:
        print('%d column labels found when there are %d columns.' \
                % (len(col_labels), ncol))
        exit(1)

print('Header Processed.')

# temporary working directories for gmt are within here
# prevent multiprocessing issues by isolating processes
gmt_temp = os.path.join(os.path.abspath('.'), 'GMT_WD_STATIONS')

# allow overriding output directories more easily when scripting
if len(sys.argv) > 2:
    statplot.out_dir = os.path.abspath(sys.argv[2])
# clear output dirs
for out_dir in [statplot.out_dir, gmt_temp]:
    if os.path.isdir(out_dir):
        rmtree(out_dir)
    os.makedirs(out_dir)

if SIM_DIR:
    if os.path.exists(sim_params.MODELPARAMS):
        corners, cnr_str = get_corners(sim_params.MODELPARAMS, gmt_format = True)
    else:
        print("MODELPARAMS path in params_base.py is invalid.")
        print("Looking for XYTS file to extract simulation boundary instead.")
        # xyts file is placed here in some cases when transferred from fitzroy
        try:
            if os.path.exists(sim_params.xyts_files[0]):
                xytsf = XYTSFile(sim_params.xyts_files[0])
                corners, cnr_str = xytsf.corners(gmt_format = True)
        except NameError:
            print('Couldn\'t find simulation domain. Fix params_base.py.')

if statplot.region == None and SIM_DIR:
    # fit simulation region
    x_min = min([xy[0] for xy in corners])
    x_max = max([xy[0] for xy in corners])
    y_min = min([xy[1] for xy in corners])
    y_max = max([xy[1] for xy in corners])
elif statplot.region == None:
    # fit all values
    xy = np.loadtxt(station_file, dtype = 'f', skiprows = 6)[:, :2]
    x_min, y_min = np.min(xy, axis = 0) - 0.1
    x_max, y_max = np.max(xy, axis = 0) + 0.1
else:
    x_min, x_max, y_min, y_max = statplot.region

# avg lon/lat (midpoint of plotting region)
ll_avg = (x_min + x_max) / 2.0, (y_min + y_max) / 2.0
# combined region
ll_region = (x_min, x_max, y_min, y_max)

# create masking if using grid overlay
if grid != None:
    mask = '%s/mask.grd' % (gmt_temp)
    try:
        path_from_corners(corners = corners, min_edge_points = 100, \
                output = '%s/sim.modelpath_hr' % (gmt_temp))
    except NameError:
        path_from_corners(corners = [ \
                [x_min, y_min], [x_max, y_min], \
                [x_max, y_max], [x_min, y_max]], \
                min_edge_points = 100, \
                output = '%s/sim.modelpath_hr' % (gmt_temp))
    grd_mask('%s/sim.modelpath_hr' % (gmt_temp), mask, \
            dx = stat_size, dy = stat_size, region = ll_region)

if statplot.sites == None or statplot.sites == 'major':
    region_sites = sites_major
elif statplot.sites == 'all':
    region_sites = sites.keys()
else:
    region_sites = statplot.sites

###
### PLOTTING STARTS HERE - TEMPLATE
###
######################################################

cpt_land = '%s/land.cpt' % (gmt_temp)
cpt_stations = '%s/stations.cpt' % (gmt_temp)
ps_template = '%s/template.ps' % (gmt_temp)

### create resources that are used throughout the process
t0 = time()
# topography colour scale
makecpt('%s/cpt/palm_springs_1.cpt' % \
        (os.path.abspath(os.path.dirname(__file__))), cpt_land, \
        -250, 9000, inc = 10, invert = True)
# overlay colour scale
makecpt(cpt, cpt_stations, cpt_min, cpt_max, \
        inc = cpt_inc, invert = 'invert' in cpt_properties, \
        fg = cpt_fg, bg = cpt_bg, transparency = transparency)

### create a basemap template which all maps start with
t = GMTPlot(ps_template)
# background can be larger as whitespace is later cropped
t.background(11, 15)
t.spacial('M', ll_region, sizing = statplot.width, \
        x_shift = 1, y_shift = 2.5)
# topo, water, overlay cpt scale
t.land(fill = 'darkgreen')
t.topo(statplot.topo_file, cpt = cpt_land)
t.water(colour = 'lightblue', res = 'f')
t.coastlines()
t.cpt_scale(3, -0.5, cpt_stations, cpt_tick, cpt_inc, \
        label = legend, \
        arrow_f = cpt_max > 0, arrow_b = cpt_min < 0)
try:
    # simulation domain if loaded before
    t.path(cnr_str, is_file = False, split = '-', \
            close = True, width = '0.4p', colour = 'black')
except NameError:
    pass
if SIM_DIR:
    # fault file - creating direct from SRF is slower
    try:
        if os.path.exists(sim_params.srf_files[0]):
            srf2corners(sim_params.srf_files[0], cnrs = '%s/srf_cnrs.txt' % (gmt_temp))
        elif os.path.exists(sim_params.srf_cnrs[0]):
            copyfile(sim_params.srf_cnrs[0], '%s/srf_cnrs.txt' % (gmt_temp))
    except AttributeError:
        print('SRF or corners file not found, not adding fault planes to plot.')
# ticks on top otherwise parts of map border may be drawn over
t.ticks(major = statplot.tick_major, minor = statplot.tick_minor, sides = 'ws')
t.leave()
print('Created template resources (%.2fs)' % (time() - t0))


###
### PLOTTING CONTINUES - COLUMN LOOPING
###
######################################################

def render_period(n):
    t0 = time()

    # prepare resources in separate folder
    # prevents GMT IO errors on its conf/history files
    swd = mkdtemp(prefix = 'p%.3dwd_' % (n), dir = gmt_temp)
    # name of slice postscript
    ps = '%s/c%.3d.ps' % (swd, n)

    # copy GMT setup and basefile
    copy('%s/gmt.conf' % (gmt_temp), swd)
    copy('%s/gmt.history' % (gmt_temp), swd)
    copyfile(ps_template, ps)
    p = GMTPlot(ps, append = True)

    # common title
    if len(title):
        p.text(ll_avg[0], y_max, title, colour = 'black', \
                align = 'CB', size = 28, dy = 0.2)

    # title for this data column
    if len(col_labels):
        p.text(x_min, y_max, col_labels[n], colour = label_colour, \
                align = 'LB', size = '18p', dx = 0.2, dy = -0.35)

    # add ratios to map
    if grid == None:
        p.points(station_file, shape = shape, size = stat_size, \
                fill = None, line = None, cpt = cpt_stations, \
                cols = '0,1,%d' % (n + 2), header = 6)
    else:
        grd_file = '%s/overlay.grd' % (swd)
        table2grd(station_file, grd_file, file_input = True, \
                grd_type = grid, region = ll_region, dx = stat_size, \
                climit = cpt_inc * 0.5, wd = swd, geo = True, \
                sectors = 4, min_sectors = 1, search = stat_size, \
                cols = '0,1,%d' % (n + 2), header = 6)
        p.overlay(grd_file, cpt_stations, dx = stat_size, dy = stat_size, \
                crop_grd = mask, land_crop = False, transparency = transparency)
    # add srf to map
    if os.path.exists('%s/srf_cnrs.txt' % (gmt_temp)):
        p.fault('%s/srf_cnrs.txt' % (gmt_temp), is_srf = False, \
                plane_width = 0.5, top_width = 1, hyp_width = 0.5)
    # add locations to map
    p.sites(region_sites)

    # create PNG
    p.finalise()
    p.png(dpi = statplot.dpi, out_dir = statplot.out_dir, clip = True)

    print('Column %d complete in %.2fs' % (n, time() - t0))

#for n in xrange(ncol):
#    render_period(n)
pool = mp.Pool(8)
pool.map(render_period, xrange(ncol))

# clear all working files
rmtree(gmt_temp)