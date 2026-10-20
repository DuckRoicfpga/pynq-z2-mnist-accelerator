"""
=============================================================================
  EXPORT MÔ HÌNH MLP CHO FPGA (PYNQ-Z2 / Zynq-7020)
=============================================================================
  Script này thực hiện:
    1. Tải mô hình đã train (Float32)
    2. Lượng tử hóa trọng số (INT8) cho phần cứng
    3. Hiệu chuẩn (calibrate) tham số right-shift cho mỗi hidden layer
    4. Pre-scale bias thành INT32 (để cộng trực tiếp vào accumulator)
    5. Mô phỏng suy luận 100% bằng số nguyên (giống hệt cách FPGA sẽ tính)
    6. Xuất tất cả file .mem cho Vivado ($readmemh)
    7. Tạo file params.vh chứa các hằng số cho Verilog
    
  Nguyên lý lượng tử hóa cho FPGA:
  ─────────────────────────────────
  Mỗi layer trong mạng MLP tính: output = ReLU(Σ(input × weight) + bias)
  
  Trên FPGA, tất cả tính toán đều dùng SỐ NGUYÊN:
    - Input pixel: UINT8 [0, 255]  (ảnh gốc, không cần chia 255)
    - Weight:      INT8  [-127, +127]  (đã lượng tử hóa)
    - Accumulator: INT32 (tích lũy tất cả phép nhân)
    - Bias:        INT32 (đã pre-scale để cộng thẳng vào accumulator)
    - Output:      ReLU → Right-Shift → Clip [0, 255] → đưa vào layer tiếp
    
  Chuỗi scale factor:
    Layer 1: S_p1 = (1/255) × (max|W1|/127)
    Layer 2: S_p2 = S_p1 × 2^SHIFT1 × (max|W2|/127)
    Layer 3: S_p3 = S_p2 × 2^SHIFT2 × (max|W3|/127)
    
    bias_scaled[layer] = round(bias_float / S_p[layer])
=============================================================================
"""

import os
import sys
import math
import numpy as np
import torch
import torch.nn as nn
from torchvision import datasets, transforms
from torch.utils.data import DataLoader


# ===========================================================================
#  CẤU HÌNH
# ===========================================================================
INPUT_SIZE = 784
L1_NEURONS = 128
L2_NEURONS = 64
L3_NEURONS = 10

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
RTL_DIR = os.path.join(BASE_DIR, "rtl")
SIM_DIR = os.path.join(BASE_DIR, "sim")
FPGA_MEM_DIR = os.path.join(OUTPUT_DIR, "fpga_mem")


