# SPDX-FileCopyrightText: 2025 JG for Cedar Grove Maker Studios
# SPDX-License-Identifier: MIT

"""
`wtc_code.py`  AIO-connected Workshop Thermal Camera (WTC).
Rename to code.py and store in the device's root directory.
"""

import time
import os
import gc
import board
import struct
import rtc
import ssl
import supervisor
import adafruit_connection_manager
import wifi
import adafruit_requests
from adafruit_io.adafruit_io import IO_HTTP
import neopixel
from analogio import AnalogIn
from digitalio import DigitalInOut, Direction
import adafruit_binascii as binascii
from simpleio import map_range

from wtc_display import Display, WeekDayMonth, Colors
from camera_amg88xx import CameraAMG88xx


def celsius_to_fahrenheit(deg_c=None):
    """Convert C to F; round to 1 degree C"""
    return round(((9 / 5) * deg_c) + 32)


def fahrenheit_to_celsius(deg_f=None):
    """Convert F to C; round to 1 degree F"""
    return round((deg_f - 32) * (5 / 9))


# --- SYSTEM PARAMETERS ---
BRIGHTNESS = 1.0  # 0.0 (min) to 1.0 (max)
AUTO_DISPLAY_BRIGHT = True  # Use sensor to adjust per ambient lighting
DISPLAY_IMAGE = True  # Display mode; True for image, False for histogram
SELFIE = True  # Screen orientation; True for forward-facing camera

GRID_SIZE = (240, 240)  # Size of grid area (pixels)
GRID_OFFSET = (0, 0)  # Grid area offset (pixels)
PALETTE_SIZE = 100  # Number of display colors in spectral palette (must be > 0)
CELL_OUTLINE = 0  # Size of cell outline in pixels

AIO_IMAGE_FEED = "shop-camera.thermal-camera"  # Thermal camera bitmap image

LOCAL_TIME_UPDATE = 0  # Once per hour at the top of the hour
IMAGE_UPLOAD_PERIOD = 20  # Every 20 minutes and once at startup

# Default motion threshold, alarm, and min/max range values
ALARM_F = 120
MIN_RANGE_F = 60
MAX_RANGE_F = 120
MOTION_THRESH_C = 1.5
ALARM_C = fahrenheit_to_celsius(ALARM_F)
MIN_RANGE_C = fahrenheit_to_celsius(MIN_RANGE_F)
MAX_RANGE_C = fahrenheit_to_celsius(MAX_RANGE_F)

# Define the state/mode pixel colors
STARTUP = Colors.PURPLE
NORMAL = Colors.GREEN
FETCH = Colors.YELLOW
ERROR = Colors.RED

# --- CONNECT PERIPHERALS ---
# Instantiate the AMG8833 thermal camera module; 0 to 80C, autofocus, interpolate
camera = CameraAMG88xx(auto_focus=True, interpolate=True)

# Instantiate the display and load a sample spectrum
display = Display(
    grid_size=GRID_SIZE,
    grid_offset=GRID_OFFSET,
    grid_axis=camera.grid_axis,
    palette_size=PALETTE_SIZE,
    cell_outline=CELL_OUTLINE,
)
display.brightness = BRIGHTNESS
display.update_image_frame(camera.grid_data)  # Display the sample spectrum
display.alert("IRON")

# Instantiate the red LED
led = DigitalInOut(board.LED)
led.direction = Direction.OUTPUT
led.value = False

# Instantiate the NeoPixel
pixels = neopixel.NeoPixel(board.NEOPIXEL, 1)
pixels[0] = STARTUP
pixels.brightness = BRIGHTNESS

# Instantiate the ALS-PT19 light sensor for auto display brightness
light_sensor = AnalogIn(board.A3)


def _send_b64_to_aio(data):
    """Convert byte array to base64 and send to AIO feed.
    :param bytearray data: The byte array to be sent. No default."""
    pixels[0] = FETCH
    # Strip off newline character and encode
    b64_data = binascii.b2a_base64(data).strip().decode("utf-8")
    try:
        while io.get_remaining_throttle_limit() <= 10:
            busy(1)  # Wait until throttle limit increases
        io.send_data(AIO_IMAGE_FEED, b64_data)  # Send to AIO
        pixels[0] = NORMAL
    except:
        soft_reset(error="", desc="AIO Publish or Throttle Query")
    pixels[0] = NORMAL


