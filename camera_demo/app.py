"""Camera demo on localhost. Camera starts only after the browser's Start button."""
import argparse
import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys
from threading import Lock
from time import perf_counter
from urllib.parse import urlsplit
import uuid

import numpy as np
from PIL import Image, UnidentifiedImageError

from inference import FpgaEngine, IntegerModel, RemoteEngine, validate_pixels
from preprocess import prepare_digit


HERE = Path(__file__).resolve().parent
MAX_BODY = 2_000_000


def decode_image(data_url):
    if not isinstance(data_url, str) or not data_url.startswith(("data:image/jpeg;base64,", "data:image/png;base64,")):
        raise ValueError("Ảnh cần ở định dạng JPEG hoặc PNG.")
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
        with Image.open(BytesIO(raw)) as opened:
            if opened.width * opened.height > 4_000_000:
                raise ValueError("Ảnh quá lớn; chọn ảnh tối đa 4 triệu pixel.")
            opened.load()
            if opened.mode in ("RGBA", "LA") or "transparency" in opened.info:
                rgba = opened.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                return Image.alpha_composite(background, rgba).convert("RGB")
            return opened.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Không đọc được ảnh JPEG/PNG.") from exc


class DemoService:
    def __init__(self, backend="software", board_url=None, bitfile=None):
        self.model = IntegerModel()
        self.backend = backend
        self.engine = self.model
        if backend == "fpga":
            self.engine = FpgaEngine(self.model, bitfile or HERE / "fpga" / "mnist_mlp.bit")
        elif backend == "remote":
            if not board_url:
                raise ValueError("Backend remote cần --board-url.")
            self.engine = RemoteEngine(self.model, board_url)
        elif backend != "software":
            raise ValueError("Backend không hợp lệ.")
        self.lock = Lock()
        self.board_test_passed = False
        with np.load(HERE / "test_images.npz", allow_pickle=False) as samples:
            self.samples = samples["images"].copy()
            self.expected = samples["expected_predictions"].copy()

    def config(self):
        return {"backend": self.backend, "model_fingerprint": self.model.fingerprint,
                "architecture": [784, 128, 64, 10], "board_test_passed": self.board_test_passed}

    def infer(self, pixels):
        with self.lock:
            return self.engine.predict(validate_pixels(pixels))

    def predict_image(self, payload):
        started = perf_counter()
        prepared = prepare_digit(decode_image(payload.get("image")), payload.get("polarity", "dark"))
        result = {"status": prepared.status, "message": prepared.message,
                  "pixels": prepared.pixels.reshape(-1).tolist(), "ink_fraction": prepared.ink_fraction}
        if prepared.status == "ok":
            result.update(self.infer(prepared.pixels))
        result["pipeline_ms"] = (perf_counter() - started) * 1000
        return result

    def sample(self, index):
        if not 0 <= index < len(self.samples):
            raise ValueError("Chọn mẫu từ 0 đến 9.")
        pixels = self.samples[index]
        started = perf_counter()
        return {"status": "ok", "message": "Ảnh MNIST mẫu; chưa phải ảnh camera.",
                "pixels": pixels.reshape(-1).tolist(), "expected": int(self.expected[index]),
                **self.infer(pixels), "pipeline_ms": (perf_counter() - started) * 1000}

    def self_test(self):
        predictions = [self.infer(pixels)["digit"] for pixels in self.samples]
        if predictions != self.expected.tolist():
            raise RuntimeError("Kiểm tra 10 ảnh mẫu không đạt.")
        if self.backend == "fpga":
            self.board_test_passed = True
        return {"passed": 10, "backend": self.backend, "predictions": predictions}

    def save_sample(self, payload):
        label = payload.get("label")
        if type(label) is not int or not 0 <= label <= 9:
            raise ValueError("Nhãn thật cần là số từ 0 đến 9.")
        pixels = validate_pixels(payload.get("pixels"))
        if not np.any(pixels):
            raise ValueError("Không lưu khung trống làm mẫu chữ số.")
        result = self.infer(pixels)
        folder = HERE / "captures"
        folder.mkdir(exist_ok=True)
        name = uuid.uuid4().hex
        Image.fromarray(pixels).save(folder / f"{name}.png")
        record = {"label": label, "model_fingerprint": self.model.fingerprint,
                  "created_utc": datetime.now(timezone.utc).isoformat(), **result}
        (folder / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"saved": name, "label": label, "digit": result["digit"], "correct": result["digit"] == label}


def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, value, status=200):
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urlsplit(self.path).path
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/demo.js": ("demo.js", "text/javascript; charset=utf-8")}
            if path in assets:
                name, mime = assets[path]
                raw = (HERE / "web" / name).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)
            elif path == "/api/config":
                self.respond(service.config())
            else:
                self.respond({"error": "Không tìm thấy trang."}, 404)

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BODY:
                    self.respond({"error": "Nội dung gửi lên quá lớn hoặc bị trống."}, 413)
                    return
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self.respond({"error": "API yêu cầu JSON."}, 415)
                    return
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("Nội dung JSON không hợp lệ.")
                path = urlsplit(self.path).path
                if path == "/api/predict":
                    result = service.predict_image(payload)
                elif path == "/api/sample":
                    index = payload.get("index")
                    if type(index) is not int:
                        raise ValueError("Chọn số mẫu từ 0 đến 9.")
                    result = service.sample(index)
                elif path == "/api/pixels":
                    result = service.infer(payload.get("pixels"))
                elif path == "/api/save":
                    result = service.save_sample(payload)
                else:
                    self.respond({"error": "Không tìm thấy API."}, 404)
                    return
                self.respond(result)
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                self.respond({"error": str(exc)}, 400)
            except Exception as exc:
                # Expose hardware/network failures; never substitute a software result.
                print(f"Demo error: {exc}", flush=True)
                self.respond({"error": "Nhận diện thất bại: " + str(exc)}, 503)

        def log_message(self, fmt, *args):
            if self.command != "POST":
                super().log_message(fmt, *args)

    return Handler


def main():
    for console in (sys.stdout, sys.stderr):
        if hasattr(console, "reconfigure"):
            console.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("software", "fpga", "remote"), default="software")
    parser.add_argument("--board-url")
    parser.add_argument("--bit", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--self-test", action="store_true", help="Check 10 MNIST samples before starting.")
    args = parser.parse_args()
    try:
        service = DemoService(args.backend, args.board_url, args.bit)
        if args.self_test:
            print(json.dumps(service.self_test()), flush=True)
        server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    except Exception as exc:
        parser.exit(1, f"Không khởi động được demo: {exc}\n")
    print(f"Camera demo: http://{args.host}:{args.port} | backend={args.backend}", flush=True)
    print("Camera chỉ mở khi em bấm Bật camera. Ctrl+C để dừng server.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
