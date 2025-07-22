# SPDX-FileCopyrightText: 2025 JG for Cedar Grove Maker Studios
# SPDX-License-Identifier: MIT

"""
`wtc_display.py`  A display class for the workshop thermal camera.
"""

import time
import gc
import board
import fourwire
import pwmio
from ulab import numpy as np
import displayio
from simpleio import map_range
from adafruit_display_text.label import Label
from adafruit_bitmap_font import bitmap_font
from adafruit_display_shapes.rect import Rect
from index_to_rgb_iron import index_to_rgb


class WeekDayMonth:
    # fmt: off
    # A couple of day/month lookup tables
    WEEKDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", ]


class Colors:
    # fmt: off
    # Default colors
    BLACK = 0x000000
    BLUE = 0x0000FF
    BLUE_DK = 0x000080
    BLUE_LT = 0x000044
    BLUE_LT_LCARS = 0x07A2FF
    CYAN = 0x00FFFF
    GRAY = 0x444455
    GREEN = 0x00FF00
    GREEN_LT = 0x5dd82f
    ORANGE = 0xFF8811
    PINK = 0XEF5CA4
    PURPLE = 0xFF00FF
    RED = 0xFF0000
    VIOLET = 0x9900FF
    VIOLET_DK = 0x110022
    WHITE = 0xFFFFFF
    YELLOW = 0xFFFF00

    WIND = 0x00e7ce
    GUSTS = 0xfd614a
    # fmt: on