def acquire_and_display():
    """Acquire and display the camera image."""
    global time_to_acquire, time_to_display, t_max
    time_to_acquire = time.monotonic()  # Time marker: Acquire Sensor Data
    grid_data = camera.acquire()  # Get camera sensor array data
    time_to_acquire = time.monotonic() - time_to_acquire

    # Update and display alarm setting and max, min, and ave stats
    time_to_display = time.monotonic()  # Time marker: Display Image
    t_min, t_avg, t_max = camera.statistics
    display.alarm_value.text = str(ALARM_F)
    display.max_value.text = str(celsius_to_fahrenheit(t_max))
    display.min_value.text = str(celsius_to_fahrenheit(t_min))
    display.avg_value.text = str(celsius_to_fahrenheit(t_avg))

    # Display image or histogram
    if DISPLAY_IMAGE:
        display.update_image_frame(grid_data, selfie=SELFIE)
    else:
        display.update_histo_frame(grid_data)
    time_to_display = time.monotonic() - time_to_display


def adjust_brightness():
    """Acquire the ALS-PT19 light sensor value and gradually adjust display
    brightness based on ambient light. The display brightness ranges from 0.05
    to BRIGHTNESS when the ambient light level falls between 5 and 200 lux.
    Full-scale raw light sensor value (65535) is approximately 1500 Lux."""
    global old_brightness
    if not AUTO_DISPLAY_BRIGHT:
        return
    raw = 0
    for i in range(20):
        raw = raw + light_sensor.value

    target_brightness = round(
        map_range(raw / 20 / 65535 * 1500, 5, 200, 0.3, BRIGHTNESS), 3
    )
    new_brightness = round(
        old_brightness + ((target_brightness - old_brightness) / 5), 3
    )
    display.brightness = new_brightness
    pixels.brightness = new_brightness
    old_brightness = new_brightness


def busy(delay):
    """An alternative 'time.sleep' function that blinks the LED once per second.
    A blocking method.
    :param float delay: The time delay in seconds. No default."""
    for blinks in range(int(round(delay, 0))):
        led.value = True
        time.sleep(0.498)
        led.value = False
        time.sleep(0.500)


def capture_grid_and_upload():
    """Build a bitmap image formatted bytearray of the displayed grid and
    send to the AIO camera feed."""
    global time_to_capture
    time_to_capture = time.monotonic()  # Time marker: Capture Bitmap
    pixels[0] = FETCH
    print("Creating Bitmap Image...")
    width = display.grid_axis[0]
    height = display.grid_axis[1]
    file_size = 54 + height * display.bytes_per_row(width)
    # Build the Bitmap BMP Header
    bmp_header = (
        bytes("BM", "ascii")
        + struct.pack("<I", file_size)
        + b"\00\x00"
        + b"\00\x00"
        + struct.pack("<I", 54)
    )
    # Build the Bitmap DIB Header
    dib_header = (
        struct.pack("<I", 40)
        + struct.pack("<I", width)
        + struct.pack("<I", height)
        + struct.pack("<H", 1)
        + struct.pack("<H", 24)
    )
    for _ in range(24):
        dib_header += b"\x00"
    # Build the Grid Image Data
    grid_bmp_data = b""  # Create blank byte array
    for _row in range(height - 1, -1, -1):
        _row_colors = display.fetch_grid_row_bgr_colors(_row, selfie=SELFIE & DISPLAY_IMAGE)
        grid_bmp_data += _row_colors
    # Convert to base 64 and send to AIO
    _send_b64_to_aio(bmp_header + dib_header + grid_bmp_data)
    print("... Done.")
    pixels[0] = NORMAL
    time_to_capture = time.monotonic() - time_to_capture


def soft_reset(error="", desc="", delay=30):
    """Soft reset of MCU. The terminal session and system time are preserved.
    Display switches to REPL and shows error code string.
    :param union(Exception, str) error: The exception error string. Defaults to blank string.
    :param str desc: The error description string. Defaults to blank string.
    :param int delay: The time delay before soft reset (seconds). Defaults
    to 30 seconds."""
    pixels[0] = ERROR  # Light NeoPixel with error color
    display.image_group = None  # Show the REPL
    print(f"  FAIL: {desc} Error: {str(error)}")
    print(f"    MCU will soft reset in {delay} seconds.")
    busy(delay)
    supervisor.reload()  # soft reset: keeps the terminal session alive


