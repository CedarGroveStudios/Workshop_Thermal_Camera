# SPDX-FileCopyrightText: 2025 JG for Cedar Grove Maker Studios
# SPDX-License-Identifier: MIT

"""
`mlx90640.py` AMG88xx thermal camera object.
"""

import board
import busio
from ulab import numpy as np
import adafruit_mlx90640


class CameraMLX90640:
    def __init__(self, temp_range_c=(-40, 300), auto_focus=True):
        """Initialize the CameraAMG88xx object.
        :param tuple temp_range_c: The camera's temperature range in Celsius.
          Defaults to the MLX90640 specification of -40 to 300 degrees Celsius.
        :param bool auto_focus: The autofocus enable state.
          Defaults to True (enabled)."""
        self._range_min_c = temp_range_c[0]
        self._range_max_c = temp_range_c[1]
        self._auto_focus = auto_focus

        self._sensor_axis = [32, 24]  # The size of the sensor element array axis (32x24)
        self._grid_axis = self._sensor_axis  # No interpolation for this camerra

        # Initiate the MLX90640 Thermal Camera
        i2c = busio.I2C(board.SCL, board.SDA, frequency=800_000)  # orig 800_000
        self._mlx90640 = adafruit_mlx90640.MLX90640(i2c)
        self._mlx90640.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_2_HZ  # 0.5 to 64Hz available

        # Set up the 2-D sensor data narray
        self._sensor_data = np.array(range(self._sensor_axis[0] * self._sensor_axis[1])).reshape((self._sensor_axis[0], self._sensor_axis[1]))

        # Load the 2-D display color index narray with a spectrum
        self._grid_data = np.array(range(self._grid_axis[0] * self._grid_axis[1])).reshape((self._grid_axis[0], self._grid_axis[1])) / (self._grid_axis[0] * self._grid_axis[1])
        self._grid_data = self._grid_data[::-1, ::-1]

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
        #sensor = [0] * 768  # Prepare an empty sensor frame buffer list
        sensor = np.array(range(self._sensor_axis[0] * self._sensor_axis[1]))
        success = False
        while not success:
            self._mlx90640.getFrame(sensor)
            success = True

        sensor = sensor.reshape((self._sensor_axis[0], self._sensor_axis[1]))

        # Put sensor data into an array; limit value to the sensor's range
        self._sensor_data = np.clip(
            np.array(sensor[::-1]), self._range_min_c, self._range_max_c
        )

        self._sensor_data = self._sensor_data[::-1, ::-1]  # Flip vertical

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
        return self._sensor_data