# ===========================================================================
#  ĐỊNH NGHĨA LẠI KIẾN TRÚC MLP (phải giống hệt file train)
# ===========================================================================
class MLP_MNIST(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(INPUT_SIZE, L1_NEURONS)
        self.fc2 = nn.Linear(L1_NEURONS, L2_NEURONS)
        self.fc3 = nn.Linear(L2_NEURONS, L3_NEURONS)
        self.relu = nn.ReLU()

    def forward(self, x):
        x = x.view(-1, INPUT_SIZE)
        x = self.relu(self.fc1(x))
        x = self.relu(self.fc2(x))
        x = self.fc3(x)
        return x


# ===========================================================================
#  HÀM TIỆN ÍCH
# ===========================================================================
def quantize_int8(data):
    """Lượng tử hóa mảng float sang INT8 [-127, +127]."""
    abs_max = np.max(np.abs(data))
    scale = abs_max / 127.0
    q = np.clip(np.round(data / scale), -127, 127).astype(np.int8)
    return q, scale


def int8_to_hex(val):
    """Chuyển INT8 signed sang chuỗi hex 2 ký tự (bù 2)."""
    val = int(val)
    if val < 0:
        val += 256
    return f"{val:02X}"


def int32_to_hex(val):
    """Chuyển INT32 signed sang chuỗi hex 8 ký tự (bù 2)."""
    val = int(val)
    if val < 0:
        val += 2**32
    return f"{val:08X}"


def save_mem_int8(data_flat, filepath):
    """Lưu mảng INT8 ra file .mem (mỗi dòng = 1 giá trị hex 2 ký tự)."""
    with open(filepath, 'w', encoding='utf-8') as f:
        for val in data_flat:
            f.write(int8_to_hex(int(val)) + '\n')


def save_mem_int32(data_flat, filepath):
    """Lưu mảng INT32 ra file .mem (mỗi dòng = 1 giá trị hex 8 ký tự)."""
    with open(filepath, 'w', encoding='utf-8') as f:
        for val in data_flat:
            f.write(int32_to_hex(int(val)) + '\n')


def save_mem_uint8(data_flat, filepath):
    """Lưu mảng UINT8 ra file .mem (mỗi dòng = 1 giá trị hex 2 ký tự)."""
    with open(filepath, 'w', encoding='utf-8') as f:
        for val in data_flat:
            f.write(f"{int(val):02X}\n")


# ===========================================================================
#  SỐ NGUYÊN INFERENCE - MÔ PHỎNG CHÍNH XÁC CÁCH FPGA SẼ TÍNH
# ===========================================================================
def integer_inference_batch(x_uint8, w1_q, b1_s, w2_q, b2_s, w3_q, b3_s, shift1, shift2):
    """
    Mô phỏng suy luận hoàn toàn bằng số nguyên (giống FPGA).
    
    Args:
        x_uint8: (batch, 784) uint8 pixel values [0, 255]
        w*_q: INT8 quantized weights
        b*_s: INT32 pre-scaled biases
        shift1, shift2: Right-shift amounts
    
    Returns:
        predictions: (batch,) predicted digit indices
    """
    x = x_uint8.astype(np.int32)

    # Layer 1: acc = x @ W1^T + b1_scaled, ReLU, shift, clip
    acc1 = x @ w1_q.astype(np.int32).T + b1_s.astype(np.int32)
    l1_out = np.clip(np.maximum(0, acc1) >> shift1, 0, 255).astype(np.int32)

    # Layer 2: acc = l1 @ W2^T + b2_scaled, ReLU, shift, clip
    acc2 = l1_out @ w2_q.astype(np.int32).T + b2_s.astype(np.int32)
    l2_out = np.clip(np.maximum(0, acc2) >> shift2, 0, 255).astype(np.int32)

    # Layer 3: acc = l2 @ W3^T + b3_scaled, argmax (no ReLU/shift)
    acc3 = l2_out @ w3_q.astype(np.int32).T + b3_s.astype(np.int32)

    return np.argmax(acc3, axis=1)


# ===========================================================================
#  CHƯƠNG TRÌNH CHÍNH
# ===========================================================================
def main():
    # Tạo thư mục
    for d in [FPGA_MEM_DIR, RTL_DIR, SIM_DIR, os.path.join(SIM_DIR, "test_images")]:
        os.makedirs(d, exist_ok=True)

    print("=" * 60)
    print("  EXPORT MO HINH MLP CHO FPGA (PYNQ-Z2)")
    print("=" * 60)

    # ──────────────────────────────────────────────────────────
    #  BUOC 1: Tai mo hinh da train
    # ──────────────────────────────────────────────────────────
    model = MLP_MNIST()
    model_path = os.path.join(OUTPUT_DIR, "model", "mlp_mnist_float32.pth")
    model.load_state_dict(torch.load(model_path, map_location='cpu', weights_only=True))
    model.eval()
    print(f"\n[1/7] Da tai mo hinh tu: {model_path}")

    # Lay trong so va bias (float32)
    w1_f = model.fc1.weight.data.numpy()  # (128, 784)
    b1_f = model.fc1.bias.data.numpy()    # (128,)
    w2_f = model.fc2.weight.data.numpy()  # (64, 128)
    b2_f = model.fc2.bias.data.numpy()    # (64,)
    w3_f = model.fc3.weight.data.numpy()  # (10, 64)
    b3_f = model.fc3.bias.data.numpy()    # (10,)

    # ──────────────────────────────────────────────────────────
    #  BUOC 2: Luong tu hoa trong so sang INT8
    # ──────────────────────────────────────────────────────────
    print("[2/7] Luong tu hoa trong so INT8...")
    w1_q, s_w1 = quantize_int8(w1_f)
    w2_q, s_w2 = quantize_int8(w2_f)
    w3_q, s_w3 = quantize_int8(w3_f)

    print(f"  W1: scale={s_w1:.6f}, shape={w1_q.shape}, range=[{w1_q.min()}, {w1_q.max()}]")
    print(f"  W2: scale={s_w2:.6f}, shape={w2_q.shape}, range=[{w2_q.min()}, {w2_q.max()}]")
    print(f"  W3: scale={s_w3:.6f}, shape={w3_q.shape}, range=[{w3_q.min()}, {w3_q.max()}]")

    # ──────────────────────────────────────────────────────────
    #  BUOC 3: Tai du lieu de hieu chuan (calibration)
    # ──────────────────────────────────────────────────────────
    print("[3/7] Tai du lieu hieu chuan...")
    transform = transforms.Compose([transforms.ToTensor()])
    test_dataset = datasets.MNIST(root='./data', train=False, transform=transform)
    test_loader = DataLoader(test_dataset, batch_size=256, shuffle=False)

    # ──────────────────────────────────────────────────────────
    #  BUOC 4: Hieu chuan Layer 1 (tinh SHIFT1 va bias1_scaled)
    # ──────────────────────────────────────────────────────────
    print("[4/7] Hieu chuan Layer 1...")

    # Scale cua accumulator Layer 1
    # Float: out = sum(pixel/255 * weight_float)
    # Integer: acc = sum(pixel_uint8 * weight_int8)
    # Quan he: out ≈ acc * S_p1, voi S_p1 = (1/255) * s_w1
    S_in = 1.0 / 255.0
    S_p1 = S_in * s_w1

    # Pre-scale bias: bias_scaled = round(bias_float / S_p1)
    b1_scaled = np.round(b1_f / S_p1).astype(np.int64)

    # Tim gia tri accumulator lon nhat de chon SHIFT1
    max_acc_l1 = 0
    for images, _ in test_loader:
        x = (images.view(-1, INPUT_SIZE).numpy() * 255).astype(np.int32)
        acc = x @ w1_q.astype(np.int32).T + b1_scaled.astype(np.int32)
        acc_relu = np.maximum(0, acc)
        max_acc_l1 = max(max_acc_l1, int(acc_relu.max()))

    # SHIFT1: chon sao cho max_acc >> SHIFT1 ≈ 255 (su dung toi da 8-bit range)
    if max_acc_l1 > 255:
        SHIFT1 = int(math.ceil(math.log2(max_acc_l1 / 255.0)))
    else:
        SHIFT1 = 0

    print(f"  Max accumulator (sau ReLU): {max_acc_l1:,d}")
    print(f"  SHIFT1 = {SHIFT1}")
    print(f"  Gia tri 8-bit sau shift: ~{max_acc_l1 >> SHIFT1}")

    # ──────────────────────────────────────────────────────────
    #  BUOC 5: Hieu chuan Layer 2 (tinh SHIFT2 va bias2_scaled)
    # ──────────────────────────────────────────────────────────
    print("[5/7] Hieu chuan Layer 2...")

    S_l1_out = S_p1 * (2 ** SHIFT1)   # Scale cua output Layer 1 (8-bit)
    S_p2 = S_l1_out * s_w2             # Scale cua accumulator Layer 2

    b2_scaled = np.round(b2_f / S_p2).astype(np.int64)

    max_acc_l2 = 0
    for images, _ in test_loader:
        x = (images.view(-1, INPUT_SIZE).numpy() * 255).astype(np.int32)
        # Layer 1
        acc1 = x @ w1_q.astype(np.int32).T + b1_scaled.astype(np.int32)
        l1_out = np.clip(np.maximum(0, acc1) >> SHIFT1, 0, 255).astype(np.int32)
        # Layer 2
        acc2 = l1_out @ w2_q.astype(np.int32).T + b2_scaled.astype(np.int32)
        acc2_relu = np.maximum(0, acc2)
        max_acc_l2 = max(max_acc_l2, int(acc2_relu.max()))

    if max_acc_l2 > 255:
        SHIFT2 = int(math.ceil(math.log2(max_acc_l2 / 255.0)))
    else:
        SHIFT2 = 0

    print(f"  Max accumulator (sau ReLU): {max_acc_l2:,d}")
    print(f"  SHIFT2 = {SHIFT2}")
    print(f"  Gia tri 8-bit sau shift: ~{max_acc_l2 >> SHIFT2}")

    # Layer 3: chi can bias, khong can shift (output la argmax)
    S_l2_out = S_p2 * (2 ** SHIFT2)
    S_p3 = S_l2_out * s_w3
    b3_scaled = np.round(b3_f / S_p3).astype(np.int64)

    # Clip biases ve pham vi INT32
    b1_scaled = np.clip(b1_scaled, -(2**31), 2**31 - 1).astype(np.int32)
    b2_scaled = np.clip(b2_scaled, -(2**31), 2**31 - 1).astype(np.int32)
    b3_scaled = np.clip(b3_scaled, -(2**31), 2**31 - 1).astype(np.int32)

    print(f"\n  Bias ranges (INT32 pre-scaled):")
    print(f"    b1: [{b1_scaled.min():,d}, {b1_scaled.max():,d}]")
    print(f"    b2: [{b2_scaled.min():,d}, {b2_scaled.max():,d}]")
    print(f"    b3: [{b3_scaled.min():,d}, {b3_scaled.max():,d}]")

    # ──────────────────────────────────────────────────────────
    #  BUOC 6: Kiem tra do chinh xac voi integer-only inference
    # ──────────────────────────────────────────────────────────
    print("\n[6/7] Kiem tra do chinh xac integer-only inference...")
    correct = 0
    total = 0
    for images, labels in test_loader:
        x = (images.view(-1, INPUT_SIZE).numpy() * 255).astype(np.uint8)
        pred = integer_inference_batch(x, w1_q, b1_scaled, w2_q, b2_scaled,
                                       w3_q, b3_scaled, SHIFT1, SHIFT2)
        correct += (pred == labels.numpy()).sum()
        total += labels.size(0)

    int_accuracy = 100.0 * correct / total
    print(f"  Do chinh xac integer-only: {int_accuracy:.2f}%")

    # ──────────────────────────────────────────────────────────
    #  BUOC 7: Xuat file cho Vivado
    # ──────────────────────────────────────────────────────────
    print("\n[7/7] Xuat file cho Vivado...")

    # 7a. Weight .mem files (INT8)
    save_mem_int8(w1_q.flatten(), os.path.join(FPGA_MEM_DIR, "fc1_weight.mem"))
    save_mem_int8(w2_q.flatten(), os.path.join(FPGA_MEM_DIR, "fc2_weight.mem"))
    save_mem_int8(w3_q.flatten(), os.path.join(FPGA_MEM_DIR, "fc3_weight.mem"))
    print(f"  [OK] Weight .mem: fc1_weight.mem, fc2_weight.mem, fc3_weight.mem")

    # 7b. Bias .mem files (INT32 pre-scaled)
    save_mem_int32(b1_scaled, os.path.join(FPGA_MEM_DIR, "fc1_bias.mem"))
    save_mem_int32(b2_scaled, os.path.join(FPGA_MEM_DIR, "fc2_bias.mem"))
    save_mem_int32(b3_scaled, os.path.join(FPGA_MEM_DIR, "fc3_bias.mem"))
    print(f"  [OK] Bias .mem: fc1_bias.mem, fc2_bias.mem, fc3_bias.mem")

    # 7c. Test images (1 anh cho moi chu so 0-9)
    print("  Xuat 10 anh test (moi chu so 1 anh)...")
    found_digits = {}
    for img, label in test_dataset:
        label = int(label)
        if label not in found_digits:
            pixels = (img.view(INPUT_SIZE).numpy() * 255).astype(np.uint8)
            found_digits[label] = pixels
        if len(found_digits) == 10:
            break

    for digit in range(10):
        pixels = found_digits[digit]
        save_mem_uint8(pixels, os.path.join(SIM_DIR, "test_images", f"test_image_{digit}.mem"))

        # Kiem tra voi integer inference
        x = pixels.astype(np.int32).reshape(1, -1)
        pred = integer_inference_batch(
            pixels.reshape(1, -1), w1_q, b1_scaled, w2_q, b2_scaled,
            w3_q, b3_scaled, SHIFT1, SHIFT2
        )
        status = "OK" if int(pred[0]) == digit else "WRONG"
        print(f"    Chu so {digit}: du doan = {int(pred[0])} [{status}]")

    # Luu expected labels
    with open(os.path.join(SIM_DIR, "test_images", "expected_labels.txt"), 'w') as f:
        for d in range(10):
            f.write(f"{d}\n")

    # 7d. Tao params.vh cho Verilog
    params_content = f"""\
// ============================================================================
// Auto-generated by export_for_fpga.py - DO NOT EDIT MANUALLY
// Parameters for MLP Neural Network Accelerator on PYNQ-Z2
// ============================================================================

// Network architecture
`define INPUT_SIZE    {INPUT_SIZE}    // 28x28 pixels flattened
`define L1_NEURONS    {L1_NEURONS}    // Hidden layer 1 neurons
`define L2_NEURONS    {L2_NEURONS}    // Hidden layer 2 neurons
`define L3_NEURONS    {L3_NEURONS}    // Output layer neurons (digits 0-9)

// Weight memory depths (number of entries)
`define W1_DEPTH      {L1_NEURONS * INPUT_SIZE}  // L1_NEURONS * INPUT_SIZE
`define W2_DEPTH      {L2_NEURONS * L1_NEURONS}   // L2_NEURONS * L1_NEURONS
`define W3_DEPTH      {L3_NEURONS * L2_NEURONS}     // L3_NEURONS * L2_NEURONS

// Quantization right-shift amounts (calibrated on test set)
`define SHIFT1        {SHIFT1}     // Right-shift after Layer 1 ReLU
`define SHIFT2        {SHIFT2}     // Right-shift after Layer 2 ReLU

// Integer-only inference accuracy: {int_accuracy:.2f}%
// Scale factors (reference only):
//   S_w1 = {s_w1:.8f}
//   S_w2 = {s_w2:.8f}
//   S_w3 = {s_w3:.8f}
"""
    params_path = os.path.join(RTL_DIR, "params.vh")
    with open(params_path, 'w', encoding='utf-8') as f:
        f.write(params_content)
    print(f"  [OK] Verilog params: {params_path}")

    # 7e. Tao file thong tin tong hop
    summary_path = os.path.join(OUTPUT_DIR, "fpga_export_summary.txt")
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write("FPGA EXPORT SUMMARY\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Model: MLP {INPUT_SIZE} -> {L1_NEURONS} -> {L2_NEURONS} -> {L3_NEURONS}\n")
        f.write(f"SHIFT1: {SHIFT1}\n")
        f.write(f"SHIFT2: {SHIFT2}\n")
        f.write(f"Integer accuracy: {int_accuracy:.2f}%\n\n")
        f.write("Weight scales:\n")
        f.write(f"  s_w1 = {s_w1:.8f}\n")
        f.write(f"  s_w2 = {s_w2:.8f}\n")
        f.write(f"  s_w3 = {s_w3:.8f}\n\n")
        f.write("Bias ranges (INT32 pre-scaled):\n")
        f.write(f"  b1: [{b1_scaled.min()}, {b1_scaled.max()}]\n")
        f.write(f"  b2: [{b2_scaled.min()}, {b2_scaled.max()}]\n")
        f.write(f"  b3: [{b3_scaled.min()}, {b3_scaled.max()}]\n\n")
        f.write("Memory requirements:\n")
        f.write(f"  W1: {L1_NEURONS * INPUT_SIZE:,d} x 8-bit = {L1_NEURONS * INPUT_SIZE / 1024:.1f} KB\n")
        f.write(f"  W2: {L2_NEURONS * L1_NEURONS:,d} x 8-bit = {L2_NEURONS * L1_NEURONS / 1024:.1f} KB\n")
        f.write(f"  W3: {L3_NEURONS * L2_NEURONS:,d} x 8-bit = {L3_NEURONS * L2_NEURONS / 1024:.0f} KB\n")
        f.write(f"  B1: {L1_NEURONS} x 32-bit = {L1_NEURONS * 4 / 1024:.1f} KB\n")
        f.write(f"  B2: {L2_NEURONS} x 32-bit = {L2_NEURONS * 4 / 1024:.1f} KB\n")
        f.write(f"  B3: {L3_NEURONS} x 32-bit = {L3_NEURONS * 4 / 1024:.1f} KB\n")
        total_kb = (L1_NEURONS*INPUT_SIZE + L2_NEURONS*L1_NEURONS + L3_NEURONS*L2_NEURONS +
                    (L1_NEURONS + L2_NEURONS + L3_NEURONS) * 4) / 1024
        f.write(f"  TOTAL: ~{total_kb:.1f} KB\n")

    # ──────────────────────────────────────────────────────────
    #  TOM TAT
    # ──────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  EXPORT HOAN TAT!")
    print(f"{'=' * 60}")
    print(f"  SHIFT1 = {SHIFT1}")
    print(f"  SHIFT2 = {SHIFT2}")
    print(f"  Do chinh xac integer-only: {int_accuracy:.2f}%")
    print(f"  Thu muc FPGA mem: {FPGA_MEM_DIR}")
    print(f"  Thu muc RTL:      {RTL_DIR}")
    print(f"  Thu muc SIM:      {SIM_DIR}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
