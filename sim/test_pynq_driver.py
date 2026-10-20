"""Host tests for packing and driver behaviour using a controlled MMIO fake.

These tests do not replace the XSim AXI tests or testing on a physical board.
"""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np


class FakeArray:
    def __init__(self, owner):
        self.owner = owner
        self.data = np.zeros(16384, dtype=np.uint32)

    def __setitem__(self, key, value):
        self.data[key] = value
        if key.start == 1024 and key.stop == 1220:
            self.owner.loaded = 784


class FakeMMIO:
    def __init__(self):
        self.array = FakeArray(self)
        self.status = 0
        self.loaded = 0
        self.remaining = 0
        self.hang = False
        self.writes = []

    def read(self, offset):
        if offset == 0x04:
            if self.status & 1 and not self.hang:
                if self.remaining:
                    self.remaining -= 1
                else:
                    self.status = 10
            return self.status
        return {0x18: 0x4D4C5031, 0x14: 784, 0x1C: self.loaded,
                0x08: 7, 0x0C: 110208, 0x10: 100000000, 0x24: 0}.get(offset, 0)

    def write(self, offset, value):
        self.writes.append((offset, value))
        if offset == 0 and value == 1:
            self.status = 9
            self.remaining = 2
        elif offset == 0 and value == 2:
            self.status &= ~6
        elif offset == 0 and value == 4:
            self.status = 0
            self.loaded = 0


class FakeDefaultIP:
    def __init__(self, description):
        self.mmio = description["mmio"]


pynq_stub = types.ModuleType("pynq")
pynq_stub.DefaultIP = FakeDefaultIP
pynq_stub.Overlay = lambda path: None
sys.modules["pynq"] = pynq_stub
path = Path(__file__).resolve().parents[1] / "pynq/mnist_driver.py"
spec = importlib.util.spec_from_file_location("host_mnist_driver", path)
driver = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = driver
spec.loader.exec_module(driver)


class DriverTests(unittest.TestCase):
    def test_little_endian_and_full_image(self):
        pixels = np.arange(784, dtype=np.uint16) % 256
        words = driver.pack_pixels(pixels)
        self.assertEqual(int(words[0]), 0x03020100)
        self.assertEqual(words.shape, (196,))
        np.testing.assert_array_equal(words.view(np.uint8), pixels.astype(np.uint8))

    def test_non_contiguous_image(self):
        pixels = (np.arange(784, dtype=np.uint16).reshape(28, 28) % 256)[:, ::-1]
        words = driver.pack_pixels(pixels)
        np.testing.assert_array_equal(words.view(np.uint8), pixels.flatten().astype(np.uint8))

    def test_reject_bad_shape_range_and_float(self):
        for pixels in (np.zeros((27, 28), dtype=np.uint8), np.full(784, -1),
                       np.full(784, 256), np.zeros(784, dtype=np.float32)):
            with self.assertRaises(ValueError):
                driver.pack_pixels(pixels)

    def test_predict_upload_ack_and_timing(self):
        mmio = FakeMMIO()
        ip = driver.MnistMLP({"mmio": mmio})
        pixels = (np.arange(784) % 256).astype(np.uint8)
        result = ip.predict(pixels)
        self.assertEqual(result.digit, 7)
        self.assertEqual(result.cycles, 110208)
        self.assertAlmostEqual(result.compute_ms, 1.10208)
        self.assertGreaterEqual(result.total_ms, result.upload_ms)
        np.testing.assert_array_equal(mmio.array.data[1024:1220].view(np.uint8), pixels)
        self.assertEqual(mmio.writes, [(0, 2), (0, 1), (0, 2)])

    def test_busy_and_timeout(self):
        mmio = FakeMMIO()
        ip = driver.MnistMLP({"mmio": mmio})
        mmio.hang = True
        mmio.status = 1
        with self.assertRaises(RuntimeError):
            ip.predict(np.zeros(784, dtype=np.uint8))
        mmio.status = 0
        mmio.hang = True
        with patch.object(driver, "monotonic", side_effect=[0.0, 1.0]):
            with self.assertRaises(TimeoutError):
                ip.predict(np.zeros(784, dtype=np.uint8), timeout=0.5)

    def test_soft_reset_and_invalid_timeout(self):
        mmio = FakeMMIO()
        ip = driver.MnistMLP({"mmio": mmio})
        mmio.status = 9
        mmio.loaded = 784
        ip.soft_reset()
        self.assertEqual(mmio.loaded, 0)
        with self.assertRaises(ValueError):
            ip.predict(np.zeros(784, dtype=np.uint8), timeout=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
