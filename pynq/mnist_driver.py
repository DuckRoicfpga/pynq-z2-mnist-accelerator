"""Driver for the MNIST AXI4-Lite IP; import this before loading the overlay."""
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import perf_counter_ns, monotonic

import numpy as np
from pynq import DefaultIP, Overlay


def pack_pixels(pixels):
    """784 raw MNIST UINT8 pixels -> 196 little-endian UINT32 AXI words."""
    array = np.asarray(pixels)
    if array.shape not in ((28, 28), (784,)):
        raise ValueError("Ảnh cần có kích thước 28x28 hoặc vector 784 pixel.")
    if array.dtype.kind not in "ui" or np.any(array < 0) or np.any(array > 255):
        raise ValueError("Pixel cần là số nguyên 0..255, cùng cách biểu diễn MNIST đã train.")
    raw = np.ascontiguousarray(array.reshape(784), dtype=np.uint8)
    return raw.view("<u4").copy()


@dataclass(frozen=True)
class InferenceResult:
    digit: int
    cycles: int
    clock_hz: int
    compute_ms: float
    upload_ms: float
    total_ms: float


class MnistMLP(DefaultIP):
    bindto = ["mnist.local:user:mlp_axi_lite:1.0"]
    CONTROL, STATUS, RESULT, CYCLES = 0x00, 0x04, 0x08, 0x0C
    CLOCK, IMAGE_SIZE, ID, LOADED, DEBUG, ERROR, IRQ_ENABLE = (
        0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x28
    )
    PIXEL_BASE = 0x1000
    BUSY, DONE, ERROR_FLAG, IMAGE_READY = 1, 2, 4, 8
    ERROR_TEXT = {
        1: "accelerator đang bận",
        2: "chưa nạp đủ 784 pixel",
        3: "địa chỉ không hợp lệ",
        4: "ghi vào thanh ghi chỉ đọc",
    }

    def __init__(self, description):
        super().__init__(description)
        self._lock = Lock()
        if self.mmio.read(self.ID) != 0x4D4C5031:
            raise RuntimeError("ID không đúng; kiểm tra cặp .bit/.hwh và địa chỉ IP.")
        if self.mmio.read(self.IMAGE_SIZE) != 784:
            raise RuntimeError("Overlay dùng kích thước ảnh khác driver này.")

    def soft_reset(self, timeout=0.1):
        """Abort work and invalidate the image; the next call must upload pixels."""
        if timeout <= 0:
            raise ValueError("timeout phải lớn hơn 0.")
        with self._lock:
            self.mmio.write(self.CONTROL, 4)
            deadline = monotonic() + timeout
            while self.mmio.read(self.STATUS) & self.BUSY:
                if monotonic() >= deadline:
                    raise TimeoutError("Reset accelerator không hoàn tất.")
            if self.mmio.read(self.LOADED) != 0:
                raise RuntimeError("Reset chưa xóa trạng thái ảnh đầu vào.")

    def predict(self, pixels, timeout=1.0):
        """Upload a raw MNIST image, run once and return measured timing.

        compute_ms uses the hardware cycle counter. total_ms is host wall time
        including AXI upload, register accesses, polling and acknowledgement.
        A timeout leaves the core state inspectable; call soft_reset to abort.
        """
        if timeout <= 0:
            raise ValueError("timeout phải lớn hơn 0.")
        words = pack_pixels(pixels)
        with self._lock:
            if self.mmio.read(self.STATUS) & self.BUSY:
                raise RuntimeError("Accelerator đang bận; chờ hoàn tất hoặc gọi soft_reset().")
            self.mmio.write(self.CONTROL, 2)
            started = perf_counter_ns()
            first = self.PIXEL_BASE // 4
            self.mmio.array[first:first + 196] = words
            if self.mmio.read(self.LOADED) != 784:
                raise RuntimeError("AXI chưa nạp đủ ảnh; kiểm tra overlay và driver.")
            uploaded = perf_counter_ns()
            self.mmio.write(self.CONTROL, 1)
            deadline = monotonic() + timeout
            while True:
                status = self.mmio.read(self.STATUS)
                if status & self.ERROR_FLAG:
                    code = self.mmio.read(self.ERROR)
                    raise RuntimeError(self.ERROR_TEXT.get(code, f"lỗi phần cứng {code}"))
                if status & self.DONE:
                    break
                if monotonic() >= deadline:
                    raise TimeoutError("Suy luận quá timeout; gọi soft_reset() nếu muốn hủy.")
            digit = self.mmio.read(self.RESULT)
            cycles = self.mmio.read(self.CYCLES)
            clock_hz = self.mmio.read(self.CLOCK)
            if digit not in range(10) or cycles == 0 or clock_hz <= 0:
                raise RuntimeError("Kết quả/timing không hợp lệ; kiểm tra cặp .bit/.hwh.")
            self.mmio.write(self.CONTROL, 2)
            ended = perf_counter_ns()
            return InferenceResult(
                digit=int(digit), cycles=int(cycles), clock_hz=int(clock_hz),
                compute_ms=cycles * 1000 / clock_hz,
                upload_ms=(uploaded - started) / 1e6,
                total_ms=(ended - started) / 1e6,
            )


def load_overlay(bitfile="mnist_mlp.bit"):
    path = Path(bitfile).resolve()
    if not path.is_file() or not path.with_suffix(".hwh").is_file():
        raise FileNotFoundError("Cần đặt mnist_mlp.bit và mnist_mlp.hwh cùng thư mục, cùng tên gốc.")
    try:
        from pynq.ps import Clocks
        Clocks.set_pl_clk = lambda *args, **kwargs: None
    except Exception:
        pass
    overlay = Overlay(str(path))
    ip = overlay.mlp_ai_0
    if not isinstance(ip, MnistMLP):
        raise RuntimeError("Driver chưa bind đúng VLNV của IP.")
    return overlay, ip

