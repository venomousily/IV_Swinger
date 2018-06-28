#!/usr/bin/env python
"""IV Swinger 2 configuration and control module"""
#
###############################################################################
#
# IV_Swinger2.py: IV Swinger 2 configuration and control module
#
# Copyright (C) 2017,2018  Chris Satterlee
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
#
# IV Swinger and IV Swinger 2 are open source hardware and software
# projects
#
# Permission to use the hardware designs is granted under the terms of
# the TAPR Open Hardware License Version 1.0 (May 25, 2007) -
# http://www.tapr.org/OHL
#
# Permission to use the software is granted under the terms of the GNU
# GPL v3 as noted above.
#
# Current versions of the licensing files, documentation, Fritzing file
# (hardware description), and software can be found at:
#
#    https://github.com/csatt/IV_Swinger
#
###############################################################################
#
# This file contains the Python code that implements the IV Swinger 2
# hardware control, configuration, plotting, and debug logging.  It
# provides an API to higher level code such as (but not limited to) a
# graphical user interface (GUI).
#
# IV Swinger 2 (IVS2) is very different from the original IV Swinger
# (IVS1), yet there are still some opportunities to leverage the IVS1
# code (if not for that fact, it might even have made more sense to use
# a different language than Python for IVS2). The IV_Swinger2 class in
# this module extends the IV_Swinger class, allowing code re-use where
# it makes sense. The IV_Singer_plotter module is also imported and used
# for plotting the results.
#
# The Raspberry Pi (RPi) is the compute platform for IVS1.  On IVS1, the
# Python code runs on the RPi; it controls the IV Swinger hardware,
# captures measurements, and writes the data and graphs to one or more
# USB flash drives. IVS2 uses an Arduino to control the hardware and
# take the voltage and current measurements. The IVS2 Python code runs
# on an external "host", which is most likely a Windows or Mac laptop
# computer.  But the host computer can be anything that is capable of
# running Python (including RPi).
#
# As mentioned above, the higher level code that sits on top of this
# module can be something other than the GUI that is used for the IV
# Swinger 2 application. For example, a command-line interface (CLI)
# could be implemented. Another example would be a Python script that
# implements some kind of automated test, potentially also interacting
# with other devices. Imagine, for example, a device that incrementally
# moves "shade" across the PV module - a script could loop, moving the
# shade a step and swinging an IV curve on each iteration.
#
import argparse
import ConfigParser
import difflib
import glob
import io
import math
import os
import re
import serial
import serial.tools.list_ports
import shutil
import subprocess
import sys
import time
from PIL import Image
from inspect import currentframe, getframeinfo
try:
    # Mac only
    from AppKit import NSSearchPathForDirectoriesInDomains as get_mac_dir
    from AppKit import NSApplicationSupportDirectory as mac_app_sup_dir
    from AppKit import NSUserDomainMask as mac_domain_mask
except:
    pass
import IV_Swinger
import IV_Swinger_plotter

#################
#   Constants   #
#################
APP_NAME = "IV_Swinger2"
RC_SUCCESS = 0
RC_FAILURE = -1
RC_BAUD_MISMATCH = -2
RC_TIMEOUT = -3
RC_SERIAL_EXCEPTION = -4
RC_ZERO_VOC = -5
RC_ZERO_ISC = -6
RC_ISC_TIMEOUT = -7
RC_NO_POINTS = -8
CFG_STRING = 0
CFG_FLOAT = 1
CFG_INT = 2
CFG_BOOLEAN = 3
SKETCH_VER_LT = -1
SKETCH_VER_EQ = 0
SKETCH_VER_GT = 1
SKETCH_VER_ERR = -2
LATEST_SKETCH_VER = "1.3.0"
MIN_PT1_TO_VOC_RATIO_FOR_ISC = 0.20

# From IV_Swinger
PLOT_COLORS = IV_Swinger.PLOT_COLORS
AMPS_INDEX = IV_Swinger.AMPS_INDEX
VOLTS_INDEX = IV_Swinger.VOLTS_INDEX
OHMS_INDEX = IV_Swinger.OHMS_INDEX
WATTS_INDEX = IV_Swinger.WATTS_INDEX
INFINITE_VAL = IV_Swinger.INFINITE_VAL

# From Arduino SPI.h:
SPI_CLOCK_DIV4 = 0x00
SPI_CLOCK_DIV16 = 0x01
SPI_CLOCK_DIV64 = 0x02
SPI_CLOCK_DIV128 = 0x03
SPI_CLOCK_DIV2 = 0x04
SPI_CLOCK_DIV8 = 0x05
SPI_CLOCK_DIV32 = 0x06
# Default plotting config
FONT_SCALE_DEFAULT = 1.0
LINE_SCALE_DEFAULT = 1.0
POINT_SCALE_DEFAULT = 1.0
# Default Arduino config
SPI_CLK_DEFAULT = SPI_CLOCK_DIV8
MAX_IV_POINTS_DEFAULT = 140
MIN_ISC_ADC_DEFAULT = 100
MAX_ISC_POLL_DEFAULT = 5000
ISC_STABLE_DEFAULT = 5
MAX_DISCARDS_DEFAULT = 300
ASPECT_HEIGHT_DEFAULT = 2
ASPECT_WIDTH_DEFAULT = 3
# Other Arduino constants
ARDUINO_MAX_INT = (1 << 15) - 1
MAX_IV_POINTS_MAX = 275
ADC_MAX = 4095
MAX_ASPECT = 8
# Default calibration values
V_CAL_DEFAULT = 1.0197
I_CAL_DEFAULT = 1.1187
# Default resistor values
R1_DEFAULT = 150000.0   # R1 = 150k nominal
R1_DEFAULT_BUG = 180000.0   # This was a bug
R2_DEFAULT = 7500.0     # R2 = 7.5k nominal
RF_DEFAULT = 75000.0    # Rf = 75k
RG_DEFAULT = 1000.0     # Rg = 1k
SHUNT_DEFAULT = 5000.0  # Shunt = 5000 microohms
# Arduino EEPROM constants
EEPROM_VALID_ADDR = 0
EEPROM_VALID_COUNT_ADDR = 4
EEPROM_R1_OHMS_ADDR = 8
EEPROM_R2_OHMS_ADDR = 12
EEPROM_RF_OHMS_ADDR = 16
EEPROM_RG_OHMS_ADDR = 20
EEPROM_SHUNT_UOHMS_ADDR = 24
EEPROM_V_CAL_X1M_ADDR = 28
EEPROM_I_CAL_X1M_ADDR = 32
EEPROM_V_BATT_X1M_ADDR = 36  # Obsolete
EEPROM_R_BATT_X1M_ADDR = 40  # Obsolete
EEPROM_VALID_VALUE = "123456.7890"
EEPROM_VALID_COUNT = 9  # increment if any added (starts at addr 8)
# Debug constants
DEBUG_CONFIG = False


########################
#   Global functions   #
########################
def get_date_time_str():
    return IV_Swinger.DateTimeStr.get_date_time_str()


def extract_date_time_str(input_str):
    return IV_Swinger.DateTimeStr.extract_date_time_str(input_str)


def is_date_time_str(input_str):
    return IV_Swinger.DateTimeStr.is_date_time_str(input_str)


def xlate_date_time_str(date_time_str):
    return IV_Swinger.DateTimeStr.xlate_date_time_str(date_time_str)


def close_plots():
    IV_Swinger.IV_Swinger.close_plots()


def sys_view_file(file):
    """Method to use an OS-specific application to view a file, based on
       its file type/extension. e.g. a .txt file will be opened
       using a text editor, a PDF file will be opened with
       whatever is normally used to view PDFs (Acrobat reader,
       Preview, etc.)
    """
    if sys.platform == "darwin":
        # Mac
        subprocess.call(("open", file))
    elif sys.platform == "win32":
        # Windows
        os.startfile(file)
    else:
        # Linux
        subprocess.call(("xdg-open", file))


def gen_dbg_str(str):
    cf = currentframe()
    fi = getframeinfo(cf)
    dbg_str = "DEBUG({}, line {}): {}".format(fi.filename,
                                              cf.f_back.f_lineno,
                                              str)
    return dbg_str


#################
#   Classes     #
#################


