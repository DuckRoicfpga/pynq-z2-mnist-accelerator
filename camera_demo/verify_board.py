"""Run ON PYNQ-Z2: identity/clock, 120 reference cases, reset, ARM baseline."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter

import numpy as np

from inference import FpgaEngine, IntegerModel, validate_pixels


HERE = Path(__file__).resolve().parent
EXPECTED_CYCLES = 110208


def load_cases(path, model):
    with np.load(path, allow_pickle=False) as source:
        images = source["images"].copy()
        expected = source["expected_predictions"].copy()
    if images.shape != (120, 28, 28) or images.dtype != np.uint8 or expected.shape != (120,):
        raise ValueError("Bộ kiểm chứng cần có đúng 120 ảnh UINT8 28×28.")
    predictions = np.array([model.predict(p)["digit"] for p in images])
    if not np.array_equal(predictions, expected):
        raise ValueError("Dữ liệu tham chiếu không khớp trọng số INT8.")
    return images, expected


def check_result(result, expected):
    if result.digit != int(expected):
        raise RuntimeError(f"FPGA={result.digit}, tham chiếu={int(expected)}.")
    if result.cycles != EXPECTED_CYCLES or result.clock_hz != 100_000_000:
        raise RuntimeError(f"Cycle/clock không đúng: {result.cycles} / {result.clock_hz}.")


def main():
    for console in (sys.stdout, sys.stderr):
        if hasattr(console, "reconfigure"):
            console.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=HERE / "fpga" / "rtl_reference_cases.npz")
    parser.add_argument("--bit", type=Path, default=HERE / "fpga" / "mnist_mlp.bit")
    parser.add_argument("--benchmark-repeats", type=int, default=100)
    parser.add_argument("--captures", type=Path, help="Optional folder of labeled 28×28 PNG/JSON samples.")
    parser.add_argument("--output", type=Path, default=HERE / "board_verification.json")
    args = parser.parse_args()
    if args.benchmark_repeats < 10:
        parser.error("--benchmark-repeats cần >= 10.")
    try:
        model = IntegerModel()
        images, expected = load_cases(args.cases, model)
        from pynq import Clocks
        import pynq
        engine = FpgaEngine(model, args.bit)
        ai = engine.accelerator
        info = engine.overlay.ip_dict["mlp_ai_0"]
        clock_mhz = float(Clocks.fclk0_mhz)
        identity = {"ip": info["type"], "base": hex(info["phys_addr"]),
                    "id": hex(ai.mmio.read(ai.ID)), "image_size": ai.mmio.read(ai.IMAGE_SIZE),
                    "pl_clock_mhz_from_registers": clock_mhz}
        if identity["base"] != "0x40000000" or identity["id"] != "0x4d4c5031" or identity["image_size"] != 784:
            raise RuntimeError(f"Sai IP/register map: {identity}")
        if abs(clock_mhz - 100.0) > 0.1:
            raise RuntimeError(f"FCLK0 cần 100 MHz, đang là {clock_mhz} MHz.")
        rows = []
        for index, (pixels, wanted) in enumerate(zip(images, expected)):
            result = ai.predict(pixels)
            check_result(result, wanted)
            rows.append({"case": index, "expected_prediction": int(wanted), **asdict(result)})
        if ai.mmio.read(ai.LOADED) != 784 or ai.mmio.read(ai.STATUS) & 7:
            raise RuntimeError("Sau predict, cần đủ 784 pixel, không BUSY/DONE/ERROR.")
        ai.soft_reset()
        if ai.mmio.read(ai.LOADED) != 0:
            raise RuntimeError("Soft reset chưa xóa trạng thái ảnh.")
        check_result(ai.predict(images[7]), expected[7])
        # Time the direct driver call, excluding the verification wrapper's CPU reference.
        for pixels in images[:5]:
            model.predict(pixels)
            ai.predict(pixels)
        cpu_ms, fpga_call_ms, compute_ms, driver_total_ms = [], [], [], []
        for index in range(args.benchmark_repeats):
            pixels = images[index % 10]
            started = perf_counter()
            reference = model.predict(pixels)
            cpu_ms.append((perf_counter() - started) * 1000)
            started = perf_counter()
            result = ai.predict(pixels)
            fpga_call_ms.append((perf_counter() - started) * 1000)
            check_result(result, reference["digit"])
            compute_ms.append(result.compute_ms)
            driver_total_ms.append(result.total_ms)
        benchmark = {"repeats": args.benchmark_repeats,
                     "mean_cpu_arm_reference_ms": statistics.mean(cpu_ms),
                     "mean_fpga_call_on_arm_ms": statistics.mean(fpga_call_ms),
                     "mean_fpga_compute_ms": statistics.mean(compute_ms),
                     "mean_driver_total_ms": statistics.mean(driver_total_ms),
                     "speedup_cpu_arm_over_fpga_call": statistics.mean(cpu_ms) / statistics.mean(fpga_call_ms),
                     "baseline": "NumPy integer reference on ARM, same pixels and weights; not an optimized CPU implementation"}
        labeled = []
        if args.captures:
            from PIL import Image
            for record_path in sorted(args.captures.glob("*.json")):
                record = json.loads(record_path.read_text(encoding="utf-8"))
                label = record.get("label")
                if type(label) is not int or not 0 <= label <= 9:
                    raise ValueError(f"Nhãn không hợp lệ: {record_path.name}")
                with Image.open(record_path.with_suffix(".png")) as image:
                    pixels = validate_pixels(np.asarray(image))
                reference = model.predict(pixels)
                result = ai.predict(pixels)
                check_result(result, reference["digit"])
                labeled.append({"file": record_path.name, "label": label, "correct": result.digit == label, **asdict(result)})
            if not labeled:
                raise ValueError("Thư mục --captures chưa có cặp PNG/JSON có nhãn.")
        report = {"status": "PASS", "created_utc": datetime.now(timezone.utc).isoformat(), "actual_board_test_performed": True,
                  "machine": platform.machine(), "pynq_version": pynq.__version__,
                  "model_fingerprint": model.fingerprint, "identity": identity,
                  "reference_cases_passed": len(rows), "soft_reset_passed": True,
                  "reference_results": rows, "benchmark": benchmark,
                  "labeled_samples_count": len(labeled), "labeled_samples": labeled,
                  "labeled_samples_accuracy_percent": 100 * sum(r["correct"] for r in labeled) / len(labeled) if labeled else None}
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "PASS", "reference_cases": len(rows), "identity": identity,
                          "benchmark": benchmark, "output": str(args.output)}, ensure_ascii=False, indent=2))
    except Exception as exc:
        parser.exit(1, f"Kiểm chứng board KHÔNG ĐẠT: {exc}\nChưa tạo báo cáo PASS mới. Không dùng kết quả cũ làm kết quả lần này.\n")


if __name__ == "__main__":
    main()
