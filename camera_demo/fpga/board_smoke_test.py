"""Run on PYNQ-Z2 after copying the deployment bundle to its Jupyter folder."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import statistics

import numpy as np
from mnist_driver import load_overlay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bit", default="mnist_mlp.bit")
    parser.add_argument("--samples", default="test_images.npz")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    overlay, accelerator = load_overlay(args.bit)
    print("IP:", overlay.ip_dict["mlp_ai_0"]["type"])
    print("AXI base:", hex(overlay.ip_dict["mlp_ai_0"]["phys_addr"]))
    samples = np.load(args.samples, allow_pickle=False)
    results = []
    for pixels, expected in zip(samples["images"], samples["expected_predictions"]):
        result = accelerator.predict(pixels)
        print(f"digit={result.digit} expected={int(expected)} cycles={result.cycles} "
              f"compute={result.compute_ms:.5f} ms total={result.total_ms:.3f} ms")
        if result.digit != int(expected):
            raise AssertionError("Board prediction differs from the Python reference")
        results.append(asdict(result))
    for _ in range(args.repeats):
        results.append(asdict(accelerator.predict(samples["images"][0])))
    report = {
        "sample_predictions_passed": len(samples["images"]),
        "mean_total_ms": statistics.mean(r["total_ms"] for r in results),
        "mean_upload_ms": statistics.mean(r["upload_ms"] for r in results),
        "mean_compute_ms": statistics.mean(r["compute_ms"] for r in results),
        "results": results,
    }
    Path("board_results.json").write_text(json.dumps(report, indent=2))
    print("PASS. Actual board measurements saved to board_results.json")


if __name__ == "__main__":
    main()