class Display:
    """A display class for the workshop thermal camera."""

    def __init__(
        self,
        tft="2.4-inch",
        rotation=0,
        brightness=1.0,
        grid_size=(64, 64),
        grid_offset=(0, 0),
        grid_axis=(15, 15),
        palette_size=100,
        cell_outline=False,
    ):
        self._backlite = pwmio.PWMOut(board.TX, frequency=500)
        self._backlite.duty_cycle = 0xFFFF  # Reduce brightness during initialization

        self._brightness = brightness
        self._rotation = rotation
        self._grid_size = grid_size
        self._grid_offset = grid_offset
        self._grid_axis = grid_axis
        self._palette_size = palette_size
        self._cell_outline = cell_outline

        # Calculate grid parameters; size of a grid cell in pixels
        self._cell_size = min(
            self._grid_size[0] // self._grid_axis[0],
            self._grid_size[1] // self._grid_axis[1],
        )
        self._cell_size = [self._cell_size, self._cell_size]

        if "2.4" in tft:
            # Instantiate the 2.4" TFT FeatherWing Display
            import adafruit_ili9341  # 2.4" TFT FeatherWing

            displayio.release_displays()  # Release display resources
            display_bus = fourwire.FourWire(
                board.SPI(), command=board.D10, chip_select=board.D9, reset=None
            )
            self._display = adafruit_ili9341.ILI9341(display_bus, width=320, height=240)
        else:
            # Instantiate the 3.5" TFT FeatherWing Display
            import adafruit_hx8357  # 3.5" TFT FeatherWing

            displayio.release_displays()  # Release display resources
            display_bus = fourwire.FourWire(
                board.SPI(), command=board.D10, chip_select=board.D9, reset=None
            )
            self._display = adafruit_hx8357.HX8357(display_bus, width=480, height=320)

        self._display.rotation = self._rotation
        self.width = self._display.width
        self.height = self._display.height

        font_0 = bitmap_font.load_font("/fonts/Arial_16.bdf")

        # Define the display group
        self.image_group = displayio.Group(scale=1)
        self._display.root_group = self.image_group  # Load display

        # Define the foundational thermal image grid cells; image_group[0:224]
        #   image_group[#] = image_group[ (row * self._grid_axis) + column ]
        for row in range(self._grid_axis[1]):
            for col in range(self._grid_axis[0]):
                cell_x = (col * self._cell_size[0]) + self._grid_offset[0]
                cell_y = (row * self._cell_size[1]) + self._grid_offset[1]
                cell = Rect(
                    x=cell_x,
                    y=cell_y,
                    width=self._cell_size[0],
                    height=self._cell_size[1],
                    fill=Colors.PURPLE,
                    outline=Colors.BLACK,
                    stroke=self._cell_outline,
                )
                self.image_group.append(cell)

        # Define labels and values
        self.status_label = Label(font_0, text="", color=None)
        self.status_label.anchor_point = (0.5, 1)
        self.status_label.anchored_position = (
            (self._grid_size[0] + self._grid_offset[0]) // 2,
            self.height,
        )
        self.image_group.append(self.status_label)  # image_group[225]

        self.alarm_value = Label(font_0, text="---", color=Colors.WHITE)
        self.alarm_value.anchor_point = (1, 0)
        self.alarm_value.anchored_position = (self.width - 5, 5)
        self.image_group.append(self.alarm_value)  # image_group[226]

        self.alarm_label = Label(font_0, text="alarm", color=Colors.WHITE)
        self.alarm_label.anchor_point = (1, 0)
        self.alarm_label.anchored_position = (self.width - 5, 30)
        self.image_group.append(self.alarm_label)  # image_group[227]

        self.max_value = Label(font_0, text="---", color=Colors.RED)
        self.max_value.anchor_point = (1, 0)
        self.max_value.anchored_position = (self.width - 5, 65)
        self.image_group.append(self.max_value)  # image_group[228]

        self.max_label = Label(font_0, text="max", color=Colors.RED)
        self.max_label.anchor_point = (1, 0)
        self.max_label.anchored_position = (self.width - 5, 90)
        self.image_group.append(self.max_label)  # image_group[229]

        self.avg_value = Label(font_0, text="---", color=Colors.YELLOW)
        self.avg_value.anchor_point = (1, 0)
        self.avg_value.anchored_position = (self.width - 5, 125)
        self.image_group.append(self.avg_value)  # image_group[230]

        self.avg_label = Label(font_0, text="avg", color=Colors.YELLOW)
        self.avg_label.anchor_point = (1, 0)
        self.avg_label.anchored_position = (self.width - 5, 150)
        self.image_group.append(self.avg_label)  # image_group[231]

        self.min_label = Label(font_0, text="min", color=Colors.CYAN)
        self.min_label.anchor_point = (1, 0)
        self.min_label.anchored_position = (self.width - 5, 210)
        self.image_group.append(self.min_label)  # image_group[232]

        self.min_value = Label(font_0, text="---", color=Colors.CYAN)
        self.min_value.anchor_point = (1, 0)
        self.min_value.anchored_position = (self.width - 5, 185)
        self.image_group.append(self.min_value)  # image_group[233]

        # Set backlight to brightness after initialization
        self._backlite.duty_cycle = int(self._brightness * 0xFFFF)
        gc.collect()

    @property
    def display(self):
        """The display object."""
        return self._display

    @property
    def brightness(self):
        """The TFT display brightness."""
        return self._brightness

    @brightness.setter
    def brightness(self, brightness=1.0):
        """Set the TFT display brightness.
        :param float brightness: The display brightness.
          Defaults to full intensity (1.0)."""
        self._brightness = brightness
        self._backlite.duty_cycle = int(brightness * 0xFFFF)

    @property
    def rotation(self):
        """The TFT display rotation in degrees."""
        return self._rotation

    @rotation.setter
    def rotation(self, rot=180):
        """Set the TFT display rotation.
        :param int rot: The display rotation in degrees. Defaults to 180."""
        self._rotation = rot
        self.display.rotation = rot

    def alert(self, text=""):
        """Display alert message in status area. Default is a blank message.
        :param str text: The text to display. No default."""
        msg_text = text[:20]
        if msg_text == "" or msg_text is None:
            msg_text = ""
            self.status_label.text = msg_text
        else:
            print("ALERT: " + msg_text)  # Print alert text in the REPL
            self.status_label.color = Colors.RED
            self.status_label.text = msg_text
            time.sleep(0.1)
            self.status_label.color = Colors.YELLOW
            time.sleep(0.1)
            self.status_label.color = Colors.RED
            time.sleep(0.1)
            self.status_label.color = Colors.YELLOW
            time.sleep(0.5)
            self.status_label.color = None

    @property
    def grid_axis(self):
        return self._grid_axis

    def update_image_frame(self, grid_data, selfie=False):
        """Get normalized camera data and update the display.
        :param np.array grid_data: Two-dimensional list of grid values. No
          default.
        :param bool selfie: The camera is forward-facing. Defaults to False
          (selfie disabled)."""

        for _col in range(self._grid_axis[0]):
            for _row in range(self._grid_axis[1]):
                if selfie:
                    color_index = grid_data[_col][self._grid_axis[1] - 1 - _row]
                else:
                    color_index = grid_data[_col][_row]
                color = index_to_rgb(
                    round(color_index * self._palette_size, 0) / self._palette_size
                )
                group_index = (_col * self._grid_axis[1]) + _row
                if color != self.image_group[group_index].fill:
                    self.image_group[group_index].fill = color

    def update_histo_frame(self, grid_data):
        """Display a histogram from a grid data array.
        :param np.array grid_data: Two-dimensional list of grid values.
          No default."""

        histogram = np.zeros(self._grid_axis[0])  # Clear histogram accumulation array
        # Collect grid data and calculate the histogram
        for _row in range(0, self._grid_axis[1]):
            for _col in range(0, self._grid_axis[0]):
                histo_index = int(
                    map_range(grid_data[_col, _row], 0, 1, 0, self._grid_axis[0] - 1)
                )
                histogram[histo_index] = histogram[histo_index] + 1

        histo_scale = np.max(histogram) / (self._grid_axis[0] - 1)
        if histo_scale <= 0:
            histo_scale = 1

        # Display the histogram
        for _col in range(self._grid_axis[0]):
            for _row in range(self._grid_axis[1]):
                if histogram[_col] / histo_scale > self._grid_axis[0] - 1 - _row:
                    self.image_group[
                        ((_row * self._grid_axis[1]) + _col)
                    ].fill = index_to_rgb(round((_col / self._grid_axis[1]), 3))
                else:
                    self.image_group[
                        ((_row * self._grid_axis[1]) + _col)
                    ].fill = Colors.BLACK

    def bytes_per_row(self, source_width):
        """Calculate bytes per row of the pixel source.
        :param int source_width: The number of pixels per row. No default."""
        pixel_bytes = 3 * source_width
        padding_bytes = (4 - (pixel_bytes % 4)) % 4
        return pixel_bytes + padding_bytes

    def rgb888_to_bgr888_tuple(self, rgb_color):
        """Convert RGB888 value into three BGR888 bytes.
        :param int rgb_color: The RGB888 color value to convert. No default."""
        _red = (rgb_color >> 16) & 0xFF
        _grn = (rgb_color >> 8) & 0xFF
        _blu = (rgb_color >> 0) & 0xFF
        return _blu, _grn, _red

    def fetch_grid_row_bgr_colors(self, row, selfie=False):
        """Fetches a row of RGB colors from the image_group and returns a list of GBR
        values to be used to create a bitmap image. Reverses selfie image if needed.
        :param int row: The row address. No default.
        :param bool selfie: The camera is forward-facing. Defaults to False
          (selfie disabled)."""
        _row_buffer = np.zeros(self.bytes_per_row(self._grid_axis[0]), dtype=np.uint8)
        _buffer_index = 0
        if selfie:
            row_range = range(self._grid_axis[0] - 1, -1, -1)
        else:
            row_range = range(0, self._grid_axis[0])
        for _col in row_range:
            _rgb_color = self.image_group[((row * self._grid_axis[1]) + _col)].fill
            (
                _row_buffer[_buffer_index],
                _row_buffer[_buffer_index + 1],
                _row_buffer[_buffer_index + 2],
            ) = self.rgb888_to_bgr888_tuple(_rgb_color)
            _buffer_index += 3
        return _row_buffer