# Configuration class
#
class Configuration(object):
    """Provides support for saving and restoring configuration values. Only
       the configuration values that map to properties in the
       IV_Swinger2 class are included, but the class can be extended to
       add others.
    """

    # Initializer
    def __init__(self, ivs2=None):
        self.ivs2 = ivs2
        self.cfg = ConfigParser.SafeConfigParser()
        self.cfg_snapshot = ConfigParser.SafeConfigParser()
        self._cfg_filename = None
        self._starting_cfg_filename = None
        self.save_starting_cfg_file()

    # ---------------------------------
    @property
    def cfg_filename(self):
        """Name of file (full path) that contains preferences and other
           configuration options
        """
        if self._cfg_filename is None:
            self._cfg_filename = os.path.join(self.ivs2.app_data_dir,
                                              "{}.cfg".format(APP_NAME))
        return self._cfg_filename

    @cfg_filename.setter
    def cfg_filename(self, value):
        if value is not None and not os.path.isabs(value):
            raise ValueError("cfg_filename must be an absolute path")
        self._cfg_filename = value

    # ---------------------------------
    @property
    def starting_cfg_filename(self):
        """Name of file (full path) that contains preferences and other
           configuration options
        """
        if self._starting_cfg_filename is None:
            self._starting_cfg_filename = os.path.join(self.ivs2.app_data_dir,
                                                       "{}_starting.cfg"
                                                       .format(APP_NAME))
        return self._starting_cfg_filename

    @starting_cfg_filename.setter
    def starting_cfg_filename(self, value):
        if value is not None and not os.path.isabs(value):
            raise ValueError("starting_cfg_filename must be an absolute path")
        self._starting_cfg_filename = value

    # -------------------------------------------------------------------------
    def save_starting_cfg_file(self):
        """Method to save the starting config file. Mostly a debug feature,
           but not dependent on DEBUG_CONFIG.
        """
        if os.path.exists(self.cfg_filename):
            shutil.copyfile(self.cfg_filename, self.starting_cfg_filename)
        else:
            if os.path.exists(self.starting_cfg_filename):
                os.remove(self.starting_cfg_filename)
            # Create an empty file
            open(self.starting_cfg_filename, "a").close()

    # -------------------------------------------------------------------------
    def log_cfg_diffs(self):
        """Method to log the differences between the starting config file
           and the current config file.
        """
        diff = difflib.ndiff(open(self.starting_cfg_filename).readlines(),
                             open(self.cfg_filename).readlines())
        heading_str = "Config file diffs\n                 -----------------\n"
        log_str = "{}{}".format(heading_str, "".join(diff))
        self.ivs2.logger.log(log_str)

    # -------------------------------------------------------------------------
    def cfg_set(self, section, option, value):
        """Method to set a config option. Just a wrapper around the
           ConfigParser set method, but converts value to a string
           first.
        """
        self.cfg.set(section, option, str(value))

    # -------------------------------------------------------------------------
    def cfg_dump(self, dump_header=None):
        if dump_header is not None:
            self.ivs2.logger.print_and_log("DUMP: {}".format(dump_header))
        for section in self.cfg.sections():
            self.ivs2.logger.print_and_log(section)
            for option in self.cfg.options(section):
                dump_str = " {}={}".format(option,
                                           self.cfg.get(section, option))
                self.ivs2.logger.print_and_log(dump_str)

    # -------------------------------------------------------------------------
    def get(self):
        """Method to get the saved preferences and other configuration from the
           .cfg file if it exists, and apply the values to the
           associated properties
        """
        if DEBUG_CONFIG:
            dbg_str = "get: Reading config from {}".format(self.cfg_filename)
            self.ivs2.logger.print_and_log(dbg_str)
        try:
            with open(self.cfg_filename, "r") as cfg_fp:
                self.cfg.readfp(cfg_fp)
                if DEBUG_CONFIG:
                    self.cfg_dump()
        except IOError:
            # File doesn't exist
            self.ivs2.find_arduino_port()
            self.populate()
            self.save()
        else:
            # File does exist ...
            self.apply_all()

    # -------------------------------------------------------------------------
    def get_snapshot(self):
        """Method to get the saved preferences and other configuration
           from the .cfg file and store them in the snapshot config
        """
        if DEBUG_CONFIG:
            dbg_str = ("get_snapshot: Reading config "
                       "from {}".format(self.cfg_filename))
            self.ivs2.logger.print_and_log(dbg_str)
        self.cfg_snapshot = ConfigParser.SafeConfigParser()
        with open(self.cfg_filename, "r") as cfg_fp:
            self.cfg_snapshot.readfp(cfg_fp)

    # -------------------------------------------------------------------------
    def get_old_result(self, cfg_file):
        """Method to get the preferences and other configuration from the
           specified .cfg file and apply the values to the associated
           properties. This includes the axes and title configurations,
           which are not applied in other cases. But it excludes the USB
           and Arduino configurations.
        """
        if DEBUG_CONFIG:
            dbg_str = ("get_old_result: Reading config "
                       "from {}".format(cfg_file))
            self.ivs2.logger.print_and_log(dbg_str)
        with open(cfg_file, "r") as cfg_fp:
            # Blow away old config and create new one
            self.cfg = ConfigParser.SafeConfigParser()
            # Read values from file
            self.cfg.readfp(cfg_fp)
            # Apply selected values to properties
            self.apply_general()
            self.apply_calibration()
            self.apply_plotting()
            self.apply_axes()
            self.apply_title()
        if DEBUG_CONFIG:
            self.cfg_dump("at exit of get_old_result")

    # -------------------------------------------------------------------------
    def merge_old_with_current_plotting(self, cfg_file):
        """Method to read a config file from an existing run into the current
           config, but discard its Plotting section values and replace
           them with the values in the config at the time the method is
           called. The associated properties are all updated based on
           the merged config.
        """
        # Capture Plotting options from current config
        section = "Plotting"
        x_pixels = self.cfg.get("General", "x pixels")
        plot_power = self.cfg.get(section, "plot power")
        fancy_labels = self.cfg.get(section, "fancy labels")
        linear = self.cfg.get(section, "linear")
        font_scale = self.cfg.get(section, "font scale")
        line_scale = self.cfg.get(section, "line scale")
        point_scale = self.cfg.get(section, "point scale")
        correct_adc = self.cfg.get(section, "correct adc")
        fix_isc = self.cfg.get(section, "fix isc")
        fix_voc = self.cfg.get(section, "fix voc")
        comb_dupv_pts = self.cfg.get(section, "combine dupv points")
        reduce_noise = self.cfg.get(section, "reduce noise")
        fix_overshoot = self.cfg.get(section, "fix overshoot")
        # Note that battery bias is -not- included, so a batch update
        # that includes a mix of runs with and without a bias battery
        # won't get messed up

        # Read the old result's saved config
        self.get_old_result(cfg_file)

        # Overwrite the Plotting options with the captured values
        section = "Plotting"
        self.cfg_set("General", "x pixels", x_pixels)
        self.cfg_set(section, "plot power", plot_power)
        self.cfg_set(section, "fancy labels", fancy_labels)
        self.cfg_set(section, "linear", linear)
        self.cfg_set(section, "font scale", font_scale)
        self.cfg_set(section, "line scale", line_scale)
        self.cfg_set(section, "point scale", point_scale)
        self.cfg_set(section, "correct adc", correct_adc)
        self.cfg_set(section, "fix isc", fix_isc)
        self.cfg_set(section, "fix voc", fix_voc)
        self.cfg_set(section, "combine dupv points", comb_dupv_pts)
        self.cfg_set(section, "reduce noise", reduce_noise)
        self.cfg_set(section, "fix overshoot", fix_overshoot)

        # Apply plotting options to properties
        self.apply_plotting()

    # -------------------------------------------------------------------------
    def get_saved_title(self, cfg_file):
        """Method to get the title configuration from the specified .cfg file
        """
        my_cfg = ConfigParser.SafeConfigParser()
        with open(cfg_file, "r") as cfg_fp:
            # Read values from file
            my_cfg.readfp(cfg_fp)
            try:
                # Get title config
                title = my_cfg.get("Plotting", "title")
            except ConfigParser.NoOptionError:
                title = None
        return title

    # -------------------------------------------------------------------------
    def apply_one(self, section, option, config_type, old_prop_val):
        """Method to apply an option read from the .cfg file to the
           associated object property. The value returned is the new (or
           perhaps old) property value. If the option is not found in
           the .cfg file, the old value is added to the config and the
           old value is returned to the caller. Also, if the option is
           found in the .cfg file, but it is not of the correct type,
           then the old value is added to the config.
        """
        full_name = "{} {}".format(section, option)
        try:
            if config_type == CFG_FLOAT:
                cfg_value = self.cfg.getfloat(section, option)
                return float(cfg_value)
            elif config_type == CFG_INT:
                cfg_value = self.cfg.getint(section, option)
                return int(cfg_value)
            elif config_type == CFG_BOOLEAN:
                cfg_value = self.cfg.getboolean(section, option)
                return bool(cfg_value)
            elif config_type == CFG_STRING:
                cfg_value = self.cfg.get(section, option)
                if cfg_value == "None":
                    cfg_value = None
                return cfg_value
            else:
                return old_prop_val
        except ConfigParser.NoOptionError:
            err_str = "{} not found in cfg file".format(full_name)
            self.ivs2.logger.print_and_log(err_str)
            self.cfg_set(section, option, old_prop_val)
            return old_prop_val
        except ValueError:
            err_str = "{} invalid in cfg file".format(full_name)
            self.ivs2.logger.print_and_log(err_str)
            self.cfg_set(section, option, old_prop_val)
            return old_prop_val

    # -------------------------------------------------------------------------
    def apply_all(self):
        """Method to apply the config read from the .cfg file to the
           associated object properties for all sections and options
        """
        # General section
        self.apply_general()

        # USB section
        self.apply_usb()

        # Calibration section
        self.apply_calibration()

        # Plotting section
        self.apply_plotting()

        # Arduino section
        self.apply_arduino()

    # -------------------------------------------------------------------------
    def apply_general(self):
        """Method to apply the General section options read from the
           .cfg file to the associated object properties
        """
        section = "General"

        # X pixels
        args = (section, "x pixels", CFG_INT, self.ivs2.x_pixels)
        self.ivs2.x_pixels = self.apply_one(*args)

    # -------------------------------------------------------------------------
    def apply_usb(self):
        """Method to apply the USB section options read from the .cfg
           file to the associated object properties
        """
        section = "USB"

        # Port
        option = "port"
        full_name = "{} {}".format(section, option)
        try:
            cfg_value = self.cfg.get(section, option)
        except ConfigParser.NoOptionError:
            err_str = "{} not found in cfg file".format(full_name)
            self.ivs2.logger.print_and_log(err_str)
            self.ivs2.find_arduino_port()
            self.cfg_set(section, option, self.ivs2.usb_port)
        else:
            port_attached = False
            for serial_port in self.ivs2.serial_ports:
                if cfg_value in str(serial_port):
                    port_attached = True
                    break
            if port_attached:
                self.ivs2.usb_port = cfg_value
            else:
                if cfg_value != "None":
                    err_str = "{} in cfg file not attached".format(full_name)
                    self.ivs2.logger.print_and_log(err_str)
                self.ivs2.find_arduino_port()
                self.cfg_set(section, option, self.ivs2.usb_port)
        # Baud
        args = (section, "baud", CFG_INT, self.ivs2.usb_baud)
        self.ivs2.usb_baud = self.apply_one(*args)

    # -------------------------------------------------------------------------
    def apply_calibration(self):
        """Method to apply the Calibration section options read from the
           .cfg file to the associated object properties
        """
        section = "Calibration"

        # Voltage
        args = (section, "voltage", CFG_FLOAT, self.ivs2.v_cal)
        self.ivs2.v_cal = self.apply_one(*args)

        # Current
        args = (section, "current", CFG_FLOAT, self.ivs2.i_cal)
        self.ivs2.i_cal = self.apply_one(*args)

        # NOTE: The "old" values in the args values are used when the
        # .cfg file is missing values for a particular config
        # type. Since the resistors were not originally included in the
        # config, they will be missing in the .cfg files of older
        # runs. Instead of using the current values of their associated
        # properties, we use the default values. In the case of R1,
        # however, there was a bug in the code when the older runs were
        # generated, so we need to use that older (bad) value. This
        # should prevent unexpected changes in the old graphs when they
        # are updated (for example to plot power).

        # Resistor R1
        args = (section, "r1 ohms", CFG_FLOAT, R1_DEFAULT_BUG)
        self.ivs2.vdiv_r1 = self.apply_one(*args)

        # Resistor R2
        args = (section, "r2 ohms", CFG_FLOAT, R2_DEFAULT)
        self.ivs2.vdiv_r2 = self.apply_one(*args)

        # Resistor Rf
        args = (section, "rf ohms", CFG_FLOAT, RF_DEFAULT)
        self.ivs2.amm_op_amp_rf = self.apply_one(*args)

        # Resistor Rg
        args = (section, "rg ohms", CFG_FLOAT, RG_DEFAULT)
        self.ivs2.amm_op_amp_rg = self.apply_one(*args)

        # Shunt resistor
        #
        # For "legacy" reasons, the shunt resistor is specified by two values:
        # max volts and max amps.  It's resistance is max_volts/max_amps.  The
        # max_amps value is hardcoded to 10A, so we just keep the value of
        # max_volts in the config.
        args = (section, "shunt max volts", CFG_FLOAT,
                (self.ivs2.amm_shunt_max_amps *
                 (SHUNT_DEFAULT / 1000000.0)))
        self.ivs2.amm_shunt_max_volts = self.apply_one(*args)

    # -------------------------------------------------------------------------
    def apply_plotting(self):
        """Method to apply the Plotting section options read from the
           .cfg file to the associated object properties
        """
        section = "Plotting"

        # Plot power
        args = (section, "plot power", CFG_BOOLEAN, self.ivs2.plot_power)
        self.ivs2.plot_power = self.apply_one(*args)

        # Fancy labels
        args = (section, "fancy labels", CFG_BOOLEAN, self.ivs2.fancy_labels)
        self.ivs2.fancy_labels = self.apply_one(*args)

        # Interpolation
        args = (section, "linear", CFG_BOOLEAN, self.ivs2.linear)
        self.ivs2.linear = self.apply_one(*args)

        # Font scale
        args = (section, "font scale", CFG_FLOAT, self.ivs2.font_scale)
        self.ivs2.font_scale = self.apply_one(*args)

        # Line scale
        args = (section, "line scale", CFG_FLOAT, self.ivs2.line_scale)
        self.ivs2.line_scale = self.apply_one(*args)

        # Point scale
        args = (section, "point scale", CFG_FLOAT, self.ivs2.point_scale)
        self.ivs2.point_scale = self.apply_one(*args)

        # ADC correction
        args = (section, "correct adc", CFG_BOOLEAN, self.ivs2.correct_adc)
        self.ivs2.correct_adc = self.apply_one(*args)

        # Fix Isc
        args = (section, "fix isc", CFG_BOOLEAN, self.ivs2.fix_isc)
        self.ivs2.fix_isc = self.apply_one(*args)

        # Fix Voc
        args = (section, "fix voc", CFG_BOOLEAN, self.ivs2.fix_voc)
        self.ivs2.fix_voc = self.apply_one(*args)

        # Combine =V points
        args = (section, "combine dupv points", CFG_BOOLEAN,
                self.ivs2.comb_dupv_pts)
        self.ivs2.comb_dupv_pts = self.apply_one(*args)

        # Noise reduction
        args = (section, "reduce noise", CFG_BOOLEAN, self.ivs2.reduce_noise)
        self.ivs2.reduce_noise = self.apply_one(*args)

        # Fix overshoot
        args = (section, "fix overshoot", CFG_BOOLEAN,
                self.ivs2.fix_overshoot)
        self.ivs2.fix_overshoot = self.apply_one(*args)

        # Battery bias
        args = (section, "battery bias", CFG_BOOLEAN, self.ivs2.battery_bias)
        self.ivs2.battery_bias = self.apply_one(*args)

    # -------------------------------------------------------------------------
    def apply_axes(self):
        """Method to apply the Plotting section "plot max x" and "plot max y"
           options read from the .cfg file to the associated object
           properties
        """
        section = "Plotting"

        # Max x
        args = (section, "plot max x", CFG_FLOAT, self.ivs2.plot_max_x)
        self.ivs2.plot_max_x = self.apply_one(*args)

        # Max y
        args = (section, "plot max y", CFG_FLOAT, self.ivs2.plot_max_y)
        self.ivs2.plot_max_y = self.apply_one(*args)

        # Set the axis lock property so the values are used when the
        # plot is generated
        self.ivs2.plot_lock_axis_ranges = True

    # -------------------------------------------------------------------------
    def apply_title(self):
        """Method to apply the Plotting section "title" option read from the
           .cfg file to the associated object property
        """
        section = "Plotting"
        args = (section, "title", CFG_STRING, self.ivs2.plot_title)
        self.ivs2.plot_title = self.apply_one(*args)

    # -------------------------------------------------------------------------
    def apply_arduino(self):
        """Method to apply the Arduino section options read from the
           .cfg file to the associated object properties
        """
        section = "Arduino"

        # SPI clock divider
        args = (section, "spi clock div", CFG_INT, self.ivs2.spi_clk_div)
        self.ivs2.spi_clk_div = self.apply_one(*args)

        # Max IV points
        args = (section, "max iv points", CFG_INT, self.ivs2.max_iv_points)
        self.ivs2.max_iv_points = self.apply_one(*args)

        # Min Isc ADC
        args = (section, "min isc adc", CFG_INT, self.ivs2.min_isc_adc)
        self.ivs2.min_isc_adc = self.apply_one(*args)

        # Max Isc poll
        args = (section, "max isc poll", CFG_INT, self.ivs2.max_isc_poll)
        self.ivs2.max_isc_poll = self.apply_one(*args)

        # Isc stable ADC
        args = (section, "isc stable adc", CFG_INT, self.ivs2.isc_stable_adc)
        self.ivs2.isc_stable_adc = self.apply_one(*args)

        # Max discards
        args = (section, "max discards", CFG_INT, self.ivs2.max_discards)
        self.ivs2.max_discards = self.apply_one(*args)

        # Aspect height
        args = (section, "aspect height", CFG_INT, self.ivs2.aspect_height)
        self.ivs2.aspect_height = self.apply_one(*args)

        # Aspect width
        args = (section, "aspect width", CFG_INT, self.ivs2.aspect_width)
        self.ivs2.aspect_width = self.apply_one(*args)

    # -------------------------------------------------------------------------
    def save(self, copy_dir=None):
        """Method to save preferences and other configuration to the
           .cfg file
        """
        if DEBUG_CONFIG:
            dbg_str = "save: Writing config to {}".format(self.cfg_filename)
            self.ivs2.logger.print_and_log(dbg_str)
            self.cfg_dump()
        # Attempt to open the file for writing
        try:
            with open(self.cfg_filename, "wb") as cfg_fp:
                # Write config to file
                self.cfg.write(cfg_fp)
        except IOError:
            # Failed to open file for writing
            err_str = "Couldn't open config file for writing"
            self.ivs2.logger.print_and_log(err_str)
            return

        # Copy the file to the specified directory (if any, and if it is
        # actually a directory)
        if copy_dir is not None and os.path.isdir(copy_dir):
            self.copy_file(copy_dir)

    # -------------------------------------------------------------------------
    def save_snapshot(self):
        """Method to save preferences and other configuration to the
           .cfg file from the snapshot copy
        """
        if DEBUG_CONFIG:
            dbg_str = ("save_snapshot: Writing snapshot config "
                       "to {}".format(self.cfg_filename))
            self.ivs2.logger.print_and_log(dbg_str)
        # Attempt to open the file for writing
        try:
            with open(self.cfg_filename, "wb") as cfg_fp:
                self.cfg_snapshot.write(cfg_fp)
        except IOError:
            # Failed to open file for writing
            err_str = "Couldn't open config file for writing"
            self.ivs2.logger.print_and_log(err_str)

    # -------------------------------------------------------------------------
    def copy_file(self, dir):
        """Method to copy the current .cfg file to the specified directory
        """
        if os.path.dirname(self.cfg_filename) == dir:
            # Return without doing anything if the property is already
            # pointing to the specified directory
            return
        if DEBUG_CONFIG:
            dbg_str = ("copy_file: Copying config from {}"
                       " to {}".format(self.cfg_filename, dir))
            self.ivs2.logger.print_and_log(dbg_str)
        try:
            shutil.copy(self.cfg_filename, dir)
        except shutil.Error as e:
            err_str = "Couldn't copy config file to {} ({})".format(dir, e)
            self.ivs2.logger.print_and_log(err_str)

    # -------------------------------------------------------------------------
    def populate(self):
        """Method to populate the ConfigParser object from the current
           property values
        """
        # Start with a fresh ConfigParser object
        self.cfg = ConfigParser.SafeConfigParser()

        # General config
        section = "General"
        self.cfg.add_section(section)
        self.cfg_set(section, "x pixels", self.ivs2.x_pixels)

        # USB port config
        section = "USB"
        self.cfg.add_section(section)
        self.cfg_set(section, "port", self.ivs2.usb_port)
        self.cfg_set(section, "baud", self.ivs2.usb_baud)

        # Calibration
        section = "Calibration"
        self.cfg.add_section(section)
        self.cfg_set(section, "voltage", self.ivs2.v_cal)
        self.cfg_set(section, "current", self.ivs2.i_cal)
        self.cfg_set(section, "r1 ohms", self.ivs2.vdiv_r1)
        self.cfg_set(section, "r2 ohms", self.ivs2.vdiv_r2)
        self.cfg_set(section, "rf ohms", self.ivs2.amm_op_amp_rf)
        self.cfg_set(section, "rg ohms", self.ivs2.amm_op_amp_rg)
        self.cfg_set(section, "shunt max volts",
                     self.ivs2.amm_shunt_max_volts)

        # Plotting config
        section = "Plotting"
        self.cfg.add_section(section)
        self.cfg_set(section, "plot power", self.ivs2.plot_power)
        self.cfg_set(section, "fancy labels", self.ivs2.fancy_labels)
        self.cfg_set(section, "linear", self.ivs2.linear)
        self.cfg_set(section, "font scale", self.ivs2.font_scale)
        self.cfg_set(section, "line scale", self.ivs2.line_scale)
        self.cfg_set(section, "point scale", self.ivs2.point_scale)
        self.cfg_set(section, "correct adc", self.ivs2.correct_adc)
        self.cfg_set(section, "fix isc", self.ivs2.fix_isc)
        self.cfg_set(section, "fix voc", self.ivs2.fix_voc)
        self.cfg_set(section, "combine dupv points", self.ivs2.comb_dupv_pts)
        self.cfg_set(section, "reduce noise", self.ivs2.reduce_noise)
        self.cfg_set(section, "fix overshoot", self.ivs2.fix_overshoot)
        self.cfg_set(section, "battery bias", self.ivs2.battery_bias)

        # Arduino config
        section = "Arduino"
        self.cfg.add_section(section)
        self.cfg_set(section, "spi clock div", self.ivs2.spi_clk_div)
        self.cfg_set(section, "max iv points", self.ivs2.max_iv_points)
        self.cfg_set(section, "min isc adc", self.ivs2.min_isc_adc)
        self.cfg_set(section, "max isc poll", self.ivs2.max_isc_poll)
        self.cfg_set(section, "isc stable adc", self.ivs2.isc_stable_adc)
        self.cfg_set(section, "max discards", self.ivs2.max_discards)
        self.cfg_set(section, "aspect height", self.ivs2.aspect_height)
        self.cfg_set(section, "aspect width", self.ivs2.aspect_width)

    # -------------------------------------------------------------------------
    def add_axes_and_title(self):
        self.cfg_set("Plotting", "plot max x", self.ivs2.plot_max_x)
        self.cfg_set("Plotting", "plot max y", self.ivs2.plot_max_y)
        self.cfg_set("Plotting", "title", self.ivs2.plot_title)

    # -------------------------------------------------------------------------
    def remove_axes_and_title(self):
        if not self.ivs2.plot_lock_axis_ranges:
            if (self.cfg.has_option("Plotting", "plot max x")):
                self.cfg.remove_option("Plotting", "plot max x")
                self.ivs2.plot_max_x = None
            if (self.cfg.has_option("Plotting", "plot max y")):
                self.cfg.remove_option("Plotting", "plot max y")
                self.ivs2.plot_max_y = None
        if (self.cfg.has_option("Plotting", "title")):
            self.cfg.remove_option("Plotting", "title")
            self.ivs2.plot_title = None


