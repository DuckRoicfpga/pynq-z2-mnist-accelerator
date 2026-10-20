"""Recheck existing model/export without retraining or replacing artifacts."""
import hashlib
import importlib.util
import json
import math
import re
import struct
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "validation"
OUT.mkdir(parents=True, exist_ok=True)
REG = OUT / "regression"


def read_mem(path, bits, count):
    tokens = path.read_text().split()
    assert len(tokens) == count, (path, len(tokens), count)
    assert all(re.fullmatch(r"[0-9a-fA-F]{%d}" % (bits // 4), t) for t in tokens), path
    raw = np.array([int(t, 16) for t in tokens], dtype=np.int64)
    if bits in (8, 32):
        raw = np.where(raw >= 2 ** (bits - 1), raw - 2**bits, raw)
    return raw


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_mem(path, values, bits):
    mask = (1 << bits) - 1
    path.write_text("".join(f"{int(v) & mask:0{bits // 4}X}\n" for v in np.asarray(values).flat))


def golden(x, weights, biases, shifts):
    h1_acc = x.astype(np.int64) @ weights[0].T + biases[0]
    h1 = np.clip(np.maximum(h1_acc, 0) >> shifts[0], 0, 255)
    h2_acc = h1 @ weights[1].T + biases[1]
    h2 = np.clip(np.maximum(h2_acc, 0) >> shifts[1], 0, 255)
    logits = h2 @ weights[2].T + biases[2]
    for acc in (h1_acc, h2_acc, logits):
        assert np.all(acc >= -(2**31)) and np.all(acc < 2**31), "INT32 overflow"
    return h1, h2, logits, h1_acc, h2_acc


def main():
    REG.mkdir(exist_ok=True)
    params = dict(re.findall(r"`define\s+(\w+)\s+(\d+)", (ROOT / "rtl/params.vh").read_text()))
    assert [int(params[k]) for k in ("INPUT_SIZE", "L1_NEURONS", "L2_NEURONS", "L3_NEURONS")] == [784, 128, 64, 10]
    shifts = [int(params["SHIFT1"]), int(params["SHIFT2"])]
    state = torch.load(ROOT / "output/model/mlp_mnist_float32.pth", map_location="cpu", weights_only=True)
    weights, biases, scales = [], [], []
    hashes = {}
    shapes = [(128, 784), (64, 128), (10, 64)]
    activation_scale = 1 / 255
    for layer, shape in enumerate(shapes, 1):
        wf = state[f"fc{layer}.weight"].numpy()
        bf = state[f"fc{layer}.bias"].numpy()
        assert wf.shape == shape and bf.shape == (shape[0],)
        assert np.isfinite(wf).all() and np.isfinite(bf).all()
        scale = np.max(np.abs(wf)) / 127
        wq = np.clip(np.round(wf / scale), -127, 127).astype(np.int8)
        activation_scale *= scale
        bq = np.round(bf / activation_scale).astype(np.int64)
        bq = np.clip(bq, -(2**31), 2**31 - 1)
        for kind, bits, values in (("weight", 8, wq), ("bias", 32, bq)):
            name = f"fc{layer}_{kind}.mem"
            path = ROOT / "output/fpga_mem" / name
            actual = read_mem(path, bits, values.size).reshape(values.shape)
            assert np.array_equal(actual, values), f"Checkpoint/export mismatch: {name}"
            assert sha(path) == sha(ROOT / "sim" / name), f"sim copy differs: {name}"
            hashes[name] = sha(path)
            (REG / name).write_bytes(path.read_bytes())
        weights.append(wq.astype(np.int64))
        biases.append(bq)
        scales.append(float(scale))
        if layer < 3:
            activation_scale *= 2 ** shifts[layer - 1]
    print("PASS: checkpoint, INT8 weights, INT32 biases and sim copies agree", flush=True)

    image_path = ROOT / "data/MNIST/raw/t10k-images-idx3-ubyte"
    label_path = ROOT / "data/MNIST/raw/t10k-labels-idx1-ubyte"
    with image_path.open("rb") as f:
        magic, n, rows, cols = struct.unpack(">IIII", f.read(16))
    assert (magic, n, rows, cols) == (2051, 10000, 28, 28)
    with label_path.open("rb") as f:
        label_magic, label_n = struct.unpack(">II", f.read(8))
    assert (label_magic, label_n) == (2049, n)
    images = np.memmap(image_path, mode="r", offset=16, dtype=np.uint8, shape=(n, 784))
    labels = np.memmap(label_path, mode="r", offset=8, dtype=np.uint8, shape=(n,))
    spec = importlib.util.spec_from_file_location("existing_export", ROOT / "export_for_fpga.py")
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    float_correct = integer_correct = float_quantized_correct = 0
    maxima = [0, 0]
    int_preds = []
    torch.set_num_threads(4)
    with torch.no_grad():
        for first in range(0, n, 256):
            x = np.array(images[first:first + 256])
            y = np.array(labels[first:first + 256])
            h1, h2, logits, a1, a2 = golden(x, weights, biases, shifts)
            pred = np.argmax(logits, axis=1)
            exported_pred = exporter.integer_inference_batch(x, weights[0], biases[0], weights[1], biases[1], weights[2], biases[2], *shifts)
            assert np.array_equal(pred, exported_pred), "Python INT32/INT64 reference mismatch"
            integer_correct += int(np.sum(pred == y))
            int_preds.extend(pred.tolist())
            maxima[0] = max(maxima[0], int(np.maximum(a1, 0).max()))
            maxima[1] = max(maxima[1], int(np.maximum(a2, 0).max()))
            z = torch.from_numpy(x.astype(np.float32) / 255)
            for layer in range(1, 4):
                z = F.linear(z, state[f"fc{layer}.weight"], state[f"fc{layer}.bias"])
                if layer < 3:
                    z = F.relu(z)
            float_correct += int((z.argmax(1).numpy() == y).sum())
            zq = x.astype(np.float32) / 255
            for layer in range(1, 4):
                wf = state[f"fc{layer}.weight"].numpy()
                bf = state[f"fc{layer}.bias"].numpy()
                sw, sb = np.max(np.abs(wf)) / 127, np.max(np.abs(bf)) / 127
                qw = np.clip(np.round(wf / sw), -127, 127).astype(np.int8).astype(np.float32) * sw
                qb = np.clip(np.round(bf / sb), -127, 127).astype(np.int8).astype(np.float32) * sb
                zq = zq @ qw.T + qb
                if layer < 3:
                    zq = np.maximum(zq, 0)
            float_quantized_correct += int((zq.argmax(1) == y).sum())
            if first % 2048 == 0:
                print(f"Checked {min(first + 256, n)}/{n} MNIST test images", flush=True)
    recalibrated = [max(0, int(math.ceil(math.log2(m / 255)))) if m > 255 else 0 for m in maxima]
    assert recalibrated == shifts, (recalibrated, shifts)
    integer_accuracy = integer_correct * 100 / n
    summary = (ROOT / "output/fpga_export_summary.txt").read_text()
    saved_accuracy = float(re.search(r"Integer accuracy:\s*([\d.]+)", summary).group(1))
    assert round(integer_accuracy, 2) == saved_accuracy
    print(f"Float32: {float_correct}/{n} = {float_correct*100/n:.2f}%", flush=True)
    print(f"Quantized weights with float arithmetic: {float_quantized_correct}/{n} = {float_quantized_correct*100/n:.2f}%", flush=True)
    print(f"Integer-only: {integer_correct}/{n} = {integer_accuracy:.2f}%", flush=True)

    cases, pixels = [], []
    for digit in range(10):
        path = ROOT / "sim" / f"test_image_{digit}.mem"
        assert sha(path) == sha(ROOT / "sim/test_images" / path.name)
        x = np.array([int(t, 16) for t in path.read_text().split()], dtype=np.uint8)
        assert x.shape == (784,)
        cases.append({"name": f"exported_digit_{digit}", "label": digit})
        pixels.append(x)
    rng = np.random.default_rng(20261014)
    for idx in sorted(rng.choice(n, 100, replace=False).tolist()):
        cases.append({"name": f"mnist_test_{idx}", "label": int(labels[idx])})
        pixels.append(np.array(images[idx]))
    edges = {
        "zero": np.zeros(784, dtype=np.uint8),
        "all_255": np.full(784, 255, dtype=np.uint8),
        "all_127": np.full(784, 127, dtype=np.uint8),
        "all_128": np.full(784, 128, dtype=np.uint8),
        "first_pixel_255": np.r_[np.uint8(255), np.zeros(783, dtype=np.uint8)],
        "last_pixel_255": np.r_[np.zeros(783, dtype=np.uint8), np.uint8(255)],
        "checkerboard": ((np.indices((28, 28)).sum(axis=0) % 2) * 255).astype(np.uint8).reshape(-1),
        "random_pixels": rng.integers(0, 256, size=784, dtype=np.uint8),
    }
    for name, x in edges.items():
        cases.append({"name": name, "label": None})
        pixels.append(x)
    for digit in (0, 9):
        cases.append({"name": f"repeat_digit_{digit}", "label": digit})
        pixels.append(pixels[digit].copy())
    x = np.array(pixels, dtype=np.uint8)
    h1, h2, logits, _, _ = golden(x, weights, biases, shifts)
    predictions = logits.argmax(1)
    for i, case in enumerate(cases):
        case["prediction"] = int(predictions[i])
    save_mem(REG / "inputs.mem", x, 8)
    save_mem(REG / "expected_l1.mem", h1, 8)
    save_mem(REG / "expected_l2.mem", h2, 8)
    save_mem(REG / "expected_l3.mem", logits, 32)
    save_mem(REG / "expected_predictions.mem", predictions, 8)
    (REG / "cases.json").write_text(json.dumps(cases, indent=2))
    (REG / "case_count.vh").write_text(f"`define CASE_COUNT {len(cases)}\n")
    bounds = [int(np.max(np.sum(np.abs(w), axis=1) * 255 + np.abs(b))) for w, b in zip(weights, biases)]
    assert all(bound < 2**31 for bound in bounds)
    report = {
        "status": "PASS", "mnist_test_images": n, "float32_accuracy_percent": float_correct * 100 / n,
        "quantized_weight_float_arithmetic_accuracy_percent": float_quantized_correct * 100 / n,
        "integer_accuracy_percent": integer_accuracy, "shift1": shifts[0], "shift2": shifts[1],
        "max_relu_accumulators": maxima, "conservative_accumulator_abs_bounds": bounds,
        "rtl_case_count": len(cases), "hashes": hashes,
        "calibration_note": "Existing export selects shifts on the test set; accuracy is not from an untouched holdout.",
    }
    (OUT / "stage1_results.json").write_text(json.dumps(report, indent=2))
    print(f"PASS: SHIFT values and accuracy reproduced; {len(cases)} RTL reference cases prepared", flush=True)


if __name__ == "__main__":
    main()
