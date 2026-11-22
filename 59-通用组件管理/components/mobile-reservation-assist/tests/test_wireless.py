"""无线 adb 能力测试：地址持久化、驱动回退、连接命令（不连真机）。"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _support  # noqa: F401

import mra
from phone_driver import u2_driver


class WirelessBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get("MRA_STATE_DIR")
        os.environ["MRA_STATE_DIR"] = self.tmp

    def tearDown(self) -> None:
        if self.old is None:
            os.environ.pop("MRA_STATE_DIR", None)
        else:
            os.environ["MRA_STATE_DIR"] = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)


class PersistTest(WirelessBase):
    def test_save_and_load(self) -> None:
        path = u2_driver.save_serial("192.168.1.141:5555")
        self.assertTrue(path.exists())
        self.assertEqual(u2_driver.load_saved_serial(), "192.168.1.141:5555")

    def test_load_missing_returns_empty(self) -> None:
        self.assertEqual(u2_driver.load_saved_serial(), "")

    def test_driver_uses_saved_serial(self) -> None:
        u2_driver.save_serial("10.0.0.2:5555")
        with mock.patch.dict(os.environ, {"MRA_DEVICE_SERIAL": "", "ANDROID_SERIAL": ""}):
            self.assertEqual(u2_driver.U2Driver().serial, "10.0.0.2:5555")

    def test_env_overrides_saved(self) -> None:
        u2_driver.save_serial("10.0.0.2:5555")
        with mock.patch.dict(os.environ, {"MRA_DEVICE_SERIAL": "ddad4c46"}):
            self.assertEqual(u2_driver.U2Driver().serial, "ddad4c46")


class ProbeTest(unittest.TestCase):
    def test_wifi_ip_parse(self) -> None:
        output = "192.168.1.0/24 dev wlan0 proto kernel scope link src 192.168.1.141"
        with mock.patch.object(u2_driver, "adb", return_value=output):
            self.assertEqual(u2_driver.wifi_ip(), "192.168.1.141")

    def test_wifi_ip_empty_when_no_device(self) -> None:
        with mock.patch.object(u2_driver, "adb", return_value=""):
            self.assertEqual(u2_driver.wifi_ip(), "")

    def test_wifi_ip_prefers_wlan0_over_cellular(self) -> None:
        output = (
            "10.82.154.240/30 dev rmnet_data2 proto kernel scope link src 10.82.154.242\n"
            "192.168.1.0/24 dev wlan0 proto kernel scope link src 192.168.1.141"
        )
        with mock.patch.object(u2_driver, "adb", return_value=output):
            self.assertEqual(u2_driver.wifi_ip("ddad4c46"), "192.168.1.141")

    def test_adb_connect_result(self) -> None:
        with mock.patch.object(u2_driver, "adb", return_value="connected to 1.2.3.4:5555"):
            self.assertTrue(u2_driver.adb_connect("1.2.3.4:5555"))
        with mock.patch.object(u2_driver, "adb", return_value="failed to connect"):
            self.assertFalse(u2_driver.adb_connect("1.2.3.4:5555"))


class ConnectCommandTest(WirelessBase):
    def test_connect_with_host(self) -> None:
        args = mra.build_parser().parse_args(["phone", "connect", "--host", "1.2.3.4"])
        with mock.patch.object(u2_driver, "adb_tcpip", return_value=""), \
                mock.patch.object(u2_driver, "adb_connect", return_value=True), \
                mock.patch.object(mra.time, "sleep", return_value=None):
            code = mra.cmd_phone(args)
        self.assertEqual(code, mra.EXIT_OK)
        self.assertEqual(u2_driver.load_saved_serial(), "1.2.3.4:5555")

    def test_connect_auto_detect_ip(self) -> None:
        args = mra.build_parser().parse_args(["phone", "connect"])
        with mock.patch.object(u2_driver, "wifi_ip", return_value="192.168.1.141"), \
                mock.patch.object(u2_driver, "adb_tcpip", return_value=""), \
                mock.patch.object(u2_driver, "adb_connect", return_value=True), \
                mock.patch.object(mra.time, "sleep", return_value=None):
            self.assertEqual(mra.cmd_phone(args), mra.EXIT_OK)
        self.assertEqual(u2_driver.load_saved_serial(), "192.168.1.141:5555")

    def test_connect_without_device(self) -> None:
        args = mra.build_parser().parse_args(["phone", "connect"])
        with mock.patch.object(u2_driver, "wifi_ip", return_value=""):
            self.assertEqual(mra.cmd_phone(args), mra.EXIT_ARG)

    def test_connect_failure_not_saved(self) -> None:
        args = mra.build_parser().parse_args(["phone", "connect", "--host", "1.2.3.4"])
        with mock.patch.object(u2_driver, "adb_tcpip", return_value=""), \
                mock.patch.object(u2_driver, "adb_connect", return_value=False), \
                mock.patch.object(mra.time, "sleep", return_value=None):
            self.assertEqual(mra.cmd_phone(args), mra.EXIT_GATE)
        self.assertEqual(u2_driver.load_saved_serial(), "")


if __name__ == "__main__":
    unittest.main()
