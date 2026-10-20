"""Verify the implemented overlay and package the PYNQ deployment bundle."""
import ast
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output/stage3"
IP = ROOT / "hardware/ip_repo/mlp_axi_lite_1_0"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bit_header(path):
    with path.open("rb") as f:
        length = struct.unpack(">H", f.read(2))[0]
        magic = f.read(length)
        assert magic.startswith(b"\x0f\xf0"), "Unexpected bitstream magic"
        assert struct.unpack(">H", f.read(2))[0] == 1
        fields = {}
        while True:
            key = f.read(1).decode("ascii")
            if key == "e":
                fields["payload_bytes"] = struct.unpack(">I", f.read(4))[0]
                assert path.stat().st_size - f.tell() == fields["payload_bytes"]
                break
            assert key in "abcd", key
            size = struct.unpack(">H", f.read(2))[0]
            fields[key] = f.read(size).rstrip(b"\0").decode("ascii")
        return fields


def main():
    status = dict(line.split("=", 1) for line in (OUT / "implementation_status.txt").read_text().splitlines())
    assert int(status["CLOCK_HZ"]) == 100000000
    assert float(status["SETUP_SLACK_NS"]) >= 0 and float(status["HOLD_SLACK_NS"]) >= 0
    assert int(status["CRITICAL_DRC_COUNT"]) == 0
    timing = (OUT / "timing_post_route.rpt").read_text()
    assert "All user specified timing constraints are met." in timing
    for check in ("checking no_clock (0)", "checking no_input_delay (0)",
                  "checking no_output_delay (0)", "checking unconstrained_internal_endpoints (0)"):
        assert check in timing, check
    utilization = (OUT / "utilization_post_route.rpt").read_text()
    top_row = next(line for line in utilization.splitlines() if re.match(r"\|\s*mnist_system_wrapper\s*\|", line))
    values = [v.strip() for v in top_row.strip().strip("|").split("|")]
    resources = dict(zip(("total_luts", "logic_luts", "lutram", "srl", "flip_flops", "ramb36", "ramb18", "dsp"),
                         map(int, values[2:])))
    resources["bram_tiles"] = resources["ramb36"] + resources["ramb18"] / 2
    header = bit_header(OUT / "mnist_mlp.bit")
    assert "7z020clg400" in header["b"], header
    hwh = ET.parse(OUT / "mnist_mlp.hwh").getroot()
    ai = next(m for m in hwh.findall(".//MODULE") if m.get("INSTANCE") == "mlp_ai_0")
    assert ai.get("VLNV") == "mnist.local:user:mlp_axi_lite:1.0"
    params = {p.get("NAME"): p.get("VALUE") for p in ai.findall(".//PARAMETER")}
    assert int(params["CLOCK_HZ"]) == 100000000
    ranges = [m for m in hwh.findall(".//MEMRANGE") if m.get("INSTANCE") == "mlp_ai_0"]
    assert len(ranges) == 1
    assert int(ranges[0].get("BASEVALUE"), 16) == 0x40000000
    assert int(ranges[0].get("HIGHVALUE"), 16) == 0x4000FFFF
    ps = next(m for m in hwh.findall(".//MODULE") if m.get("INSTANCE") == "processing_system7_0")
    ps_params = {p.get("NAME"): p.get("VALUE") for p in ps.findall(".//PARAMETER")}
    assert float(ps_params["PCW_FPGA0_PERIPHERAL_FREQMHZ"]) == 100
    assert float(ps_params["PCW_M_AXI_GP0_FREQMHZ"]) == 100
    reg_names = {r.get("NAME") for r in ai.findall(".//REGISTER")}
    assert {"CONTROL", "STATUS", "RESULT", "CYCLE_COUNT", "LOADED_PIXELS"} <= reg_names
    assert any(p.get("NAME") == "irq" for p in ai.findall(".//PORT")), "IRQ missing from HWH"

    core_log = (ROOT / "output/validation/regression/xsim_regression.log").read_text()
    axi_log = (OUT / "axi_sim/xsim_axi.log").read_text()
    assert "REGRESSION PASS: 120/120 cases" in core_log
    assert "AXI REGRESSION PASS: 120/120 cases" in axi_log
    core_rows = list(csv.DictReader((ROOT / "output/validation/regression/rtl_results.csv").open()))
    axi_rows = list(csv.DictReader((OUT / "axi_sim/axi_results.csv").open()))
    assert len(core_rows) == len(axi_rows) == 120
    assert all(int(row["cycles"]) == 110208 for row in axi_rows + core_rows)
    assert all(int(a["prediction"]) == int(b["prediction"]) for a, b in zip(core_rows, axi_rows))
    file_hashes = {}
    for name in ("mlp_accelerator.v", "mlp_axi_lite.v", "params.vh"):
        actual, packed = ROOT / "rtl" / name, IP / "src" / name
        assert sha(actual) == sha(packed), f"Stale IP source: {name}"
        file_hashes[f"rtl/{name}"] = sha(actual)
    for actual in sorted((ROOT / "output/fpga_mem").glob("*.mem")):
        assert sha(actual) == sha(IP / "src" / actual.name), f"Stale IP weight: {actual.name}"
        file_hashes[f"output/fpga_mem/{actual.name}"] = sha(actual)
    component = (IP / "component.xml").read_text()
    assert not re.search(r"<spirit:dependency>.*[A-Za-z]:[/\\]", component)
    for file in (ROOT / "pynq").glob("*.py"):
        ast.parse(file.read_text(encoding="utf-8"))
    samples = np.array([[int(t, 16) for t in (ROOT / "sim" / f"test_image_{d}.mem").read_text().split()] for d in range(10)], dtype=np.uint8)
    assert samples.shape == (10, 784)
    np.savez_compressed(OUT / "test_images.npz", images=samples.reshape(10, 28, 28),
                        labels=np.arange(10), expected_predictions=np.arange(10))
    notes = {
        "stage3_status": "PASS", "board": "PYNQ-Z2", "part": "xc7z020clg400-1",
        "vivado_version": "2022.2", "clock_hz": 100000000,
        "ip_vlnv": ai.get("VLNV"), "ip_instance": "mlp_ai_0", "axi_base": "0x40000000", "axi_range": 65536,
        "setup_slack_ns": float(status["SETUP_SLACK_NS"]),
        "hold_slack_ns": float(status["HOLD_SLACK_NS"]), "critical_drc_count": 0,
        "resources_post_route": resources,
        "noncritical_drc_warnings": ["DPIP-1", "DPOP-2"],
        "core_regression_pass": 120, "axi_regression_pass": 120,
        "cycle_count": 110208, "compute_ms_at_configured_clock": 1.10208,
        "actual_board_test_performed": False,
        "limitations": ["Board measurement is stage 4", "Vendor DDR preset produces PSU-1..4 warnings; retained unchanged",
                        "Integer accuracy 97.64% uses the existing test-set calibration"],
        "bit_header": header, "source_and_weight_sha256": file_hashes,
        "artifacts": {name: {"bytes": (OUT / name).stat().st_size, "sha256": sha(OUT / name)}
                      for name in ("mnist_mlp.bit", "mnist_mlp.hwh", "mnist_mlp.xsa")},
    }
    (OUT / "manifest.json").write_text(json.dumps(notes, indent=2))
    notebook = {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "id": "intro", "source": [
                "# MNIST MLP trên PYNQ-Z2\n", "Chạy notebook này trên board PYNQ. Đặt `.bit`, `.hwh`, driver và dữ liệu mẫu cùng thư mục.\n",
                "Các output hiện để trống; kết quả board sẽ được đo khi em chạy giai đoạn 4."]},
            {"cell_type": "code", "metadata": {}, "id": "load", "execution_count": None, "outputs": [], "source": [
                "import numpy as np\n", "from mnist_driver import load_overlay\n", "overlay, accelerator = load_overlay('mnist_mlp.bit')\n",
                "samples = np.load('test_images.npz', allow_pickle=False)\n", "overlay.ip_dict['mlp_ai_0']"]},
            {"cell_type": "code", "metadata": {}, "id": "predict", "execution_count": None, "outputs": [], "source": [
                "index = 7\n", "image = samples['images'][index]\n", "result = accelerator.predict(image)\n", "print(result)\n",
                "assert result.digit == int(samples['expected_predictions'][index])"]},
            {"cell_type": "code", "metadata": {}, "id": "image", "execution_count": None, "outputs": [], "source": [
                "import matplotlib.pyplot as plt\n", "plt.imshow(image, cmap='gray', vmin=0, vmax=255)\n", "plt.title(f'Du doan: {result.digit}')\n", "plt.axis('off');"]},
            {"cell_type": "code", "metadata": {}, "id": "test", "execution_count": None, "outputs": [], "source": [
                "from dataclasses import asdict\n", "import pandas as pd\n", "rows = []\n",
                "for pixels, expected in zip(samples['images'], samples['expected_predictions']):\n",
                "    r = accelerator.predict(pixels)\n", "    assert r.digit == int(expected)\n", "    rows.append(asdict(r))\n", "pd.DataFrame(rows)"]},
            {"cell_type": "markdown", "metadata": {}, "id": "timing", "source": [
                "`compute_ms` lấy từ bộ đếm clock trong FPGA. `total_ms` và `upload_ms` được đo trên CPU, gồm chi phí truyền dữ liệu.\n",
                "10 ảnh là kiểm tra bước đầu, không phải phép đo độ chính xác toàn tập MNIST. Nếu timeout, dùng `accelerator.soft_reset()` rồi gửi lại ảnh."]},
        ],
    }
    (OUT / "quick_start.ipynb").write_text(json.dumps(notebook, ensure_ascii=False, indent=2), encoding="utf-8")
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            ast.parse("".join(cell["source"]))
    for name in ("mnist_driver.py", "board_smoke_test.py"):
        shutil.copyfile(ROOT / "pynq" / name, OUT / name)
    shutil.copyfile(ROOT / "hardware/README.md", OUT / "README.md")
    bundle_names = ["mnist_mlp.bit", "mnist_mlp.hwh", "mnist_driver.py", "board_smoke_test.py",
                    "test_images.npz", "quick_start.ipynb", "manifest.json", "README.md"]
    with zipfile.ZipFile(OUT / "mnist_pynq_z2_deploy.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for name in bundle_names:
            z.write(OUT / name, arcname=name)
    with zipfile.ZipFile(OUT / "mlp_axi_lite_ip.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(IP.rglob("*")):
            if path.is_file():
                z.write(path, arcname=str(Path(IP.name) / path.relative_to(IP)))
    with zipfile.ZipFile(OUT / "mnist_pynq_z2_deploy.zip") as z:
        assert z.testzip() is None
        assert sha(OUT / "mnist_mlp.bit") == hashlib.sha256(z.read("mnist_mlp.bit")).hexdigest()
        assert sha(OUT / "mnist_mlp.hwh") == hashlib.sha256(z.read("mnist_mlp.hwh")).hexdigest()
    print(json.dumps({"status": "PASS", "setup_slack_ns": notes["setup_slack_ns"],
                      "hold_slack_ns": notes["hold_slack_ns"], "bundle": str(OUT / "mnist_pynq_z2_deploy.zip")}, indent=2))


if __name__ == "__main__":
    main()