# The (extended) PrintAndLog class
#
class PrintAndLog(IV_Swinger.PrintAndLog):
    """Provides printing and logging methods (extended from IV_Swinger)"""

    # -------------------------------------------------------------------------
    def terminate_log(self):
        """Add newline to end of log file"""

        with open(IV_Swinger.PrintAndLog.log_file_name, "a") as f:
            f.write("\n")


# IV Swinger2 plotter class
#
class IV_Swinger2_plotter(IV_Swinger_plotter.IV_Swinger_plotter):
    """IV Swinger 2 plotter class (extended from IV_Swinger_plotter)"""

    def __init__(self):
        self.csv_proc = None
        IV_Swinger_plotter.IV_Swinger_plotter.__init__(self)
        self._csv_files = None
        self._plot_dir = None
        self._args = None
        self._current_img = None
        self._x_pixels = None
        self._generate_pdf = True
        self._curve_names = None
        self._title = None
        self._fancy_labels = True
        self._label_all_iscs = False
        self._label_all_mpps = False
        self._mpp_watts_only = False
        self._label_all_vocs = False
        self._linear = True
        self._overlay = False
        self._plot_power = True
        self._font_scale = 1.0
        self._line_scale = 1.0
        self._point_scale = 1.0
        self._v_sat = None
        self._i_sat = None
        self._logger = None
        self._ivsp_ivse = None

    # ---------------------------------
    @property
    def csv_files(self):
        """List of CSV files
        """
        return self._csv_files

    @csv_files.setter
    def csv_files(self, value):
        self._csv_files = value

    # ---------------------------------
    @property
    def plot_dir(self):
        """Directory use for plotting
        """
        return self._plot_dir

    @plot_dir.setter
    def plot_dir(self, value):
        self._plot_dir = value

    # ---------------------------------
    @property
    def args(self):
        """The argparse.Namespace() object used to specify options to
           the plotter
        """
        return self._args

    @args.setter
    def args(self, value):
        self._args = value

    # ---------------------------------
    @property
    def current_img(self):
        """File name of the current GIF
        """
        return self._current_img

    @current_img.setter
    def current_img(self, value):
        self._current_img = value

    # ---------------------------------
    @property
    def x_pixels(self):
        """Width in pixels of the GIFs
        """
        return self._x_pixels

    @x_pixels.setter
    def x_pixels(self, value):
        self._x_pixels = value

    # ---------------------------------
    @property
    def generate_pdf(self):
        """Value of the generate PDF flag
        """
        return self._generate_pdf

    @generate_pdf.setter
    def generate_pdf(self, value):
        if value not in set([True, False]):
            raise ValueError("generate_pdf must be boolean")
        self._generate_pdf = value

    # ---------------------------------
    @property
    def curve_names(self):
        """Value of the curve names list
        """
        return self._curve_names

    @curve_names.setter
    def curve_names(self, value):
        self._curve_names = value

    # ---------------------------------
    @property
    def title(self):
        """Value of the plot title
        """
        return self._title

    @title.setter
    def title(self, value):
        self._title = value

    # ---------------------------------
    @property
    def fancy_labels(self):
        """Value of the fancy labels flag
        """
        return self._fancy_labels

    @fancy_labels.setter
    def fancy_labels(self, value):
        if value not in set([True, False]):
            raise ValueError("fancy_labels must be boolean")
        self._fancy_labels = value

    # ---------------------------------
    @property
    def label_all_iscs(self):
        """Value of the label all Iscs flag
        """
        return self._label_all_iscs

    @label_all_iscs.setter
    def label_all_iscs(self, value):
        if value not in set([True, False]):
            raise ValueError("label_all_iscs must be boolean")
        self._label_all_iscs = value

    # ---------------------------------
    @property
    def label_all_mpps(self):
        """Value of the label all Mpps flag
        """
        return self._label_all_mpps

    @label_all_mpps.setter
    def label_all_mpps(self, value):
        if value not in set([True, False]):
            raise ValueError("label_all_mpps must be boolean")
        self._label_all_mpps = value

    # ---------------------------------
    @property
    def mpp_watts_only(self):
        """Value of the MPP watts only flag
        """
        return self._mpp_watts_only

    @mpp_watts_only.setter
    def mpp_watts_only(self, value):
        if value not in set([True, False]):
            raise ValueError("mpp_watts_only must be boolean")
        self._mpp_watts_only = value

    # ---------------------------------
    @property
    def label_all_vocs(self):
        """Value of the label all Vocs flag
        """
        return self._label_all_vocs

    @label_all_vocs.setter
    def label_all_vocs(self, value):
        if value not in set([True, False]):
            raise ValueError("label_all_vocs must be boolean")
        self._label_all_vocs = value

    # ---------------------------------
    @property
    def linear(self):
        """Value of the linear flag
        """
        return self._linear

    @linear.setter
    def linear(self, value):
        if value not in set([True, False]):
            raise ValueError("linear must be boolean")
        self._linear = value

    # ---------------------------------
    @property
    def overlay(self):
        """Value of the overlay flag
        """
        return self._overlay

    @overlay.setter
    def overlay(self, value):
        if value not in set([True, False]):
            raise ValueError("overlay must be boolean")
        self._overlay = value

    # ---------------------------------
    @property
    def plot_power(self):
        """Value of the plot power flag
        """
        return self._plot_power

    @plot_power.setter
    def plot_power(self, value):
        if value not in set([True, False]):
            raise ValueError("plot_power must be boolean")
        self._plot_power = value

    # ---------------------------------
    @property
    def font_scale(self):
        """Value of the font scale
        """
        return self._font_scale

    @font_scale.setter
    def font_scale(self, value):
        self._font_scale = value

    # ---------------------------------
    @property
    def line_scale(self):
        """Value of the line scale
        """
        return self._line_scale

    @line_scale.setter
    def line_scale(self, value):
        self._line_scale = value

    # ---------------------------------
    @property
    def point_scale(self):
        """Value of the point scale
        """
        return self._point_scale

    @point_scale.setter
    def point_scale(self, value):
        self._point_scale = value

    # ---------------------------------
    @property
    def v_sat(self):
        """Value of the saturation voltage
        """
        return self._v_sat

    @v_sat.setter
    def v_sat(self, value):
        self._v_sat = value

    # ---------------------------------
    @property
    def i_sat(self):
        """Value of the saturation current
        """
        return self._i_sat

    @i_sat.setter
    def i_sat(self, value):
        self._i_sat = value

    # ---------------------------------
    @property
    def logger(self):
        """Logger object"""
        return self._logger

    @logger.setter
    def logger(self, value):
        self._logger = value

    # ---------------------------------
    @property
    def ivsp_ivse(self):
        """IV Swinger object (as extended in IV_Swinger_plotter)"""
        return self._ivsp_ivse

    @ivsp_ivse.setter
    def ivsp_ivse(self, value):
        self._ivsp_ivse = value

    # -------------------------------------------------------------------------
    def set_default_args(self):
        """Method to set argparse args to default values"""

        self.args.name = self.curve_names
        self.args.overlay_name = ("overlaid_{}"
                                  .format(os.path.basename(self.plot_dir)))
        self.args.title = self.title
        self.args.fancy_labels = self.fancy_labels
        self.args.interactive = False
        self.args.label_all_iscs = self.label_all_iscs
        self.args.label_all_mpps = self.label_all_mpps
        self.args.mpp_watts_only = self.mpp_watts_only
        self.args.label_all_vocs = self.label_all_vocs
        self.args.linear = self.linear
        self.args.overlay = self.overlay
        self.args.plot_power = self.plot_power
        self.args.recalc_isc = False
        self.args.use_gnuplot = False
        self.args.gif = False
        self.args.png = False
        self.args.scale = 1.0
        self.args.font_scale = self.font_scale
        self.args.line_scale = self.line_scale
        self.args.point_scale = self.point_scale
        self.args.plot_scale = 1.0
        self.args.plot_x_scale = 1.0
        self.args.plot_y_scale = 1.0
        self.args.max_x = self.max_x
        self.args.max_y = self.max_y

    # -------------------------------------------------------------------------
    def plot_graphs_to_pdf(self, ivs, csvp):
        """Method to plot the graphs to a PDF"""

        self.args.gif = False
        self.args.png = False
        self.set_ivs_properties(self.args, ivs)
        ivs.plot_graphs(self.args, csvp)

    # -------------------------------------------------------------------------
    def plot_graphs_to_gif(self, ivs, csvp):
        """Method to plot the graphs to a GIF"""

        # Pyplot cannot generate GIFs on Windows, so we generate a PNG
        # and then convert it to GIF with PIL (regardless of platform).
        #
        # Before calling the plot_graphs() method, we have to adjust the
        # scale parameters and the DPI value based on the value of the
        # x_pixels property. The x_pixels property can be changed from a
        # combobox in the GUI.
        self.args.png = True
        self.set_ivs_properties(self.args, ivs)
        default_dpi = 100.0
        default_x_pixels = 1100.0
        ivs.plot_dpi = default_dpi * (self.x_pixels/default_x_pixels)
        ivs.plot_graphs(self.args, csvp)
        png_file = ivs.plt_img_filename
        (file, ext) = os.path.splitext(png_file)
        gif_file = "{}.gif".format(file)
        im = Image.open(png_file)
        im.save(gif_file)
        self.current_img = gif_file

    # -------------------------------------------------------------------------
    def run(self):
        """Main method to run the IV Swinger 2 plotter"""

        # The plotter uses the argparse library for command line
        # argument parsing. Here we just need to "manually" create an
        # argparse.Namespace() object and populate it.
        self.args = argparse.Namespace()
        self.set_default_args()

        # Change to plot directory so files will be created there
        os.chdir(self.plot_dir)

        # Create IV Swinger object (as extended in IV_Swinger_plotter)
        self.ivsp_ivse = IV_Swinger_plotter.IV_Swinger_extended()
        self.set_ivs_properties(self.args, self.ivsp_ivse)
        self.ivsp_ivse.logger = self.logger
        self.ivsp_ivse.v_sat = self.v_sat
        self.ivsp_ivse.i_sat = self.i_sat

        # Process all CSV files
        self.csv_proc = IV_Swinger_plotter.CsvFileProcessor(self.args,
                                                            self.csv_files,
                                                            self.ivsp_ivse,
                                                            logger=self.logger)
        # Plot graphs to PDF
        if self.generate_pdf:
            self.plot_graphs_to_pdf(self.ivsp_ivse, self.csv_proc)

        # Plot graphs to GIF
        self.plot_graphs_to_gif(self.ivsp_ivse, self.csv_proc)

        # Capture max_x and max_y for locking feature
        self.max_x = self.ivsp_ivse.plot_max_x
        self.max_y = self.ivsp_ivse.plot_max_y


