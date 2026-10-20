"""Host checks; these do not measure a camera or physical FPGA."""
import base64
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image, ImageDraw, ImageOps

import app
from inference import IntegerModel, RemoteEngine, read_signed_mem, validate_pixels
from preprocess import prepare_digit


ROOT = Path(__file__).resolve().parent.parent


def data_url(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def paper_digit(offset=(0, 0)):
    image = Image.new("L", (256, 256), 255)
    draw = ImageDraw.Draw(image)
    dx, dy = offset
    draw.line([(75 + dx, 55 + dy), (165 + dx, 55 + dy), (110 + dx, 205 + dy)], fill=0, width=12)
    return image


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = IntegerModel()

    def test_all_120_cases_and_all_three_layers_match_rtl_golden(self):
        folder = ROOT / "validation" / "fixtures"
        inputs = read_signed_mem(folder / "inputs.mem", 32, (120, 784)).astype(np.uint8)
        expected = [read_signed_mem(folder / name, 32, shape) for name, shape in (
            ("expected_l1.mem", (120, 128)), ("expected_l2.mem", (120, 64)), ("expected_l3.mem", (120, 10)))]
        for index, pixels in enumerate(inputs):
            for actual, wanted in zip(self.model.layers(pixels), expected):
                np.testing.assert_array_equal(actual, wanted[index], err_msg=f"Case {index}")

    def test_signed_weights_and_pixel_contract(self):
        self.assertLess(self.model.w1.min(), 0)
        self.assertGreater(self.model.w1.max(), 0)
        self.assertEqual(validate_pixels(np.zeros(784, np.uint8)).shape, (28, 28))
        for bad in (np.zeros((28, 28), np.float32), np.full(784, -1), np.full(784, 256), np.zeros(783, int)):
            with self.assertRaises(ValueError):
                validate_pixels(bad)

    def test_blank_paper_is_rejected(self):
        for value in (0, 128, 255):
            result = prepare_digit(Image.new("L", (256, 256), value))
            self.assertEqual(result.status, "no_digit")
            self.assertFalse(result.pixels.any())

    def test_shift_and_polarity_give_same_centered_pixels(self):
        base = prepare_digit(paper_digit())
        shifted = prepare_digit(paper_digit((20, -15)))
        inverted = prepare_digit(ImageOps.invert(paper_digit()), "light")
        self.assertEqual(base.status, "ok")
        self.assertEqual(base.pixels.dtype, np.uint8)
        np.testing.assert_array_equal(base.pixels, shifted.pixels)
        np.testing.assert_array_equal(base.pixels, inverted.pixels)
        yy, xx = np.indices((28, 28))
        self.assertLess(abs((base.pixels * xx).sum() / base.pixels.sum() - 13.5), 0.6)
        self.assertLess(abs((base.pixels * yy).sum() / base.pixels.sum() - 13.5), 0.6)

    def test_clipped_digit_is_rejected(self):
        image = Image.new("L", (256, 256), 255)
        ImageDraw.Draw(image).rectangle((0, 60, 20, 210), fill=0)
        self.assertEqual(prepare_digit(image).status, "invalid_roi")

    def test_small_camera_speckles_are_removed(self):
        clean = paper_digit()
        noisy = clean.copy()
        draw = ImageDraw.Draw(noisy)
        for x, y in ((25, 25), (230, 240), (25, 230)):
            draw.rectangle((x, y, x + 1, y + 1), fill=0)
        np.testing.assert_array_equal(prepare_digit(clean).pixels, prepare_digit(noisy).pixels)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = app.DemoService()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(cls.service))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def post(self, path, payload):
        request = Request(self.url + path, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_config_and_mnist_predictions(self):
        with urlopen(self.url + "/api/config") as response:
            config = json.load(response)
        self.assertEqual(config["backend"], "software")
        self.assertFalse(config["board_test_passed"])
        for digit in range(10):
            result = self.post("/api/sample", {"index": digit})
            self.assertEqual(result["digit"], digit)
            self.assertEqual(result["backend"], "software")
            self.assertNotIn("fpga_compute_ms", result)
            self.assertEqual(len(result["pixels"]), 784)

    def test_blank_frame_never_invokes_classifier(self):
        with patch.object(self.service, "infer", side_effect=AssertionError("Blank inference")):
            result = self.post("/api/predict", {"image": data_url(Image.new("L", (320, 320), 255))})
        self.assertEqual(result["status"], "no_digit")
        self.assertNotIn("digit", result)

    def test_real_preprocessing_http_path(self):
        result = self.post("/api/predict", {"image": data_url(paper_digit()), "polarity": "dark"})
        prepared = prepare_digit(paper_digit())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["digit"], self.service.model.predict(prepared.pixels)["digit"])
        self.assertEqual(result["pixels"], prepared.pixels.reshape(-1).tolist())

    def test_invalid_requests_and_static_path_whitelist(self):
        for path, body in (("/api/sample", {"index": 10}), ("/api/pixels", {"pixels": [1]}), ("/api/predict", {"image": "bad"})):
            with self.assertRaises(HTTPError) as caught:
                self.post(path, body)
            self.assertEqual(caught.exception.code, 400)
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.url + "/../inference.py")
        self.assertEqual(caught.exception.code, 404)

    def test_save_labeled_sample_roundtrip(self):
        pixels = self.service.samples[7]
        with tempfile.TemporaryDirectory() as folder, patch.object(app, "HERE", Path(folder)):
            result = self.post("/api/save", {"pixels": pixels.reshape(-1).tolist(), "label": 7})
            self.assertTrue(result["correct"])
            saved = Path(folder) / "captures" / result["saved"]
            np.testing.assert_array_equal(np.asarray(Image.open(saved.with_suffix(".png"))), pixels)
            record = json.loads(saved.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(record["backend"], "software")

    def test_remote_rejects_software_board_without_fallback(self):
        with self.assertRaises(ValueError):
            RemoteEngine(self.service.model, self.url)

    def test_mock_remote_protocol_and_reference_comparison(self):
        reference = IntegerModel()
        fake = SimpleNamespace(predict=lambda pixels: {
            **self.service.model.predict(pixels), "backend": "fpga", "fpga_compute_ms": 0.0})
        with patch.object(self.service, "backend", "fpga"), patch.object(self.service, "engine", fake):
            remote = RemoteEngine(reference, self.url)
            self.assertEqual(remote.predict(self.service.samples[7])["digit"], 7)
            fake.predict = lambda pixels: {"backend": "fpga", "digit": 3}
            with self.assertRaises(RuntimeError):
                remote.predict(self.service.samples[7])

    def test_mock_remote_hardware_error_is_exposed(self):
        def failure(pixels):
            raise RuntimeError("Mock FPGA unavailable")
        fake = SimpleNamespace(predict=failure)
        with patch.object(self.service, "backend", "fpga"), patch.object(self.service, "engine", fake):
            remote = RemoteEngine(IntegerModel(), self.url)
            with self.assertRaises(HTTPError) as caught:
                remote.predict(self.service.samples[7])
            self.assertEqual(caught.exception.code, 503)


if __name__ == "__main__":
    unittest.main(verbosity=2)
