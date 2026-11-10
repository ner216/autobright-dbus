#!/usr/bin/env python3
import sys
import os
import datetime
from pathlib import Path

import cv2
import numpy as np

from gi.repository import GLib
from pydbus import SystemBus



class Camera():
    def __init__(self, verbose: bool = False, camera_id: int = 0, warmup: int = 30):
        self.camera_id = camera_id
        self.warmup = warmup
        self.verbose = verbose
    
    def estimate(self) -> float:
        test_img = self._get_img()

        gray_img = cv2.cvtColor(test_img, cv2.COLOR_BGR2GRAY)
        mean = np.mean(gray_img)

        return mean

    def _get_img(self):
        # Device index of webcam is usually 0
        capture = cv2.VideoCapture(self.camera_id)

        if not capture.isOpened():
            sys.exit(f"Error, unable to access camera {self.camera_id}")

        # Disregard initial frames as camera focases
        for _ in range(self.warmup):
            ret, frame = capture.read()
            if not ret:
                sys.exit(f"Error, unable to read warmup frame")

        ret, frame = capture.read()
        if not ret:
            sys.exit(f"Error, unable to read test frame")
        return frame

class SystemConfig:
    def __init__(self, display_device_path: Path = Path("/sys/class/backlight/"), keyboard_backlight_path: Path = Path("/sys/class/firmware-attributes/dell-wmi-sysman/attributes/KeyboardIllumination/")):
        self.display_device = Path(os.path.join(display_device_path, os.listdir(display_device_path)[0]))
        self.keyboard_backlight = Path(keyboard_backlight_path)

    def get_current_display_device(self) -> str:
        return self.display_device.name

    def get_display_device_max_brightness(self) -> int:
        max_brightness = int(self._read_value(os.path.join(self.display_device, "max_brightness")))
        return max_brightness

    def get_keyboard_backlight_values(self) -> dict:
        return {0: "Disabled", 1: "Dim", 2: "Bright"}

    def _read_value(self, path: Path):
        try:
            with open(path, "r") as file:
                v = file.read().strip()
                return v
        except FileNotFoundError:
            sys.exit(f"Error, {path} not found")
        except Exception as e:
            sys.exit(f"Error, Failed to read value at {path}")


class AutoBrightService:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.bus = SystemBus()
        self.session = self.bus.get("org.freedesktop.login1", "/org/freedesktop/login1/session/auto")
        self.camera = Camera(verbose=verbose)
        self.system_config = SystemConfig()
        self.last_estimation = None

    def value_to_percent(self,value: float, minimum: float = 0.10) -> float:
        brightness_lower_bound = 60
        brightness_upper_bound = 150

        adjusted_value = min(value - brightness_lower_bound, brightness_upper_bound)
        percent = adjusted_value / (brightness_upper_bound - brightness_lower_bound)

        if percent < minimum: percent = minimum
        return percent

    def adjust_brightness(self):
        if self.last_estimation is None or (datetime.datetime.now() - self.last_estimation).total_seconds() > 5:
            estimation = self.camera.estimate()
            self.last_estimation = datetime.datetime.now()

            percent = self.value_to_percent(estimation)
            display_device = self.system_config.get_current_display_device()
            display_device_max_brightness = self.system_config.get_display_device_max_brightness()
            new_brightness_value = max(100, int(percent * display_device_max_brightness))
            if self.verbose: print(f"[Verbose] New brightness: {new_brightness_value}")

            self.session.SetBrightness("backlight", display_device, new_brightness_value)
        else:
            print("[Info] Skipping brightness estimation, last estimation was less than 5 seconds ago.")

    def handle_screensaver_signal(self, sender, path, obj, iface, signal, params):
        if self.verbose: print(f"[Verbose] Received signal: {signal} from {sender} at {path}")

        if signal == "ActiveChanged" and params[0] == False:
            if self.verbose: print("[Verbose] Screen unlocked")
            self.adjust_brightness()

    def main(self):
        # Initial brightness adjustment on service start
        self.adjust_brightness()

        self.bus.con.signal_subscribe(
            None,
            "org.gnome.ScreenSaver",
            "ActiveChanged",
            "/org/gnome/ScreenSaver",
            None,
            0,
            self.handle_screensaver_signal
        )

        print("autobright-service started...")

        loop = GLib.MainLoop()
        try:
            loop.run()
        except KeyboardInterrupt:
            print("autobright-service stopped.")
            loop.quit()

if __name__ == "__main__":
    auto_bright = AutoBrightService(verbose=True)
    auto_bright.main()