#  Main IV Swinger 2 class
#
class IV_Swinger2(IV_Swinger.IV_Swinger):
    """IV_Swinger derived class extended for IV Swinger 2
    """
    # Initializer
    def __init__(self, app_data_dir=None):
        IV_Swinger.IV_Swinger.__init__(self)
        self.lcd = None
        self.ivp = None
        self.prev_date_time_str = None
        # Property variables
        self._app_data_dir = app_data_dir
        self._hdd_output_dir = None
        self._file_prefix = "iv_swinger2_"
        self._serial_ports = []
        self._usb_port = None
        self._usb_baud = 57600
        self._serial_timeout = 0.1
        self._ser = None
        self._sio = None
        self._arduino_ready = False
        self._data_points = []
        self._unfiltered_adc_pairs = []
        self._adc_pairs = []
        self._adc_pairs_corrected = []
        self._adc_ch0_offset = 0
        self._adc_ch1_offset = 0
        self._voltage_saturated = False
        self._current_saturated = False
        self._adc_range = 4096.0
        self._msg_timer_timeout = 50
        # Note: following six override base class variables
        self._vdiv_r1 = R1_DEFAULT
        self._vdiv_r2 = R2_DEFAULT
        self._amm_op_amp_rf = RF_DEFAULT
        self._amm_op_amp_rg = RG_DEFAULT
        self._adc_vref = 5.0             # ADC voltage reference = 5V
        self._amm_shunt_max_amps = 10.0  # Legacy - hardcoded
        self._amm_shunt_max_volts = (self._amm_shunt_max_amps *
                                     (SHUNT_DEFAULT / 1000000.0))
        self._v_cal = V_CAL_DEFAULT
        self._i_cal = I_CAL_DEFAULT
        self._plot_title = None
        self._current_img = None
        self._x_pixels = 770  # Default GIF width (770x595)
        self._plot_lock_axis_ranges = False
        self._generate_pdf = True
        self._fancy_labels = True
        self._linear = True
        self._plot_power = False
        self._font_scale = FONT_SCALE_DEFAULT
        self._line_scale = LINE_SCALE_DEFAULT
        self._point_scale = POINT_SCALE_DEFAULT
        self._correct_adc = True
        self._fix_isc = True
        self._fix_voc = True
        self._comb_dupv_pts = True
        self._reduce_noise = True
        self._fix_overshoot = True
        self._battery_bias = False
        self._arduino_ver_major = -1
        self._arduino_ver_minor = -1
        self._arduino_ver_patch = -1
        self._arduino_ver_opt_suffix = ""
        self._spi_clk_div = SPI_CLK_DEFAULT
        self._max_iv_points = MAX_IV_POINTS_DEFAULT
        self._min_isc_adc = MIN_ISC_ADC_DEFAULT
        self._max_isc_poll = MAX_ISC_POLL_DEFAULT
        self._isc_stable_adc = ISC_STABLE_DEFAULT
        self._max_discards = MAX_DISCARDS_DEFAULT
        self._aspect_height = ASPECT_HEIGHT_DEFAULT
        self._aspect_width = ASPECT_WIDTH_DEFAULT
        # Configure logging and find serial ports
        self.configure_logging()
        self.find_serial_ports()

    # Properties
    # ---------------------------------
    @property
    def data_points(self):
        """Property to get the data points"""
        return self._data_points

    @data_points.setter
    def data_points(self, value):
        self._data_points = value

    # ---------------------------------
    @property
    def unfiltered_adc_pairs(self):
        """Property to get the unfiltered ADC value pairs. These are only
           captured when using a debug Arduino sketch.
        """
        return self._unfiltered_adc_pairs

    @unfiltered_adc_pairs.setter
    def unfiltered_adc_pairs(self, value):
        self._unfiltered_adc_pairs = value

    # ---------------------------------
    @property
    def adc_pairs(self):
        """Property to get the ADC value pairs"""
        return self._adc_pairs

    @adc_pairs.setter
    def adc_pairs(self, value):
        self._adc_pairs = value

    # ---------------------------------
    @property
    def adc_pairs_corrected(self):
        """Property to get the corrected ADC value pairs"""
        return self._adc_pairs_corrected

    @adc_pairs_corrected.setter
    def adc_pairs_corrected(self, value):
        self._adc_pairs_corrected = value

    # ---------------------------------
    @property
    def adc_range(self):
        """Property to get the ADC range (i.e. 2^^#bits)"""
        return self._adc_range

    @adc_range.setter
    def adc_range(self, value):
        self._adc_range = value

    # ---------------------------------
    @property
    def msg_timer_timeout(self):
        """Property to get the message timer timeout"""
        return self._msg_timer_timeout

    @msg_timer_timeout.setter
    def msg_timer_timeout(self, value):
        self._msg_timer_timeout = value

    # ---------------------------------
    @property
    def adc_vref(self):
        """Property to get the ADC reference voltage"""
        return self._adc_vref

    @adc_vref.setter
    def adc_vref(self, value):
        self._adc_vref = value

    # ---------------------------------
    @property
    def v_cal(self):
        """Property to get the voltage calibration value"""
        return self._v_cal

    @v_cal.setter
    def v_cal(self, value):
        self._v_cal = value

    # ---------------------------------
    @property
    def i_cal(self):
        """Property to get the current calibration value"""
        return self._i_cal

    @i_cal.setter
    def i_cal(self, value):
        self._i_cal = value

    # ---------------------------------
    @property
    def app_data_dir(self):
        """Application data directory where results, log files, and
           preferences are written. Default is platform-dependent.  The
           default can be overridden by setting the property after
           instantiation.
        """
        if self._app_data_dir is None:
            if sys.platform == "darwin":
                # Mac
                self._app_data_dir = os.path.join(get_mac_dir(mac_app_sup_dir,
                                                              mac_domain_mask,
                                                              True)[0],
                                                  APP_NAME)
            elif sys.platform == "win32":
                # Windows
                self._app_data_dir = os.path.join(os.environ["APPDATA"],
                                                  APP_NAME)
            else:
                # Linux
                leaf_dir = ".{}".format(APP_NAME)
                self._app_data_dir = os.path.expanduser(os.path.join("~",
                                                                     leaf_dir))
        return self._app_data_dir

    @app_data_dir.setter
    def app_data_dir(self, value):
        if not os.path.isabs(value):
            raise ValueError("app_data_dir must be an absolute path")
        self._app_data_dir = value

    # ---------------------------------
    @property
    def root_dir(self):
        """Alias for app_data_dir used by legacy (parent) IV_Swinger class"""
        return self.app_data_dir

    # ---------------------------------
    @property
    def hdd_output_dir(self):
        """Directory (on HDD) where a given run's results are written"""
        return self._hdd_output_dir

    @hdd_output_dir.setter
    def hdd_output_dir(self, value):
        if not os.path.isabs(value):
            raise ValueError("hdd_output_dir must be an absolute path")
        self._hdd_output_dir = value

    # ---------------------------------
    @property
    def serial_ports(self):
        """List of serial ports found on this computer"""
        return self._serial_ports

    @serial_ports.setter
    def serial_ports(self, value):
        self._serial_ports = value

    # ---------------------------------
    @property
    def file_prefix(self):
        """Prefix for data point CSV, GIF, and PDF files"""
        return self._file_prefix

    @file_prefix.setter
    def file_prefix(self, value):
        self._file_prefix = value

    # ---------------------------------
    @property
    def logs_dir(self):
        """ Directory on where log files are written"""
        logs_dir = "{}/logs".format(self.app_data_dir)
        return logs_dir

    # ---------------------------------
    @property
    def usb_port(self):
        """Property to get the current USB port path"""
        return self._usb_port

    @usb_port.setter
    def usb_port(self, value):
        self._usb_port = value

    # ---------------------------------
    @property
    def usb_baud(self):
        """Property to get the current USB baud rate"""
        return self._usb_baud

    @usb_baud.setter
    def usb_baud(self, value):
        self._usb_baud = value

    # ---------------------------------
    @property
    def serial_timeout(self):
        """Property to get the current serial timeout value"""
        return self._serial_timeout

    @serial_timeout.setter
    def serial_timeout(self, value):
        self._serial_timeout = value

    # ---------------------------------
    @property
    def arduino_ready(self):
        """Property to get flag that indicates if the Arduino is ready
        """
        return self._arduino_ready

    @arduino_ready.setter
    def arduino_ready(self, value):
        if value not in set([True, False]):
            raise ValueError("arduino_ready must be boolean")
        self._arduino_ready = value

    # ---------------------------------
    @property
    def plot_title(self):
        """Title for the plot
        """
        return self._plot_title

    @plot_title.setter
    def plot_title(self, value):
        self._plot_title = value

    # ---------------------------------
    @property
    def current_img(self):
        """File name of the current GIF
        """
        return self._current_img

    @current_img.setter
    def current_img(self, value):
        self._current_img = value

    # ---------------------------------
    @property
    def x_pixels(self):
        """Width in pixels of the GIFs
        """
        return self._x_pixels

    @x_pixels.setter
    def x_pixels(self, value):
        self._x_pixels = value

    # ---------------------------------
    @property
    def plot_lock_axis_ranges(self):
        """Value of the axis lock flag
        """
        return self._plot_lock_axis_ranges

    @plot_lock_axis_ranges.setter
    def plot_lock_axis_ranges(self, value):
        if value not in set([True, False]):
            raise ValueError("plot_lock_axis_ranges must be boolean")
        self._plot_lock_axis_ranges = value

    # ---------------------------------
    @property
    def generate_pdf(self):
        """Value of the generate PDF flag
        """
        return self._generate_pdf

    @generate_pdf.setter
    def generate_pdf(self, value):
        if value not in set([True, False]):
            raise ValueError("generate_pdf must be boolean")
        self._generate_pdf = value

    # ---------------------------------
    @property
    def fancy_labels(self):
        """Value of the fancy labels flag
        """
        return self._fancy_labels

    @fancy_labels.setter
    def fancy_labels(self, value):
        if value not in set([True, False]):
            raise ValueError("fancy_labels must be boolean")
        self._fancy_labels = value

    # ---------------------------------
    @property
    def linear(self):
        """Value of the linear flag
        """
        return self._linear

    @linear.setter
    def linear(self, value):
        if value not in set([True, False]):
            raise ValueError("linear must be boolean")
        self._linear = value

    # ---------------------------------
    @property
    def plot_power(self):
        """Value of the plot power flag
        """
        return self._plot_power

    @plot_power.setter
    def plot_power(self, value):
        if value not in set([True, False]):
            raise ValueError("plot_power must be boolean")
        self._plot_power = value

    # ---------------------------------
    @property
    def font_scale(self):
        """Value of the font scale
        """
        return self._font_scale

    @font_scale.setter
    def font_scale(self, value):
        self._font_scale = value

    # ---------------------------------
    @property
    def line_scale(self):
        """Value of the line scale
        """
        return self._line_scale

    @line_scale.setter
    def line_scale(self, value):
        self._line_scale = value

    # ---------------------------------
    @property
    def point_scale(self):
        """Value of the point scale
        """
        return self._point_scale

    @point_scale.setter
    def point_scale(self, value):
        self._point_scale = value

    # ---------------------------------
    @property
    def correct_adc(self):
        """Value of the correct_adc flag
        """
        return self._correct_adc

    @correct_adc.setter
    def correct_adc(self, value):
        if value not in set([True, False]):
            raise ValueError("correct_adc must be boolean")
        self._correct_adc = value

    # ---------------------------------
    @property
    def fix_isc(self):
        """Value of the fix_isc flag
        """
        return self._fix_isc

    @fix_isc.setter
    def fix_isc(self, value):
        if value not in set([True, False]):
            raise ValueError("fix_isc must be boolean")
        self._fix_isc = value

    # ---------------------------------
    @property
    def fix_voc(self):
        """Value of the fix_voc flag
        """
        return self._fix_voc

    @fix_voc.setter
    def fix_voc(self, value):
        if value not in set([True, False]):
            raise ValueError("fix_voc must be boolean")
        self._fix_voc = value

    # ---------------------------------
    @property
    def comb_dupv_pts(self):
        """Value of the comb_dupv_pts flag
        """
        return self._comb_dupv_pts

    @comb_dupv_pts.setter
    def comb_dupv_pts(self, value):
        if value not in set([True, False]):
            raise ValueError("comb_dupv_pts must be boolean")
        self._comb_dupv_pts = value

    # ---------------------------------
    @property
    def reduce_noise(self):
        """Value of the reduce_noise flag
        """
        return self._reduce_noise

    @reduce_noise.setter
    def reduce_noise(self, value):
        if value not in set([True, False]):
            raise ValueError("reduce_noise must be boolean")
        self._reduce_noise = value

    # ---------------------------------
    @property
    def fix_overshoot(self):
        """Value of the fix_overshoot flag
        """
        return self._fix_overshoot

    @fix_overshoot.setter
    def fix_overshoot(self, value):
        if value not in set([True, False]):
            raise ValueError("fix_overshoot must be boolean")
        self._fix_overshoot = value

    # ---------------------------------
    @property
    def battery_bias(self):
        """Value of the battery_bias flag
        """
        return self._battery_bias

    @battery_bias.setter
    def battery_bias(self, value):
        if value not in set([True, False]):
            raise ValueError("battery_bias must be boolean")
        self._battery_bias = value

    # ---------------------------------
    @property
    def spi_clk_div(self):
        """Arduino: SPI bus clock divider value
        """
        return self._spi_clk_div

    @spi_clk_div.setter
    def spi_clk_div(self, value):
        self._spi_clk_div = value

    # ---------------------------------
    @property
    def max_iv_points(self):
        """Arduino: Max number of I/V pairs to capture
        """
        return self._max_iv_points

    @max_iv_points.setter
    def max_iv_points(self, value):
        self._max_iv_points = value

    # ---------------------------------
    @property
    def min_isc_adc(self):
        """Arduino: Minimum ADC count for Isc
        """
        return self._min_isc_adc

    @min_isc_adc.setter
    def min_isc_adc(self, value):
        self._min_isc_adc = value

    # ---------------------------------
    @property
    def max_isc_poll(self):
        """Arduino: Max loops to wait for Isc to stabilize
        """
        return self._max_isc_poll

    @max_isc_poll.setter
    def max_isc_poll(self, value):
        self._max_isc_poll = value

    # ---------------------------------
    @property
    def isc_stable_adc(self):
        """Arduino: Stable Isc changes less than this
        """
        return self._isc_stable_adc

    @isc_stable_adc.setter
    def isc_stable_adc(self, value):
        self._isc_stable_adc = value

    # ---------------------------------
    @property
    def max_discards(self):
        """Arduino: Maximum consecutive discarded points
        """
        return self._max_discards

    @max_discards.setter
    def max_discards(self, value):
        self._max_discards = value

    # ---------------------------------
    @property
    def aspect_height(self):
        """Arduino: Height of graph's aspect ratio (max 8)
        """
        return self._aspect_height

    @aspect_height.setter
    def aspect_height(self, value):
        self._aspect_height = value

    # ---------------------------------
    @property
    def aspect_width(self):
        """Arduino: Width of graph's aspect ratio (max 8)
        """
        return self._aspect_width

    @aspect_width.setter
    def aspect_width(self, value):
        self._aspect_width = value

    # Derived properties
    # ---------------------------------
    @property
    def adc_inc(self):
        """Volts per ADC increment"""
        adc_inc = self.adc_vref / self.adc_range
        return adc_inc

    # ---------------------------------
    @property
    def vdiv_ratio(self):
        """Voltage divider ratio"""
        vdiv_ratio = self.vdiv_r2 / (self.vdiv_r1 + self.vdiv_r2)
        return vdiv_ratio

    # ---------------------------------
    @property
    def v_mult(self):
        """Voltage multiplier"""
        v_mult = (self.adc_inc / self.vdiv_ratio) * self.v_cal
        return v_mult

    # ---------------------------------
    @property
    def i_mult(self):
        """Current multiplier"""
        i_mult = ((self.adc_inc /
                   self.amm_op_amp_gain /
                   self.amm_shunt_resistance) * self.i_cal)
        return i_mult

    # ---------------------------------
    @property
    def v_sat(self):
        """Saturation voltage"""
        v_sat = ADC_MAX * self.v_mult
        return v_sat

    # ---------------------------------
    @property
    def i_sat(self):
        """Saturation current"""
        i_sat = ADC_MAX * self.i_mult
        return i_sat

    # ---------------------------------
    @property
    def arduino_sketch_ver(self):
        """Arduino sketch version"""
        if self._arduino_ver_major > -1:
            ver_str = "{}.{}.{}{}".format(self._arduino_ver_major,
                                          self._arduino_ver_minor,
                                          self._arduino_ver_patch,
                                          self._arduino_ver_opt_suffix)
            return ver_str
        else:
            return "Unknown"

    # ---------------------------------
    @property
    def arduino_max_incoming_msg_len(self):
        """Maximum supported length of messages sent to Arduino
        """
        if self.arduino_sketch_ver_lt("1.1.0"):
            return 30
        else:
            return 35

    # ---------------------------------
    @property
    def arduino_sketch_supports_eeprom_config(self):
        """True for Arduino sketch versions that support saving config
           values in EEPROM.
        """
        return self.arduino_sketch_ver_ge("1.1.0")

    # ---------------------------------
    @property
    def pdf_filename(self):
        """PDF file name"""
        dts = extract_date_time_str(self.hdd_output_dir)
        pdf_filename = os.path.join(self.hdd_output_dir,
                                    "{}{}.pdf".format(self.file_prefix, dts))
        return pdf_filename

    # -------------------------------------------------------------------------
    def find_serial_ports(self):
        """Method to find the serial ports on this computer
        """

        # Get list of serial ports and put it in the serial_ports
        # property
        self.serial_ports = list(serial.tools.list_ports.comports())

    # -------------------------------------------------------------------------
    def find_arduino_port(self):
        """Method to identify the serial port connected to the Arduino
        """

        # If one of the serial ports has "uino" (Arduino, Genuino, etc.)
        # in the name, choose that one. Note that this will choose the
        # first one if more than one Arduino is connected.
        if self.usb_port is None:
            for serial_port in self.serial_ports:
                if ("uino" in str(serial_port) or
                        "Generic CDC" in str(serial_port)):  # Elegoo now
                    self.usb_port = str(serial_port).split(" ")[0]
                    break

    # -------------------------------------------------------------------------
    def reset_arduino(self):
        """Method to reset the Arduino and establish communication to it
           over USB
        """

        # Set up to talk to Arduino via USB (this resets the Arduino)
        if self._ser is not None and self._ser.is_open:
            # First close port if it is already open
            self._ser.close()
        try:
            self._ser = serial.Serial(self.usb_port, self.usb_baud,
                                      timeout=self.serial_timeout)
        except (serial.SerialException) as e:
            self.logger.print_and_log("ERROR: reset_arduino: ({})".format(e))
            return RC_SERIAL_EXCEPTION

        # Create buffered text stream
        self._sio = io.TextIOWrapper(io.BufferedRWPair(self._ser, self._ser),
                                     line_buffering=True)

        return RC_SUCCESS

    # -------------------------------------------------------------------------
    def wait_for_arduino_ready_and_ack(self, write_eeprom=False):
        """Method to wait for the Arduino ready message, and send
           acknowledgement
        """

        # Return immediately if ready flag is already set
        if self.arduino_ready:
            return RC_SUCCESS

        # Otherwise wait for ready message from Arduino
        rc = self.receive_msg_from_arduino()
        version_intro = "IV Swinger2 sketch version"
        if (rc == RC_SUCCESS and
                self.msg_from_arduino.startswith(version_intro)):
            rc = self.get_arduino_sketch_ver(self.msg_from_arduino)
            if rc != RC_SUCCESS:
                return rc
            rc = self.receive_msg_from_arduino()
        if rc == RC_SUCCESS and self.msg_from_arduino == unicode("Ready\n"):
            self.arduino_ready = True
        elif rc != RC_SUCCESS:
            return rc
        else:
            err_str = ("ERROR: Malformed Arduino ready message: {}"
                       .format(self.msg_from_arduino))
            self.logger.print_and_log(err_str)
            return RC_FAILURE

        # Send config message(s) to Arduino
        rc = self.send_config_msgs_to_arduino(write_eeprom)
        if rc != RC_SUCCESS:
            return rc

        # Request EEPROM values from Arduino
        self.eeprom_values_received = False
        rc = self.request_eeprom_dump()
        if rc != RC_SUCCESS:
            return rc

        # Special case: EEPROM has never been written (and therefore no values
        # are returned).  We want to write it with the current values rather
        # than waiting for a calibration.
        if (self.arduino_sketch_supports_eeprom_config and
                not self.eeprom_values_received):
            rc = self.send_config_msgs_to_arduino(write_eeprom=True)
            if rc != RC_SUCCESS:
                return rc
            rc = self.request_eeprom_dump()
            if rc != RC_SUCCESS:
                return rc

        # Send ready message to Arduino
        rc = self.send_msg_to_arduino("Ready")
        if rc != RC_SUCCESS:
            return rc

        return RC_SUCCESS

    # -------------------------------------------------------------------------
    def send_config_msgs_to_arduino(self, write_eeprom=False):
        """Method to send config messages to the Arduino, waiting for each
        reply"""
        config_dict = {"CLK_DIV": self.spi_clk_div,
                       "MAX_IV_POINTS": self.max_iv_points,
                       "MIN_ISC_ADC": self.min_isc_adc,
                       "MAX_ISC_POLL": self.max_isc_poll,
                       "ISC_STABLE_ADC": self.isc_stable_adc,
                       "MAX_DISCARDS": self.max_discards,
                       "ASPECT_HEIGHT": self.aspect_height,
                       "ASPECT_WIDTH": self.aspect_width}
        for config_type, config_value in config_dict.iteritems():
            rc = self.send_one_config_msg_to_arduino(config_type, config_value)
            if rc != RC_SUCCESS:
                return rc

        if write_eeprom and self.arduino_sketch_supports_eeprom_config:
            config_values = [("{} {}".format(EEPROM_VALID_ADDR,
                                             EEPROM_VALID_VALUE)),
                             ("{} {}".format(EEPROM_VALID_COUNT_ADDR,
                                             EEPROM_VALID_COUNT)),
                             ("{} {}".format(EEPROM_R1_OHMS_ADDR,
                                             int(self.vdiv_r1))),
                             ("{} {}".format(EEPROM_R2_OHMS_ADDR,
                                             int(self.vdiv_r2))),
                             ("{} {}".format(EEPROM_RF_OHMS_ADDR,
                                             int(self.amm_op_amp_rf))),
                             ("{} {}".format(EEPROM_RG_OHMS_ADDR,
                                             int(self.amm_op_amp_rg))),
                             ("{} {}".format(EEPROM_SHUNT_UOHMS_ADDR,
                                             int(self.amm_shunt_resistance *
                                                 1000000.0))),
                             ("{} {}".format(EEPROM_V_CAL_X1M_ADDR,
                                             int(self.v_cal * 1000000.0))),
                             ("{} {}".format(EEPROM_I_CAL_X1M_ADDR,
                                             int(self.i_cal * 1000000.0)))]
            for config_value in config_values:
                rc = self.send_one_config_msg_to_arduino("WRITE_EEPROM",
                                                         config_value)
                if rc != RC_SUCCESS:
                    return rc

        return RC_SUCCESS

    # -------------------------------------------------------------------------
    def send_one_config_msg_to_arduino(self, config_type, config_value):
        """Method to send one config message to the Arduino, waiting for the
        reply"""
        msg_str = "Config: {} {}".format(config_type, config_value)
        rc = self.send_msg_to_arduino(msg_str)
        if rc != RC_SUCCESS:
            return rc
        self.msg_from_arduino = "None"
        while self.msg_from_arduino != unicode("Config processed\n"):
            rc = self.receive_msg_from_arduino()
            if rc != RC_SUCCESS:
                return rc

        return RC_SUCCESS

    # -------------------------------------------------------------------------
    def send_msg_to_arduino(self, msg):
        """Method to send a message to the Arduino"""

        if len("{}\n".format(msg)) > self.arduino_max_incoming_msg_len:
            err_str = "ERROR: Message to Arduino is too long: {}".format(msg)
            self.logger.print_and_log(err_str)
            return RC_FAILURE

        try:
            self._sio.write(unicode("{}\n".format(msg)))
        except (serial.SerialException) as e:
            self.logger.print_and_log("send_msg_to_arduino: ({})".format(e))
            return RC_SERIAL_EXCEPTION

        return RC_SUCCESS

    # -------------------------------------------------------------------------
    def receive_msg_from_arduino(self):
        """Method to receive a single message from the Arduino"""

        msg_timer = self.msg_timer_timeout
        while msg_timer:
            try:
                self.msg_from_arduino = self._sio.readline()
            except (serial.SerialException) as e:
                err_str = "ERROR: receive_msg_from_arduino: ({})".format(e)
                self.logger.print_and_log(err_str)
                return RC_SERIAL_EXCEPTION
            except UnicodeDecodeError:
                err_str = "ERROR: Probable baud mismatch on USB"
                self.logger.print_and_log(err_str)
                return RC_BAUD_MISMATCH
            if len(self.msg_from_arduino) > 0:
                self.log_msg_from_arduino(self.msg_from_arduino)
                return RC_SUCCESS
            msg_timer -= 1

        self.msg_from_arduino = "NONE"
        err_str = "ERROR: Timeout waiting for message from Arduino"
        self.logger.print_and_log(err_str)
        return RC_TIMEOUT

    # -------------------------------------------------------------------------
    def receive_data_from_arduino(self):
        """Method to receive raw IV data from the Arduino"""

        received_msgs = []
        while True:
            # Loop receiving messages and appending them to the
            # received_msgs list until the "Output complete" message is
            # received
            rc = self.receive_msg_from_arduino()
            if rc == RC_SUCCESS:
                received_msgs.append(self.msg_from_arduino)
                if self.msg_from_arduino == unicode("Output complete\n"):
                    break
            else:
                return rc

        # Loop through list, filling the adc_pairs list with the CH0/CH1
        # pairs
        self.adc_pairs = []
        self.unfiltered_adc_pairs = []
        adc_re = re.compile("CH0:(\d+)\s+CH1:(\d+)")
        unfiltered_adc_re_str = "Unfiltered CH0:(\d+)\s+Unfiltered CH1:(\d+)"
        unfiltered_adc_re = re.compile(unfiltered_adc_re_str)
        for msg in received_msgs:
            if msg.startswith("Polling for stable Isc timed out"):
                rc = RC_ISC_TIMEOUT
            match = adc_re.search(msg)
            if match:
                ch0_adc = int(match.group(1))
                ch1_adc = int(match.group(2))
                self.adc_pairs.append((ch0_adc, ch1_adc))
            unfiltered_match = unfiltered_adc_re.search(msg)
            if unfiltered_match:
                ch0_adc = int(unfiltered_match.group(1))
                ch1_adc = int(unfiltered_match.group(2))
                self.unfiltered_adc_pairs.append((ch0_adc, ch1_adc))

        return rc

    # -------------------------------------------------------------------------
    def log_msg_from_arduino(self, msg):
        """Method to log a message from the Arduino"""
        log_msg = "Arduino: {}".format(msg.rstrip())
        self.logger.log(log_msg)

    # -------------------------------------------------------------------------
    def request_eeprom_dump(self):
        """Method to send a DUMP_EEPROM "config" message to the Arduino and
           capture the values returned
        """
        if not self.arduino_sketch_supports_eeprom_config:
            return RC_SUCCESS
        rc = self.send_msg_to_arduino("Config: DUMP_EEPROM ")
        if rc != RC_SUCCESS:
            return rc
        self.msg_from_arduino = "None"
        while self.msg_from_arduino != unicode("Config processed\n"):
            rc = self.receive_msg_from_arduino()
            if rc != RC_SUCCESS:
                return rc
            if self.msg_from_arduino.startswith("EEPROM addr"):
                rc = self.process_eeprom_value()
                self.eeprom_values_received = True
                if rc != RC_SUCCESS:
                    return rc

        return RC_SUCCESS

    # -------------------------------------------------------------------------
    def get_arduino_sketch_ver(self, msg):
        """Method to extract the version number of the Arduino sketch from the
           message containing it
        """
        sketch_ver_re = re.compile("sketch version (\d+)\.(\d+)\.(\d+)(\S*)")
        match = sketch_ver_re.search(msg)
        if match:
            self._arduino_ver_major = int(match.group(1))
            self._arduino_ver_minor = int(match.group(2))
            self._arduino_ver_patch = int(match.group(3))
            self._arduino_ver_opt_suffix = match.group(4)
        else:
            err_str = "ERROR: Bad Arduino version message: {}".format(msg)
            self.logger.print_and_log(err_str)
            return RC_FAILURE

        return RC_SUCCESS

    # -------------------------------------------------------------------------
    def compare_arduino_sketch_ver(self, test_version):
        """Method to compare the Arduino sketch version with the
           specified value. Returns:
              SKETCH_VER_LT: if sketch version is lower
              SKETCH_VER_EQ: if sketch version is equal
              SKETCH_VER_GT: if sketch version is greater
        """
        test_ver_re = re.compile("(\d+)\.(\d+)\.(\d+)")
        match = test_ver_re.search(test_version)
        if match:
            test_ver_major = int(match.group(1))
            test_ver_minor = int(match.group(2))
            test_ver_patch = int(match.group(3))
            if (self._arduino_ver_major < test_ver_major or
                (self._arduino_ver_major == test_ver_major and
                 self._arduino_ver_minor < test_ver_minor) or
                (self._arduino_ver_major == test_ver_major and
                 self._arduino_ver_minor == test_ver_minor and
                 self._arduino_ver_patch < test_ver_patch)):
                return SKETCH_VER_LT
            elif (self._arduino_ver_major == test_ver_major and
                  self._arduino_ver_minor == test_ver_minor and
                  self._arduino_ver_patch == test_ver_patch):
                return SKETCH_VER_EQ
            else:
                return SKETCH_VER_GT
        else:
            err_str = "ERROR: Bad test version: {}".format(test_version)
            self.logger.print_and_log(err_str)
            return SKETCH_VER_ERR

    # -------------------------------------------------------------------------
    def arduino_sketch_ver_lt(self, test_version):
        """Method to test whether the Arduino sketch version is less than the
           specified value
        """
        if self.compare_arduino_sketch_ver(test_version) == SKETCH_VER_LT:
            return True
        else:
            return False

    # -------------------------------------------------------------------------
    def arduino_sketch_ver_eq(self, test_version):
        """Method to test whether the Arduino sketch version is equal to the
           specified value
        """
        if self.compare_arduino_sketch_ver(test_version) == SKETCH_VER_EQ:
            return True
        else:
            return False

    # -------------------------------------------------------------------------
    def arduino_sketch_ver_gt(self, test_version):
        """Method to test whether the Arduino sketch version is greater than
           the specified value
        """
        if self.compare_arduino_sketch_ver(test_version) == SKETCH_VER_GT:
            return True
        else:
            return False

    # -------------------------------------------------------------------------
    def arduino_sketch_ver_le(self, test_version):
        """Method to test whether the Arduino sketch version is less than or
           equal to the specified value
        """
        if (self.arduino_sketch_ver_lt(test_version) or
                self.arduino_sketch_ver_eq(test_version)):
            return True
        else:
            return False

    # -------------------------------------------------------------------------
    def arduino_sketch_ver_ge(self, test_version):
        """Method to test whether the Arduino sketch version is greater than
           or equal to the specified value
        """
        if (self.arduino_sketch_ver_gt(test_version) or
                self.arduino_sketch_ver_eq(test_version)):
            return True
        else:
            return False

    # -------------------------------------------------------------------------
    def process_eeprom_value(self):
        """Method to process one EEPROM value returned by the Arduino"""
        eeprom_re = re.compile("EEPROM addr: (\d+)\s+value: (\d+\.\d+)")
        match = eeprom_re.search(self.msg_from_arduino)
        if match:
            eeprom_addr = int(match.group(1))
            eeprom_value = match.group(2)
        else:
            err_str = ("ERROR: Bad EEPROM value message: {}"
                       .format(self.msg_from_arduino))
            self.logger.print_and_log(err_str)
            return RC_FAILURE

        if eeprom_addr == EEPROM_VALID_ADDR:
            if eeprom_value != EEPROM_VALID_VALUE:
                err_str = ("ERROR: Bad EEPROM valid value: {}"
                           .format(self.msg_from_arduino))
                self.logger.print_and_log(err_str)
                return RC_FAILURE
        elif eeprom_addr == EEPROM_VALID_COUNT_ADDR:
            if int(float(eeprom_value)) > EEPROM_VALID_COUNT:
                warn_str = ("WARNING: EEPROM contains more values than "
                            "supported by this version of the application: {}"
                            .format(self.msg_from_arduino))
                self.logger.print_and_log(warn_str)
        elif eeprom_addr == EEPROM_R1_OHMS_ADDR:
            self.vdiv_r1 = float(eeprom_value)
        elif eeprom_addr == EEPROM_R2_OHMS_ADDR:
            self.vdiv_r2 = float(eeprom_value)
        elif eeprom_addr == EEPROM_RF_OHMS_ADDR:
            self.amm_op_amp_rf = float(eeprom_value)
        elif eeprom_addr == EEPROM_RG_OHMS_ADDR:
            self.amm_op_amp_rg = float(eeprom_value)
        elif eeprom_addr == EEPROM_SHUNT_UOHMS_ADDR:
            self.amm_shunt_max_volts = (self.amm_shunt_max_amps *
                                        (float(eeprom_value) / 1000000.0))
        elif eeprom_addr == EEPROM_V_CAL_X1M_ADDR:
            self.v_cal = float(eeprom_value) / 1000000.0
        elif eeprom_addr == EEPROM_I_CAL_X1M_ADDR:
            self.i_cal = float(eeprom_value) / 1000000.0
        elif eeprom_addr == EEPROM_V_BATT_X1M_ADDR:
            pass  # obsolete
        elif eeprom_addr == EEPROM_R_BATT_X1M_ADDR:
            pass  # obsolete
        else:
            warn_str = ("WARNING: EEPROM value not "
                        "supported by this version of the application: {}"
                        .format(self.msg_from_arduino))
            self.logger.print_and_log(warn_str)

        return RC_SUCCESS

    # -------------------------------------------------------------------------
    def correct_adc_values(self, adc_pairs, comb_dupv_pts, fix_voc, fix_isc,
                           reduce_noise, fix_overshoot, battery_bias):
        """Method to remove errors from the ADC values. This consists of the
           following corrections:
             - Combine points with same voltage (use average current)
             - Zero out the current value for the Voc point
             - Remove the Isc point if it is not reliable
             - Replace the Isc point with a better extrapolation than the
               Arduino code was capable of
             - Apply a noise reduction algorithm
             - Adjust ADC values voltages to compensate for Voc shift
           Each of the above is configurable.
        """
        self.logger.log("Correcting ADC values:")

        # Combine points with the same voltage (use average current)
        if comb_dupv_pts:
            adc_pairs_corrected = self.combine_dup_voltages(adc_pairs)
        else:
            adc_pairs_corrected = adc_pairs[:]

        # Fix Voc
        if fix_voc:
            # Zero out the CH1 value for the Voc point so it is in line
            # with the tail of the curve and so the curve will reach the
            # axis
            adc_pairs_corrected[-1] = (adc_pairs_corrected[-1][0], 0.0)

        # Remove Isc point in some cases
        if fix_isc and not battery_bias:
            # Remove point 0 (the Isc point which was extrapolated by the
            # Arduino code) if the next point's CH0 value is more than
            # MIN_PT1_TO_VOC_RATIO_FOR_ISC of the Voc CH0 value.  We have to
            # check that point 0's voltage is zero before doing this, since
            # this method can be called again after this has already been
            # done, and we don't want to remove any points other than the
            # one with V=0.
            suppress_isc_point = False
            pt0_ch0 = adc_pairs_corrected[0][0]
            if pt0_ch0 <= self._adc_ch0_offset:
                pt1_ch0 = float(adc_pairs_corrected[1][0])
                voc_ch0 = float(adc_pairs_corrected[-1][0])
                if (pt1_ch0 / voc_ch0) > MIN_PT1_TO_VOC_RATIO_FOR_ISC:
                    del adc_pairs_corrected[0]
                    suppress_isc_point = True

        # Noise reduction
        if reduce_noise:
            if (fix_isc and not battery_bias and
                    not suppress_isc_point):
                # Replace CH1 (current) value of Isc point with CH1
                # value of first measured point
                isc_ch1 = adc_pairs_corrected[1][1]
                adc_pairs_corrected[0] = (0.0, isc_ch1)
            adc_pairs_for_nr = adc_pairs_corrected[:-1]  # exclude Voc
            adc_pairs_nr = self.noise_reduction(adc_pairs_for_nr,
                                                starting_rot_thresh=10.0,
                                                iterations=25,
                                                thresh_divisor=2.0)
            # Tack Voc point back on
            adc_pairs_corrected = adc_pairs_nr + [adc_pairs_corrected[-1]]

        # Fix Isc
        if fix_isc and not battery_bias:
            # Replace Isc point (again) with a better extrapolation
            if not suppress_isc_point:
                isc_ch1 = self.create_new_isc_point(adc_pairs_corrected)
                adc_pairs_corrected[0] = (0.0, isc_ch1)

        # Adjust voltages to compensate for overshoot
        if fix_overshoot:
            v_adj = self.v_adj(adc_pairs_corrected)
            log_msg = "  v_adj = {}".format(v_adj)
            self.logger.log(log_msg)
            adc_pairs_wo_overshoot = []
            voc_pair_num = len(adc_pairs_corrected) - 1  # last one is Voc
            for pair_num, adc_pair in enumerate(adc_pairs_corrected):
                if pair_num == voc_pair_num:
                    v_adj = 1.0
                ch0_adc_wo_overshoot = adc_pair[0] * v_adj
                ch1_adc_wo_overshoot = adc_pair[1]
                adc_pairs_wo_overshoot.append((ch0_adc_wo_overshoot,
                                               ch1_adc_wo_overshoot))
            adc_pairs_corrected = adc_pairs_wo_overshoot[:]

        return adc_pairs_corrected

    # -------------------------------------------------------------------------
    def combine_dup_voltages(self, adc_pairs):
        """Method to combine consecutive points with duplicate voltages (CH0
           values) to a single point with the average of their current
           (CH1) values
        """
        non_dup_adc_pairs = []
        ch1_sum = 0
        ch0_count = 0
        last_pair_num = len(adc_pairs) - 1
        for pair_num, adc_pair in enumerate(adc_pairs):
            ch0_adc = adc_pair[0]
            ch1_adc = adc_pair[1]
            # If the CH0 value is the same as that of the next point,
            # don't add the point to the new list; just accumulate the
            # CH1 value and increment the count to calculate the
            # average later.
            if (pair_num < last_pair_num and
                    ch0_adc == adc_pairs[pair_num+1][0]):
                # Add CH1 value to the CH1 sum and increment the
                # CH0 count for the average calculation.
                ch1_sum += ch1_adc
                ch0_count += 1
            else:
                if ch0_count > 0:
                    # This is the last point in a sequence with
                    # duplicate CH0 values, so calculate the average CH1
                    # value and append the single point to the list
                    avg_ch1_adc = float(ch1_sum + ch1_adc) / (ch0_count + 1)
                    non_dup_adc_pairs.append((ch0_adc, avg_ch1_adc))
                    # Reset the sum and count variables
                    ch1_sum = 0
                    ch0_count = 0
                else:
                    non_dup_adc_pairs.append((ch0_adc, ch1_adc))

        return non_dup_adc_pairs

    # -------------------------------------------------------------------------
    def v_adj(self, adc_pairs):
        """Method to determine the voltage adjustment value"""
        # Compensate for (as-of-yet-not-understood) effect where the
        # curve intersects the voltage axis at a value greater than Voc

        # Initialize v_adj to 1.0 (no adjustment) and just return that
        # now if there are fewer than two points
        v_adj = 1.0
        if len(adc_pairs) < 2:
            return v_adj

        # Default assumption is that the extrapolated curve intercepts
        # the V axis at the same voltage as the final measured point
        avg_v_intercept = adc_pairs[-2][0]

        # Now look at the four preceding points
        v_intercepts = []
        for adc_pair_index in [-6, -5, -4, -3]:
            if len(adc_pairs) + adc_pair_index < 0:
                continue
            # If the point's ADC CH1 (current) value is more than 20% of
            # Isc, skip to next (unless it is the last one)
            if (adc_pair_index < -3 and
                    adc_pairs[adc_pair_index][1] >
                    (adc_pairs[0][1] * 0.2)):
                continue
            # Calculate V-intercept using the line determined by this
            # point and the final measured point
            v1 = float(adc_pairs[adc_pair_index][0])
            i1 = float(adc_pairs[adc_pair_index][1])
            v2 = float(adc_pairs[-2][0])
            i2 = float(adc_pairs[-2][1])
            delta_v = v2 - v1
            delta_i = i1 - i2
            if delta_v < 0.0 or delta_i <= 0.0:
                # Throw out points that decrease in voltage or do not
                # decrease in current
                continue
            v_intercept = (i1 * delta_v / delta_i) + v1
            if not v_intercepts or abs(v_intercept - v_intercepts[-1]) <= 5:
                # Keep v_intercepts only if they are different by 5 or
                # less from their precedessors.  This assumes that the
                # earlier ones are more reliable due to their greater
                # distance from the V axis.
                v_intercepts.append(v_intercept)
        if v_intercepts:
            avg_v_intercept = sum(v_intercepts) / float(len(v_intercepts))
        voc_adc = adc_pairs[-1][0]
        if avg_v_intercept:
            v_adj = float(voc_adc) / float(avg_v_intercept)
        return v_adj

    # -------------------------------------------------------------------------
    def noise_reduction(self, adc_pairs, starting_rot_thresh=5.0,
                        iterations=1, thresh_divisor=2.0):
        """Method to smooth out "bumps" in the curve. The trick is to
           disambiguate between deviations (bad) and inflections
           (normal). For each point on the curve, the rotation angle at
           that point is calculated. If this angle exceeds a threshold,
           it is either a deviation or an inflection. It is an
           inflection if the rotation angle relative to several points
           away is actually larger than the rotation angle relative to
           the neighbor points.  Inflections are left alone. Deviations
           are corrected by replacing them with a point interpolated
           (linearly) between its neighbors. This algorithm may be
           performed incrementally, starting with a large threshold and
           then dividing that threshold by some amount each time - in
           theory this should provide better results because the larger
           deviations will be smoothed out first, so it is more clear
           what is a deviation and what isn't.
        """
        adc_pairs_nr = adc_pairs[:]
        num_points = len(adc_pairs)
        rot_thresh = starting_rot_thresh
        for ii in xrange(iterations):
            # Calculate the distance (in points) of the "far" points for
            # the inflection comparison.  It is 1/25 of the total number
            # of points, but always at least 2.
            dist = int(num_points / 25.0)
            if dist < 2:
                dist = 2
            for point in xrange(num_points - 1):
                # Rotation calculation
                pairs_list = adc_pairs_nr
                rot_degrees = self.rotation_at_point(pairs_list, point)
                if abs(rot_degrees) > rot_thresh:
                    deviation = True
                    if point >= dist and point < (num_points - dist):
                        long_rot_degrees = self.rotation_at_point(pairs_list,
                                                                  point,
                                                                  dist)
                        if ((long_rot_degrees > 0) and (rot_degrees > 0) and
                                (long_rot_degrees > rot_degrees)):
                            deviation = False
                        if ((long_rot_degrees <= 0) and (rot_degrees < 0) and
                                (long_rot_degrees < rot_degrees)):
                            deviation = False
                    if deviation:
                        curr_point = pairs_list[point]
                        prev_point = pairs_list[point-1]
                        next_point = pairs_list[point+1]
                        if point > 1:
                            ch0_adc_corrected = (prev_point[0] +
                                                 next_point[0]) / 2.0
                        else:
                            # Don't correct voltage of point 1.  Otherwise
                            # it migrates toward the Isc point each
                            # iteration, and that doesn't seem right since
                            # the Isc point is extrapolated.
                            ch0_adc_corrected = curr_point[0]
                        ch1_adc_corrected = (prev_point[1] +
                                             next_point[1]) / 2.0
                        adc_pairs_nr[point] = (ch0_adc_corrected,
                                               ch1_adc_corrected)
            rot_thresh /= thresh_divisor

        return adc_pairs_nr

    # -------------------------------------------------------------------------
    def rotation_at_point(self, adc_pairs, point, distance=1):
        """Method to calculate the angular rotation at a point on the
           curve. The list of points and the point number of
           interest are passed in.  By default, the angle is
           calculated using the immediate neighbor points
           (distance=1), but setting this parameter to a larger
           value calculates the angle using points at that distance
           on either side from the specified point.
        """
        if point == 0:
            return 0.0
        if adc_pairs:
            i_scale = (float(adc_pairs[-1][0]) /
                       float(adc_pairs[0][1]))  # Voc/Isc
        else:
            i_scale = INFINITE_VAL
        if distance < point:
            pt1 = point - distance
        else:
            pt1 = 0
        pt2 = point
        if point + distance < len(adc_pairs):
            pt3 = point + distance
        else:
            pt3 = len(adc_pairs) - 1
        i1 = adc_pairs[pt1][1]
        v1 = adc_pairs[pt1][0]
        i2 = adc_pairs[pt2][1]
        v2 = adc_pairs[pt2][0]
        i3 = adc_pairs[pt3][1]
        v3 = adc_pairs[pt3][0]
        if v2 == v1:
            if i2 > i1:
                m12 = INFINITE_VAL
            else:
                m12 = -(INFINITE_VAL)
        else:
            m12 = i_scale * (i2 - i1) / (v2 - v1)
        if v3 == v2:
            if i2 > i1:
                m23 = INFINITE_VAL
            else:
                m23 = -(INFINITE_VAL)
        else:
            m23 = i_scale * (i3 - i2) / (v3 - v2)
        rot_degrees = (math.degrees(math.atan(m12)) -
                       math.degrees(math.atan(m23)))
        return rot_degrees

    # -------------------------------------------------------------------------
    def create_new_isc_point(self, adc_pairs, replace=True):
        """Method to replace the Isc point with a new "better" one or to
           generate a new one without removing any of the current
           points.  The algorithm starts by analyzing the ADC values
           looking for where the curve begins to deflect downward.  It
           then uses the points before that to determine where the curve
           should intersect with the vertical axis.  If replace=True,
           the first existing point is not used by the algorithm since
           it will be replaced by the new value.  If replace=False, the
           first point is used by the algorithm since the new point will
           precede it.
        """
        # First determine where the curve begins to deflect
        if replace:
            deflect_begin = self.find_first_downward_deflection(adc_pairs[1:])
            deflect_begin += 1
        else:
            deflect_begin = self.find_first_downward_deflection(adc_pairs)
        if deflect_begin < 2:
            # Force to minimum of 2 so extrapolation is always possible
            deflect_begin = 2
        pt2 = (deflect_begin / 2) + 1
        max_pt1 = (pt2 / 2) + 1
        if max_pt1 == pt2:
            max_pt1 -= 1
        if pt2 > len(adc_pairs) - 1:
            return adc_pairs[0][1]
        v2 = float(adc_pairs[pt2][0])
        i2 = float(adc_pairs[pt2][1])
        if replace:
            first_pt1 = 1
        else:
            first_pt1 = 0
        new_isc_ch1_vals = []
        for pt1_num, pt1_adc_pair in enumerate(adc_pairs[first_pt1:max_pt1+1]):
            v1 = float(pt1_adc_pair[0])
            i1 = float(pt1_adc_pair[1])
            if v1 != v2:
                m = (i2 - i1)/(v2 - v1)
            else:
                if i2 > i1:
                    m = INFINITE_VAL
                else:
                    m = -(INFINITE_VAL)
            new_isc_ch1_val = i1 - (m * v1)
            new_isc_ch1_vals.append(new_isc_ch1_val)
            if pt1_num > first_pt1 + 15:
                break
        if len(new_isc_ch1_vals):
            total_increase = 0
            total_decrease = 0
            prev_new_isc_ch1_val = 0
            for pair_num, new_isc_ch1_val in enumerate(new_isc_ch1_vals):
                if pair_num > 0:
                    if new_isc_ch1_val > prev_new_isc_ch1_val:
                        increase = new_isc_ch1_val - prev_new_isc_ch1_val
                        total_increase += increase
                    else:
                        decrease = prev_new_isc_ch1_val - new_isc_ch1_val
                        total_decrease += decrease
                prev_new_isc_ch1_val = new_isc_ch1_val
            if total_increase > 0 and total_decrease > 0:
                # Use average if there is a mix of increases and
                # decreases in the extrapolated Isc values
                return sum(new_isc_ch1_vals) / float(len(new_isc_ch1_vals))
            elif total_increase > 0:
                # If the values are all increasing, then subtract the
                # average increase from the first value.  This is the
                # case where the curve is inflecting downward from the
                # start and continues to do so.
                avg_increase = total_increase / float(len(new_isc_ch1_vals))
                return new_isc_ch1_vals[0] - avg_increase
            else:
                # If the values are all decreasing, then add the average
                # decrease to the first value.  This is the case where
                # the curve is inflecting upward from the start and
                # continues to do so.
                avg_decrease = total_decrease / float(len(new_isc_ch1_vals))
                return new_isc_ch1_vals[0] + avg_decrease
        else:
            # Just return the existing Isc value if extrapolation was
            # not performed (shouldn't ever get here now).
            return adc_pairs[0][1]

    # -------------------------------------------------------------------------
    def find_first_downward_deflection(self, adc_pairs):
        """Method to find the point where the curve starts to deflect downward
        """
        # This borrows from the noise reduction algorithm, where the
        # angle of inflection is determined for a given point by
        # calculating the angle between it and points several points
        # away on either side. The start of the downward deflection is
        # determined to be the first point whose inflection angle is
        # greater than or equal to 1/15 the maximum inflection angle.
        num_points = len(adc_pairs)
        dist = int(num_points / 25.0)
        if dist < 2:
            dist = 2
        retry = 20
        while retry > 0:
            retry -= 1
            lrd_list = []
            max_long_rot_degrees = -999.0
            prev_long_rot_degrees = -999.0
            deflect_begin = 0
            reduced_rotation_count = 0
            if dist == 2:
                retry = -1
            for point in xrange(dist):
                lrd_list.append(-999.0)
            for point in xrange(dist, num_points - 1 - dist):
                long_rot_degrees = self.rotation_at_point(adc_pairs,
                                                          point,
                                                          dist)
                if long_rot_degrees < prev_long_rot_degrees:
                    reduced_rotation_count += 1
                else:
                    reduced_rotation_count = 0
                if (long_rot_degrees > 2.0 and
                        long_rot_degrees > max_long_rot_degrees):
                    max_long_rot_degrees = long_rot_degrees
                    max_long_rot_point = point
                elif max_long_rot_degrees > 0.0 and reduced_rotation_count > 2:
                    # If we've captured a max rotation but now we're
                    # seeing a trend toward a reduced rotation (three
                    # points in a row), we've passed the first
                    # deflection, and need to bail out.  This only
                    # applies to curves that have multiple downward
                    # deflections.  The purpose is that we never want to
                    # use the second (or third ..) deflection.
                    break
                lrd_list.append(long_rot_degrees)
                prev_long_rot_degrees = long_rot_degrees
            deflect_begin_found = False
            if max_long_rot_degrees > 0.0:
                for point in xrange(max_long_rot_point/2, len(lrd_list) - 1):
                    if lrd_list[point] >= max_long_rot_degrees / 15.0:
                        deflect_begin = point
                        if deflect_begin >= 3 * dist or dist == 2:
                            deflect_begin_found = True
                            retry = -1
                        break
            if not deflect_begin_found:
                dist -= 1
        if retry == 0:
            err_str = ("{} find_first_downward_deflection retried too many "
                       "times".format(os.path.basename(self.hdd_output_dir)))
            self.logger.print_and_log(err_str)

        return deflect_begin

    # -------------------------------------------------------------------------
    def convert_adc_values(self, adc_pairs):
        """Method to convert the ADC values to voltage, current, power,
           and resistance tuples and fill the data_points structure
        """
        self.data_points = []
        for pair_num, adc_pair in enumerate(adc_pairs):
            volts = adc_pair[0] * self.v_mult
            amps = adc_pair[1] * self.i_mult
            watts = volts * amps
            if amps:
                ohms = volts / amps
            else:
                ohms = INFINITE_VAL
            self.data_points.append((amps, volts, ohms, watts))
            output_line = ("V={:.6f}, I={:.6f}, P={:.6f}, R={:.6f}"
                           .format(volts, amps, watts, ohms))
            self.logger.log(output_line)

    # -------------------------------------------------------------------------
    def gen_corrected_adc_csv(self, adc_pairs, comb_dupv_pts, fix_voc, fix_isc,
                              reduce_noise, fix_overshoot, battery_bias,
                              corr_adc_csv_file):
        """Method to take raw ADC values and generate a CSV file with the
           selected corrections.
        """
        # Apply corrections
        adc_pairs_corrected = self.correct_adc_values(adc_pairs,
                                                      comb_dupv_pts,
                                                      fix_voc,
                                                      fix_isc,
                                                      reduce_noise,
                                                      fix_overshoot,
                                                      battery_bias)

        # Write corrected ADC values to output CSV file
        self.write_adc_pairs_to_csv_file(corr_adc_csv_file,
                                         adc_pairs_corrected)

    # -------------------------------------------------------------------------
    def gen_bias_batt_adc_csv(self):
        """Method to generate bias battery CSV file. This method is called
           immediately after the bias battery calibration curve has
           been swung. The generated CSV file has the ADC corrections
           (e.g. noise reduction) applied.
        """
        uncorr_adc_csv_file = self.hdd_adc_pairs_csv_filename
        raw_adc_pairs = self.read_adc_pairs_from_csv_file(uncorr_adc_csv_file)
        bias_batt_csv_file = uncorr_adc_csv_file.replace("adc_pairs",
                                                         "bias_batt_adc_pairs")
        kwargs = {"adc_pairs": raw_adc_pairs,
                  "comb_dupv_pts": True,
                  "fix_voc": True,
                  "fix_isc": True,
                  "reduce_noise": True,
                  "fix_overshoot": True,
                  "battery_bias": False,
                  "corr_adc_csv_file": bias_batt_csv_file}
        self.gen_corrected_adc_csv(**kwargs)

        return bias_batt_csv_file

    # -------------------------------------------------------------------------
    def apply_battery_bias(self, adc_pairs):
        """Method to subtract the battery bias from the measured points. The
           IV curve for the bias battery is nearly linear, but not
           quite. Previous versions of the software assumed it was
           linear, and used only the open circuit voltage (v_batt) and
           internal resistance (r_batt) to calculate the voltage bias
           for each measured point. This produced poor results. Now
           the entire battery IV curve is saved when a bias battery
           calibration is performed. The voltage bias is calculated
           for a given point by finding the two points on the bias
           battery curve that have the closest current measurement to
           the given point and interpolating between them to find the
           exact voltage bias amount. Note that this is all done in
           the ADC domain, i.e. before ADC values are converted to
           volts and amps.
        """
        # Get the CSV file with the corrected ADC values for the bias
        # battery IV curve
        bias_battery_csv = self.get_bias_batt_csv()
        if bias_battery_csv is None:
            # If the CSV file is not found, just return the unbiased
            # ADC pairs
            return adc_pairs

        # Parse the ADC pairs from the bias battery CSV file
        batt_adc_pairs = self.read_adc_pairs_from_csv_file(bias_battery_csv)

        # Process each ADC pair in the input list
        biased_adc_pairs = []
        last_negv_point = None
        for adc_pair in adc_pairs:
            ch0_adc = adc_pair[0]  # voltage value
            ch1_adc = adc_pair[1]  # current value
            prev_batt_ch0_adc = None
            prev_batt_ch1_adc = None

            # Search the bias battery ADC pairs
            for batt_adc_pair in batt_adc_pairs:
                batt_ch0_adc = batt_adc_pair[0]
                batt_ch1_adc = batt_adc_pair[1]

                # Stop when the battery ADC pair has a smaller current
                # than the given point
                if batt_ch1_adc < ch1_adc:
                    # Use interpolation between this battery ADC pair
                    # and its predecessor to find the voltage value on
                    # the battery curve that corresponds to the
                    # current of the given point; this is the bias
                    interp_batt_ch1_adc = prev_batt_ch1_adc - ch1_adc
                    interp_batt_ch0_adc = (interp_batt_ch1_adc *
                                           (batt_ch0_adc - prev_batt_ch0_adc) /
                                           (prev_batt_ch1_adc - batt_ch1_adc))
                    ch0_bias = prev_batt_ch0_adc + interp_batt_ch0_adc
                    break
                prev_batt_ch0_adc = batt_ch0_adc
                prev_batt_ch1_adc = batt_ch1_adc

            # Special case: Voc point. No interpolation here - the
            # bias is simply the battery Voc (CH0 of last pair)
            if ch1_adc == 0:
                ch0_bias = batt_adc_pairs[-1][0]

            # Subtract bias amount from voltage (CH0)
            biased_ch0_adc = ch0_adc - ch0_bias

            # If biased value is negative, throw the point away.
            # Otherwise, append it to the output list
            if biased_ch0_adc < 0:
                # Actually, keep track of the last negative voltage
                # point so we can interpolate the Isc point
                last_negv_point = (biased_ch0_adc, ch1_adc)
                continue
            else:
                biased_adc_pairs.append((biased_ch0_adc, ch1_adc))

        # Some points of the biased curve were discarded because they
        # had a negative voltage.  The first non-discarded point has a
        # positive voltage.  We need to fabricate a new Isc point at
        # zero voltage.  This is done by interpolating between the last
        # discarded point (v0,i0) and the first non-discarded point
        # (v1,i1).
        if len(biased_adc_pairs) > 1 and last_negv_point is not None:
            v0 = last_negv_point[0]
            i0 = last_negv_point[1]
            v1 = biased_adc_pairs[0][0]
            i1 = biased_adc_pairs[0][1]
            isc_ch1 = i1 + ((v1 * (i0 - i1)) / (-v0 + v1))
            new_point = (0.0, isc_ch1)
            biased_adc_pairs = [new_point] + biased_adc_pairs

        return biased_adc_pairs

    # -------------------------------------------------------------------------
    def get_bias_batt_csv(self):
        """Method to find the bias battery CSV file
        """
        bias_battery_csv = None
        glob_pattern = "{}/bias_batt_adc_pairs*.csv"
        # Find the bias battery CSV file. If one exists in the run
        # directory, use that.  Otherwise, copy the one from the parent
        # directory to the run directory and then use it.
        dir = self.hdd_output_dir
        bb_files = glob.glob(glob_pattern.format(dir))
        bb_file_count = 0
        for f in bb_files:
            bias_battery_csv = f
            bb_file_count += 1
        if bb_file_count > 1:
            err_str = ("ERROR: There are multiple "
                       "bias_batt_adc_pairs*.csv files in {}".format(dir))
            self.logger.print_and_log(err_str)
        elif bb_file_count == 0:
            dir = os.path.dirname(self.hdd_output_dir)
            bb_files = glob.glob(glob_pattern.format(dir))
            for f in bb_files:
                bias_battery_csv = f
                bb_file_count += 1
            if bb_file_count > 1:
                err_str = ("ERROR: There are multiple "
                           "bias_batt_adc_pairs*.csv files in {}".format(dir))
                self.logger.print_and_log(err_str)
            elif bb_file_count == 0:
                err_str = ("ERROR: There is no "
                           "bias_batt_adc_pairs*.csv file in {}".format(dir))
                self.logger.print_and_log(err_str)
            else:
                # Copy to run directory
                shutil.copy(bias_battery_csv, self.hdd_output_dir)
                # Recursive call will now find file in run dir
                bias_battery_csv = self.get_bias_batt_csv()
                return bias_battery_csv
        return bias_battery_csv

    # -------------------------------------------------------------------------
    def remove_prev_bias_battery_csv(self):
        """Method to remove old bias battery CSV file(s) from the IV_Swinger2
           directory"""
        glob_pattern = "{}/bias_batt_adc_pairs*.csv"
        dir = os.path.dirname(self.hdd_output_dir)
        bb_files = glob.glob(glob_pattern.format(dir))
        for f in bb_files:
            self.clean_up_file(f)

    # -------------------------------------------------------------------------
    def log_initial_debug_info(self):
        """Method to write pre-run debug info to the log file"""

        self.logger.log("app_data_dir = {}".format(self.app_data_dir))
        self.logger.log("log_file_name = {}".format(self.logger.log_file_name))
        self.logger.log("adc_inc = {}".format(self.adc_inc))
        self.logger.log("vdiv_ratio = {}".format(self.vdiv_ratio))
        self.logger.log("v_mult = {}".format(self.v_mult))
        self.logger.log("amm_op_amp_gain = {}".format(self.amm_op_amp_gain))
        self.logger.log("i_mult = {}".format(self.i_mult))

    # -------------------------------------------------------------------------
    def create_hdd_output_dir(self, date_time_str):
        """Method to create the HDD output directory"""

        # Create the HDD output directory
        hdd_iv_swinger_dirs = self.create_iv_swinger_dirs([""],
                                                          include_csv=False,
                                                          include_pdf=False)
        hdd_iv_swinger_dir = hdd_iv_swinger_dirs[0]  # only one
        self.hdd_output_dir = os.path.join(hdd_iv_swinger_dir, date_time_str)
        os.makedirs(self.hdd_output_dir)

    # -------------------------------------------------------------------------
    def copy_file_to_parent(self, file):
        """Method to copy a file to the IV_Swinger2 directory (parent of
           output directory)
        """
        dir = os.path.dirname(self.hdd_output_dir)
        try:
            shutil.copy(file, dir)
        except shutil.Error as e:
            err_str = ("Couldn't copy {} to {} ({})"
                       .format(file, dir, e))
            self.logger.print_and_log(err_str)

    # -------------------------------------------------------------------------
    def write_adc_pairs_to_csv_file(self, filename, adc_pairs):
        """Method to write each pair of readings from the ADC to a CSV
        file. This file is not used for the current run, but may be used
        later for debug or for regenerating the data points after
        algorithm improvements. It is the only history of the raw
        readings.
        """
        with open(filename, "w") as f:
            # Write headings
            f.write("CH0 (voltage), CH1 (current)\n")
            # Write ADC pairs
            for adc_pair in adc_pairs:
                csv_str = "{},{}\n".format(adc_pair[0], adc_pair[1])
                f.write(csv_str)

        self.logger.log("Raw ADC values written to {}".format(filename))

    # -------------------------------------------------------------------------
    def read_adc_pairs_from_csv_file(self, filename):
        """Method to read a CSV file containing ADC pairs and return the list
           of ADC pairs
        """
        adc_pairs = []
        try:
            with open(filename, "r") as f:
                for ii, line in enumerate(f.read().splitlines()):
                    if ii == 0:
                        expected_first_line = "CH0 (voltage), CH1 (current)"
                        if line != expected_first_line:
                            err_str = ("ERROR: first line of ADC CSV is not {}"
                                       .format(expected_first_line))
                            self.ivs2.logger.print_and_log(err_str)
                            return []
                    else:
                        adc_pair = map(float, line.split(","))
                        if len(adc_pair) != 2:
                            err_str = ("ERROR: CSV line {} is not in "
                                       "expected CH0, CH1 format"
                                       .format(ii + 1))
                            self.ivs2.logger.print_and_log(err_str)
                            return []
                        adc_tuple = (adc_pair[0], adc_pair[1])
                        adc_pairs.append(adc_tuple)
        except (IOError):
            print "Cannot open {}".format(filename)
            return []

        return adc_pairs

    # -------------------------------------------------------------------------
    def get_adc_offsets(self, adc_pairs):
        """Method to determine the minimum value of the ADC for each channel.
           This previously was treated as the "zero" value for the
           channel, and all other values were modified to subtract this
           value.  Now this is thought to be the "noise floor" of the
           channel, which just means that it is the lowest value that
           the channel can measure, and values above it should not be
           adjusted.

           Also in this method we check if any of the measured ADC
           values is the maximum (saturated) value and set a flag if so.
        """
        # Normally the last (Voc) CH1 value is the offset value (assumed
        # to apply to both channels since we don't ever see the "zero"
        # value on CH0). However, occasionally a lower value shows up,
        # in which case we want to use that.
        self._adc_ch0_offset = adc_pairs[-1][1]
        self._adc_ch1_offset = adc_pairs[-1][1]
        self._voltage_saturated = False
        self._current_saturated = False
        for adc_pair in adc_pairs:
            if adc_pair[0] < self._adc_ch0_offset:
                self._adc_ch0_offset = adc_pair[0]
            if adc_pair[0] == ADC_MAX:
                self._voltage_saturated = True
            if adc_pair[1] < self._adc_ch1_offset:
                self._adc_ch1_offset = adc_pair[1]
            if adc_pair[1] == ADC_MAX:
                self._current_saturated = True

    # -------------------------------------------------------------------------
    def adc_sanity_check(self, adc_pairs):
        """Method to do basic sanity checks on the ADC values
        """
        voc_adc = adc_pairs[-1][0]
        isc_adc = adc_pairs[0][1]
        # Check for Voc = 0V
        if voc_adc - self._adc_ch0_offset == 0:
            self.logger.log("ERROR: Voc is zero volts")
            return RC_ZERO_VOC

        # Check for Isc = 0A
        if isc_adc - self._adc_ch1_offset == 0:
            self.logger.log("ERROR: Isc is zero amps")
            return RC_ZERO_ISC

        return RC_SUCCESS

    # -------------------------------------------------------------------------
    def swing_iv_curve(self, loop_mode=False, first_loop=False):
        """Method to generate and plot an IV curve. This overrides the
           method in the IV_Swinger base class, but is completely
           different. The actual swinging of the IV curve is done by the
           Arduino. This method triggers the Arduino, receives the data
           points from it, converts the results to
           volts/amps/watts/ohms, writes the values to a CSV file, and
           plots the results to both PDF and GIF files.
           """

        # Generate the date/time string from the current time
        while True:
            date_time_str = IV_Swinger.DateTimeStr.get_date_time_str()
            # Sleep and retry if it's the same as last time. Current resolution
            # is 1 second, so this limits the rate to one curve per second.
            if date_time_str == self.prev_date_time_str:
                time.sleep(0.1)
            else:
                self.prev_date_time_str = date_time_str
                break

        # Create the HDD output directory
        self.create_hdd_output_dir(date_time_str)

        # Write info to the log file
        self.logger.log("================== Swing! ==========================")
        self.logger.log("Loop mode: {}".format(loop_mode))
        self.logger.log("Output directory: {}".format(self.hdd_output_dir))

        # Get the name of the CSV files
        self.get_csv_filenames(self.hdd_output_dir, date_time_str)

        # If Arduino has not already been reset and communication
        # established, do that now
        if not self.arduino_ready:

            # Reset Arduino
            rc = self.reset_arduino()
            if rc != RC_SUCCESS:
                return rc

            # Wait for Arduino ready message
            rc = self.wait_for_arduino_ready_and_ack()
            if rc != RC_SUCCESS:
                return rc

        # Send "go" message to Arduino
        rc = self.send_msg_to_arduino("Go")
        if rc != RC_SUCCESS:
            return rc

        # Receive ADC data from Arduino and store in adc_pairs property
        # (list of tuples)
        rc = self.receive_data_from_arduino()

        # Write ADC pairs to CSV file
        self.write_adc_pairs_to_csv_file(self.hdd_adc_pairs_csv_filename,
                                         self.adc_pairs)

        # Write Unfiltered ADC pairs (if any) to CSV file
        if len(self.unfiltered_adc_pairs):
            unfiltered_adc_csv = self.hdd_unfiltered_adc_pairs_csv_filename
            self.write_adc_pairs_to_csv_file(unfiltered_adc_csv,
                                             self.unfiltered_adc_pairs)

        # Return if receive_data_from_arduino() failed
        if rc != RC_SUCCESS:
            return rc

        # Process ADC values
        rc = self.process_adc_values()
        if rc != RC_SUCCESS:
            return rc

        # Plot results
        self.plot_results()

        return RC_SUCCESS

    # -------------------------------------------------------------------------
    def swing_battery_calibration_curve(self):
        """Method to swing an IV curve for calibrating the bias battery
        """
        restore_max_iv_points = [self.max_iv_points]
        restore_isc_stable_adc = [self.isc_stable_adc]
        restore_correct_adc = [self.correct_adc]
        restore_reduce_noise = [self.reduce_noise]
        restore_battery_bias = [self.battery_bias]

        def restore_all_and_return(rc):
            self.max_iv_points = restore_max_iv_points[0]
            self.isc_stable_adc = restore_isc_stable_adc[0]
            self.correct_adc = restore_correct_adc[0]
            self.reduce_noise = restore_reduce_noise[0]
            self.battery_bias = restore_battery_bias[0]
            return rc

        # Temporarily set max_iv_points to 80 and isc_stable_adc to 200
        self.max_iv_points = 80
        self.isc_stable_adc = 200
        self.arduino_ready = False
        rc = self.reset_arduino()
        if rc == RC_SUCCESS:
            rc = self.wait_for_arduino_ready_and_ack()
        if rc != RC_SUCCESS:
            return restore_all_and_return(rc)

        # Force ADC correction and noise reduction ON
        self.correct_adc = True
        self.reduce_noise = True

        # Force battery bias OFF
        self.battery_bias = False

        # Swing the IV curve
        rc = self.swing_iv_curve()
        if rc != RC_SUCCESS:
            return restore_all_and_return(rc)

        # Save config to output directory (this also overwrites the
        # normal config file)
        config = Configuration(ivs2=self)
        config.populate()
        config.add_axes_and_title()
        config.save(self.hdd_output_dir)

        # Restore properties
        return restore_all_and_return(rc)

    # -------------------------------------------------------------------------
    def get_csv_filenames(self, dir, date_time_str):
        """Method to derive the names of the CSV files (ADC pairs and data
        points) and set the corresponding instance variables.
        """
        # Create the leaf file names
        adc_pairs_csv_leaf_name = "adc_pairs_{}.csv".format(date_time_str)
        unfiltered_adc_pairs_csv_leaf_name = ("unfiltered_adc_pairs_{}.csv"
                                              .format(date_time_str))
        csv_data_pt_leaf_name = ("{}{}.csv".format(self.file_prefix,
                                                   date_time_str))

        # Get the full-path names of the HDD output files
        unfiltered_adc_csv = os.path.join(dir,
                                          unfiltered_adc_pairs_csv_leaf_name)
        self.hdd_unfiltered_adc_pairs_csv_filename = unfiltered_adc_csv
        adc_csv = os.path.join(dir, adc_pairs_csv_leaf_name)
        self.hdd_adc_pairs_csv_filename = adc_csv
        csv = os.path.join(dir, csv_data_pt_leaf_name)
        self.hdd_csv_data_point_filename = csv

    # -------------------------------------------------------------------------
    def process_adc_values(self):
        """Method to process the ADC values from the Arduino, i.e. determine
           the offset values, perform sanity checks, apply
           corrections, and convert the values to volts, amps, watts,
           and ohms; and write those values to a CSV file
        """
        # Determine ADC offset values
        self.get_adc_offsets(self.adc_pairs)

        # Sanity check ADC values
        rc = self.adc_sanity_check(self.adc_pairs)
        if rc != RC_SUCCESS:
            return rc

        # Apply battery bias, if enabled
        if self.battery_bias:
            adc_pairs = self.adc_pairs
            self.adc_pairs_corrected = self.apply_battery_bias(adc_pairs)
            if len(self.adc_pairs_corrected) < 2:
                err_str = "ERROR: Fewer than two points recorded"
                self.logger.print_and_log(err_str)
                return RC_NO_POINTS
        else:
            self.adc_pairs_corrected = self.adc_pairs

        # Correct the ADC values to reduce noise, etc.
        if self.correct_adc:
            args = (self.adc_pairs_corrected, self.comb_dupv_pts, self.fix_voc,
                    self.fix_isc, self.reduce_noise, self.fix_overshoot,
                    self.battery_bias)
            self.adc_pairs_corrected = self.correct_adc_values(*args)

        # Convert the ADC values to volts, amps, watts, and ohms
        self.convert_adc_values(self.adc_pairs_corrected)

        # Write CSV file
        self.write_csv_data_points_to_file(self.hdd_csv_data_point_filename,
                                           self.data_points)
        return RC_SUCCESS

    # -------------------------------------------------------------------------
    def plot_results(self):
        """Method to plot results"""
        self.ivp = IV_Swinger2_plotter()
        self.ivp.title = self.plot_title
        self.ivp.logger = self.logger
        self.ivp.csv_files = [self.hdd_csv_data_point_filename]
        self.ivp.plot_dir = self.hdd_output_dir
        self.ivp.x_pixels = self.x_pixels
        self.ivp.generate_pdf = self.generate_pdf
        self.ivp.fancy_labels = self.fancy_labels
        self.ivp.linear = self.linear
        self.ivp.plot_power = self.plot_power
        self.ivp.font_scale = self.font_scale
        self.ivp.line_scale = self.line_scale
        self.ivp.point_scale = self.point_scale
        if self._voltage_saturated:
            self.ivp.v_sat = self.v_sat
        if self._current_saturated:
            self.ivp.i_sat = self.i_sat
        if self.plot_lock_axis_ranges:
            self.ivp.max_x = self.plot_max_x
            self.ivp.max_y = self.plot_max_y
        self.ivp.run()
        self.current_img = self.ivp.current_img
        self.plot_max_x = self.ivp.max_x
        self.plot_max_y = self.ivp.max_y

    # -------------------------------------------------------------------------
    def configure_logging(self):
        """Method to set up logging"""

        # Generate the date/time string from the current time
        date_time_str = IV_Swinger.DateTimeStr.get_date_time_str()

        # Create logs directory
        if not os.path.exists(self.logs_dir):
            os.makedirs(self.logs_dir)

        # Create the logger
        leaf_name = "log_{}.txt".format(date_time_str)
        IV_Swinger.PrintAndLog.log_file_name = os.path.join(self.logs_dir,
                                                            leaf_name)
        self.logger = PrintAndLog()

    # -------------------------------------------------------------------------
    def clean_up_after_failure(self, dir):
        """Method to remove the run directory after a failed run if it contains
           fewer than two files (which would be the ADC CSV file and
           the data points CSV file)
        """
        files = glob.glob("{}/*".format(dir))
        if len(files) < 2:
            for f in files:
                self.clean_up_file(f)
            if dir == os.getcwd():
                os.chdir("..")
            os.rmdir(dir)
            msg_str = "Removed {}".format(dir)
            self.logger.log(msg_str)

    # -------------------------------------------------------------------------
    def clean_up_files(self, dir, loop_mode=False,
                       loop_save_results=False,
                       loop_save_graphs=False):
        # Return without doing anything if directory doesn't exist
        if not os.path.exists(dir):
            return

        # Always remove the plt_ file(s)
        plt_files = glob.glob("{}/plt_*".format(dir))
        for f in plt_files:
            self.clean_up_file(f)

        # Always remove the PNG file(s)
        png_files = glob.glob("{}/*.png".format(dir))
        for f in png_files:
            self.clean_up_file(f)

        # Selectively remove other files in loop mode
        if loop_mode:
            if not loop_save_results:
                # Remove all files in loop directory
                loop_files = glob.glob("{}/*".format(dir))
                for f in loop_files:
                    self.clean_up_file(f)
                # Remove the (now empty) directory
                if dir == os.getcwd():
                    os.chdir("..")
                os.rmdir(dir)

            elif not loop_save_graphs:
                # Remove GIF only
                self.clean_up_file(self.current_img)

    # -------------------------------------------------------------------------
    def clean_up_file(self, f):
            os.remove(f)
            msg_str = "Removed {}".format(f)
            self.logger.log(msg_str)


