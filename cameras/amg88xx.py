# SPDX-FileCopyrightText: 2025 JG for Cedar Grove Maker Studios
# SPDX-License-Identifier: MIT

"""
`AMG88xx.py`
AMG88xx thermal camera object.
"""

import board
import busio
from ulab import numpy as np
import adafruit_amg88xx


class CameraAMG88xx:
    def __init__(self, temp_range_c=(0, 80), auto_focus=True, interpolate=True):
        """Initialize the CameraAMG88xx object.
        :param tuple temp_range_c: The camera's temperature range in Celsius.
          Defaults to the AMG88xx specification of 0 to 80 degrees Celsius.
        :param bool auto_focus: The autofocus enable state.
          Defaults to True (enabled).
        :param bool interpolate: Enable linear interpolation. Defaults to True."""
        self._range_min_c = temp_range_c[0]
        self._range_max_c = temp_range_c[1]
        self._auto_focus = auto_focus
        self._interpolate = interpolate

        self._sensor_axis = [8, 8]  # The size of the sensor element array axis (8x8)
        if self._interpolate:
            self._grid_axis = [
                (2 * self._sensor_axis[0]) - 1,
                (2 * self._sensor_axis[1]) - 1,
            ]
        else:
            self._grid_axis = self._sensor_axis

        # Initiate the AMG8833 Thermal Camera
        i2c = busio.I2C(board.SCL, board.SDA, frequency=400000)
        self._amg8833 = adafruit_amg88xx.AMG88XX(i2c)

        # Set up the 2-D sensor data narray
        self._sensor_data = np.array(
            range(self._sensor_axis[0] * self._sensor_axis[1])
        ).reshape((self._sensor_axis[0], self._sensor_axis[1]))

        # Load the 2-D display color index narray with a spectrum
        self._grid_data = np.array(
            range(self._grid_axis[0] * self._grid_axis[1], 0, -1)
        ).reshape((self._grid_axis[0], self._grid_axis[1])) / (
            self._grid_axis[0] * self._grid_axis[1]
        )
        self._sensor_min_c = 0
        self._sensor_avg_c = 0
        self._sensor_max_c = 0

    @property
    def autofocus(self):
        """The autofocus mode."""
        return self._auto_focus

    @autofocus.setter
    def autofocus(self, new_focus):
        """Enable or disable the autofocus mode.
        :param bool new_focus: The autofocus enable state. No default."""
        self._auto_focus = new_focus

    @property
    def interpolate(self):
        """The interpolation mode."""
        return self._interpolate

    @interpolate.setter
    def interpolate(self, new_interpolate=True):
        """Enable or disable the interpolation function.
        :param bool new_interpolate: The interpolation enable state. Defaults to True.
        """
        self._interpolate = new_interpolate

    @property
    def statistics(self):
        """Calculate the minimum, average, and maximum sensor
        values of the latest camera acquisition."""
        return self._sensor_min_c, self._sensor_avg_c, self._sensor_max_c

    @property
    def sensor_axis(self):
        """The sensor axis sizes. Returns a tuple of the x-axis and
        y-axis sizes."""
        return self._sensor_axis

    @property
    def grid_axis(self):
        """Resultant grid axis sizes. Returns a tuple of the x-axis and
        y-axis sizes."""
        return self._grid_axis

    @property
    def grid_data(self):
        """An two-dimensional np.array containing grid data."""
        return self._grid_data

    def acquire(self):
        """Read the camera and return an array of interpolated and normalized
        grid values."""
        sensor = self._amg8833.pixels  # Obtain sensor data

        # Put sensor data into an array; limit value to the sensor's range
        self._sensor_data = np.clip(
            np.array(sensor), self._range_min_c, self._range_max_c
        )

        # Adjust the array for display
        # self._sensor_data = self._sensor_data.transpose()  # Swaps vertical and horizontal axes
        self._sensor_data = np.flip(self._sensor_data, axis=0)  # Flip vertical
        self._sensor_data = np.flip(self._sensor_data, axis=1)  # Flip horizontal

        # Calculate statistics
        self._sensor_min_c = np.min(self._sensor_data)
        self._sensor_avg_c = np.mean(self._sensor_data)
        self._sensor_max_c = np.max(self._sensor_data)

        # Autofocus normalization
        if self._auto_focus:
            self._sensor_data = (self._sensor_data - self._sensor_min_c) / (
                self._sensor_max_c - self._sensor_min_c
            )
        else:
            self._sensor_data = (self._sensor_data - self._range_min_c) / (
                self._range_max_c - self._range_min_c
            )

        # Interpolate the sensor data; place in the grid data array
        if self._interpolate:
            # Copy sensor data to the grid array for interpolation
            self._grid_data[::2, ::2] = self._sensor_data
            self._ulab_bilinear_interpolation()
            return self._grid_data
        return self._sensor_data

    def _ulab_bilinear_interpolation(self):
        """2x bilinear interpolation to upscale the sensor data array; by @v923z
        and @David.Glaude."""
        self._grid_data[1::2, ::2] = self._sensor_data[:-1, :]
        self._grid_data[1::2, ::2] += self._sensor_data[1:, :]
        self._grid_data[1::2, ::2] /= 2
        self._grid_data[::, 1::2] = self._grid_data[::, :-1:2]
        self._grid_data[::, 1::2] += self._grid_data[::, 2::2]
        self._grid_data[::, 1::2] /= 2