def update_local_time(update=False):
    """Refresh the local clock information. Update from AIO is optional.
    :param bool update: Fetch fresh clock information from AIO.
    Defaults to False."""
    if update:
        pixels[0] = FETCH
        try:
            rtc.RTC().datetime = time.struct_time(
                io.receive_time(os.getenv("TIMEZONE"))
            )
        except Exception as time_error:
            soft_reset(error=time_error, desc="Update Local Time")
    local_time = f"{time.localtime().tm_hour:2d}:{time.localtime().tm_min:02d}"
    wday = time.localtime().tm_wday
    month = time.localtime().tm_mon
    day = time.localtime().tm_mday
    year = time.localtime().tm_year
    combined = (
        f"{local_time} {WeekDayMonth.WEEKDAY[wday]}  {WeekDayMonth.MONTH[month - 1]} "
        + f"{day:02d}, {year:04d}"
    )
    if update:
        print(f"Time: {combined}")
    pixels[0] = NORMAL
    return combined


# --- PRIMARY PROCESS SETUP ---
# Define global variables
old_brightness = BRIGHTNESS
t_max = 0
time_to_acquire = 0
time_to_display = 0
time_to_capture = 0

# Connect to Wi-Fi
try:
    pixels[0] = FETCH
    # Connect to Wi-Fi access point
    print(f"Connect to {os.getenv('CIRCUITPY_WIFI_SSID')}")
    wifi.radio.connect(
        os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD")
    )
    pixels[0] = STARTUP
    print("  CONNECTED to WiFi")
except Exception as wifi_access_error:
    soft_reset(error=wifi_access_error, desc="WiFi Access")

# Create an instance of the Adafruit IO HTTP client
#   see https://docs.circuitpython.org/projects/adafruitio/en/stable/api.html
print("Connect to the AIO HTTP service")
# Initialize a socket pool and requests session
try:
    pixels[0] = FETCH
    pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
    requests = adafruit_requests.Session(pool, ssl.create_default_context())
    io = IO_HTTP(os.getenv("AIO_USERNAME"), os.getenv("AIO_KEY"), requests)
    pixels[0] = STARTUP
    print("  CONNECTED to AIO HTTP Service")
except Exception as aio_client_error:
    soft_reset(error=aio_client_error, desc="AIO Client")

_ = update_local_time(update=True)  # Update local time from Internet

state_LocalTimeUpdated = False  # Reset the local time updated state
state_ImageUploaded = False  # Reset the image uploaded state
old_t_max = 0  # Create maximum temp history variable; causes image upload

# --- PRIMARY PROCESS LOOP ---
while True:
    pixels[0] = NORMAL
    time_to_frame = time.monotonic()
    adjust_brightness()

    acquire_and_display()  # Get camera data and display image

    # If alarm threshold is reached, upload image and flash NeoPixels
    if t_max >= ALARM_C:
        display.alert("ALARM")
        capture_grid_and_upload()
        pixels.fill(Colors.RED)
        pixels.fill(Colors.BLACK)

    # Check for motion and upload if detected
    if t_max > old_t_max + MOTION_THRESH_C:
        display.alert("MOTION Detected")
        time.sleep(0.5)  # Wait for motion to come into frame
        acquire_and_display()  # Re-acquire camera image
        capture_grid_and_upload()
    old_t_max = t_max

    # Update local time from the Internet hourly
    if time.localtime().tm_min == LOCAL_TIME_UPDATE and not state_LocalTimeUpdated:
        update_local_time()
        state_LocalTimeUpdated = True
        print("Local Time Updated")
    if time.localtime().tm_min == LOCAL_TIME_UPDATE + 1 and state_LocalTimeUpdated:
        # Reset state_LocalTimeUpdated a minute later
        state_LocalTimeUpdated = False

    # Upload static image every IMAGE_UPLOAD_PERIOD minutes
    if time.localtime().tm_min % IMAGE_UPLOAD_PERIOD == 0 and not state_ImageUploaded:
        capture_grid_and_upload()
        state_ImageUploaded = True
        print("Image Uploaded to AIO")
    if time.localtime().tm_min % IMAGE_UPLOAD_PERIOD == 1 and state_ImageUploaded:
        # Reset state_ImageUploaded a minute later
        state_ImageUploaded = False

    gc.collect()
    time_to_frame = time.monotonic() - time_to_frame

    # Print frame performance report
    print("*** Performance Statistics ***")
    print(f"   {update_local_time()}")
    print(f"  time to capture: {time_to_capture:6.3f} sec")
    print("")
    print("                          rate")
    print(f" 1) acquire: {time_to_acquire:6.3f} sec  ", end="")
    print(f"{1 / time_to_acquire:5.1f}  /sec")
    print(f" 2) display: {time_to_display:6.3f} sec  ", end="")
    print(f"{1 / time_to_display:5.1f}  /sec")
    print("             =======")
    print(f"total frame: {time_to_frame:6.3f} sec  ", end="")
    print(f"{1 / time_to_frame:5.1f}   /sec")
    print("")