############
#   Main   #
############
def main():
    """Main function"""
    # This module is not normally run as a standalone program - but if
    # it is, we might as well do something interesting. The code below
    # swings one IV curve, stores the result in the standard
    # (OS-dependent) place, and opens the PDF. The configuration is read
    # from the standard place. A copy of the configuration is saved in
    # the run directory, but the original config is restored.

    # Create an IVS2 object
    ivs2 = IV_Swinger2()
    ivs2.logger.print_and_log("Running from IV_Swinger2.main()")

    # Create a configuration object and get the current configuration
    # from the standard file (if it exists) and also keep a snapshot of
    # this starting config.
    config = Configuration(ivs2=ivs2)
    config.get()
    config.get_snapshot()

    # Override IVS2 properties / config options
    ivs2.isc_stable_adc = 120
    config.cfg_set("Arduino", "isc stable adc", ivs2.isc_stable_adc)

    # Log the initial debug stuff
    ivs2.log_initial_debug_info()

    # Swing the curve
    rc = ivs2.swing_iv_curve()

    if rc == RC_SUCCESS:
        # Update the config
        config.populate()
        config.add_axes_and_title()

        # Save the config and copy it to the output directory
        config.save(ivs2.hdd_output_dir)

        # Restore the master config file from the snapshot
        config.save_snapshot()  # restore original

        # Print message and close the log file
        msg_str = "  Results in: {}".format(ivs2.hdd_output_dir)
        ivs2.logger.print_and_log(msg_str)
        ivs2.logger.terminate_log()

        # Open the PDF
        if os.path.exists(ivs2.pdf_filename):
            sys_view_file(ivs2.pdf_filename)

        # Clean up files
        ivs2.clean_up_files(ivs2.hdd_output_dir)
    else:
        # Log error
        fail_str = "swing_iv_curve() FAILED: "
        if rc == RC_BAUD_MISMATCH:
            ivs2.logger.print_and_log("{}{}".format(fail_str,
                                                    "baud mismatch"))
        if rc == RC_TIMEOUT:
            ivs2.logger.print_and_log("{}{}".format(fail_str,
                                                    "message timeout"))
        if rc == RC_SERIAL_EXCEPTION:
            ivs2.logger.print_and_log("{}{}".format(fail_str,
                                                    "serial exception"))
        if rc == RC_ZERO_VOC:
            ivs2.logger.print_and_log("{}{}".format(fail_str,
                                                    "Voc is 0 volts"))
        if rc == RC_ZERO_ISC:
            ivs2.logger.print_and_log("{}{}".format(fail_str,
                                                    "Isc is 0 amps"))
        if rc == RC_ISC_TIMEOUT:
            ivs2.logger.print_and_log("{}{}".format(fail_str,
                                                    "Isc stable timeout"))
        if rc == RC_NO_POINTS:
            ivs2.logger.print_and_log("{}{}".format(fail_str,
                                                    "no points"))
        # Clean up
        ivs2.clean_up_after_failure(ivs2.hdd_output_dir)


# Boilerplate main() call
if __name__ == "__main__":
    main()
