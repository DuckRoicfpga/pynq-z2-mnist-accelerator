"""Integer MNIST reference and explicit FPGA backends; no automatic fallback."""
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from time import perf_counter
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import numpy as np


HERE = Path(__file__).resolve().parent


def validate_pixels(pixels):
    array = np.asarray(pixels)
    if array.shape not in ((28, 28), (784,)):
        raise ValueError("Ảnh đầu vào phải có 28 × 28 pixel.")
    if array.dtype.kind not in "ui" or np.any(array < 0) or np.any(array > 255):
        raise ValueError("Pixel phải là số nguyên từ 0 đến 255.")
    return np.ascontiguousarray(array.reshape(28, 28), dtype=np.uint8)


def read_signed_mem(path, bits, shape):
    words = np.array([int(t, 16) for t in path.read_text().split()], dtype=np.int64)
    if words.size != int(np.prod(shape)) or np.any(words < 0) or np.any(words >= 2**bits):
        raise ValueError(f"Sai kích thước hoặc độ rộng số trong {path.name}.")
    signed = np.where(words >= 2**(bits - 1), words - 2**bits, words)
    return signed.reshape(shape)


class IntegerModel:
    def __init__(self, folder=None):
        folder = Path(folder or HERE / "model")
        spec = json.loads((folder / "model.json").read_text(encoding="utf-8"))
        if spec["architecture"] != [784, 128, 64, 10]:
            raise ValueError("Kiến trúc model không khớp bộ tăng tốc hiện tại.")
        for name, expected in spec["sha256"].items():
            if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
                raise ValueError(f"Trọng số {name} không khớp model.json.")
        self.fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        self.spec = spec
        self.shift1, self.shift2 = spec["shifts"]
        self.w1 = read_signed_mem(folder / "fc1_weight.mem", 8, (128, 784))
        self.w2 = read_signed_mem(folder / "fc2_weight.mem", 8, (64, 128))
        self.w3 = read_signed_mem(folder / "fc3_weight.mem", 8, (10, 64))
        self.b1 = read_signed_mem(folder / "fc1_bias.mem", 32, (128,))
        self.b2 = read_signed_mem(folder / "fc2_bias.mem", 32, (64,))
        self.b3 = read_signed_mem(folder / "fc3_bias.mem", 32, (10,))

    def layers(self, pixels):
        x = validate_pixels(pixels).reshape(784).astype(np.int64)
        h1 = np.clip(np.maximum(self.w1 @ x + self.b1, 0) >> self.shift1, 0, 255)
        h2 = np.clip(np.maximum(self.w2 @ h1 + self.b2, 0) >> self.shift2, 0, 255)
        scores = self.w3 @ h2 + self.b3
        return h1, h2, scores

    def predict(self, pixels):
        started = perf_counter()
        scores = self.layers(pixels)[2]
        return {
            "digit": int(np.argmax(scores)),
            "inference_ms": (perf_counter() - started) * 1000,
            "backend": "software",
        }


class FpgaEngine:
    def __init__(self, model, bitfile):
        bitfile = Path(bitfile).resolve()
        for path, key in ((bitfile, "bit_sha256"), (bitfile.with_suffix(".hwh"), "hwh_sha256")):
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != model.spec[key]:
                raise ValueError("Cặp .bit/.hwh không khớp trọng số của bản demo này.")
        # Register the existing driver without shadowing PYNQ's installed package.
        spec = importlib.util.spec_from_file_location("camera_mnist_driver", HERE / "fpga" / "mnist_driver.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.overlay, self.accelerator = module.load_overlay(bitfile)
        self.model = model
        self.fingerprint = model.fingerprint

    def predict(self, pixels):
        result = asdict(self.accelerator.predict(validate_pixels(pixels)))
        expected = self.model.predict(pixels)["digit"]
        if result["digit"] != expected:
            raise RuntimeError(f"FPGA trả {result['digit']}, Python INT8 trả {expected}; cần kiểm chứng board.")
        return {
            "backend": "fpga", "digit": result["digit"],
            "inference_ms": result["total_ms"],
            "fpga_compute_ms": result["compute_ms"],
            "cycles": result["cycles"], "reference_match": True,
        }


class RemoteEngine:
    def __init__(self, model, board_url):
        parts = urlsplit(board_url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.query or parts.fragment:
            raise ValueError("--board-url cần dạng http://địa-chỉ-board:8766.")
        self.url = board_url.rstrip("/")
        self.model = model
        self.fingerprint = model.fingerprint
        with urlopen(self.url + "/api/config", timeout=3) as response:
            config = json.load(response)
        if config["backend"] != "fpga" or config["model_fingerprint"] != self.fingerprint:
            raise ValueError("Board phải chạy backend FPGA với cùng trọng số INT8.")

    def predict(self, pixels):
        pixels = validate_pixels(pixels)
        request = Request(self.url + "/api/pixels", data=json.dumps({"pixels": pixels.reshape(-1).tolist()}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=3) as response:
            result = json.load(response)
        expected = self.model.predict(pixels)["digit"]
        if result.get("backend") != "fpga" or result.get("digit") != expected:
            raise RuntimeError("Kết quả board không khớp Python INT8; demo không chuyển sang chạy CPU.")
        return result
