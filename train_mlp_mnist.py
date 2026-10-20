"""
=============================================================================
  GIAI ĐOẠN 1: Train MLP cho MNIST + Lượng tử hóa INT8 + Xuất trọng số
=============================================================================
  Dự án: AI Accelerator trên FPGA (PYNQ-Z2)
  
  Script này thực hiện 3 việc:
    1. Train mạng MLP (784 -> 128 -> 64 -> 10) trên tập dữ liệu MNIST
    2. Lượng tử hóa (Quantize) trọng số từ Float32 sang INT8 (Fixed-Point)
    3. Xuất trọng số ra file .hex và .mem để Vivado có thể đọc và nạp vào BRAM
  
  Kiến trúc mạng MLP:
    - Input Layer:  784 nơ-ron (ảnh 28x28 pixel, mỗi pixel = 1 giá trị grayscale)
    - Hidden Layer 1: 128 nơ-ron + ReLU
    - Hidden Layer 2:  64 nơ-ron + ReLU  
    - Output Layer:  10 nơ-ron (chữ số 0-9, dùng Softmax để chọn kết quả)
  
  Lượng tử hóa INT8:
    - Trọng số Float32 nằm trong khoảng [-1.0, +1.0] 
    - Nhân với 127 và làm tròn về số nguyên => phạm vi [-127, +127]
    - Biểu diễn bằng 8 bit (signed), tương thích với phần cứng FPGA
=============================================================================
"""

import os
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, transforms
from torch.utils.data import DataLoader
import matplotlib
matplotlib.use('Agg')  # Backend không cần GUI (tránh lỗi trên một số máy)
import matplotlib.pyplot as plt


# ===========================================================================
#  CẤU HÌNH THAM SỐ
# ===========================================================================
BATCH_SIZE = 128          # Số ảnh trong mỗi lần cập nhật trọng số
EPOCHS = 15               # Số vòng lặp huấn luyện qua toàn bộ dữ liệu
LEARNING_RATE = 0.001      # Tốc độ học (Adam optimizer)
HIDDEN1_SIZE = 128         # Số nơ-ron Hidden Layer 1
HIDDEN2_SIZE = 64          # Số nơ-ron Hidden Layer 2
NUM_CLASSES = 10           # Số lớp đầu ra (chữ số 0-9)
INPUT_SIZE = 28 * 28       # Kích thước ảnh đầu vào (784 pixel)

# Thư mục lưu kết quả
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
WEIGHTS_DIR = os.path.join(OUTPUT_DIR, "weights_hex")
MODEL_DIR = os.path.join(OUTPUT_DIR, "model")

# Tự động chọn GPU nếu có, không thì dùng CPU
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ===========================================================================
#  ĐỊNH NGHĨA KIẾN TRÚC MẠNG MLP
# ===========================================================================
class MLP_MNIST(nn.Module):
    """
    Mạng nơ-ron MLP (Multi-Layer Perceptron) cho bài toán nhận diện chữ số.
    
    Kiến trúc: 784 -> 128 (ReLU) -> 64 (ReLU) -> 10
    
    Tại sao chọn kiến trúc này cho FPGA?
    - Đủ lớn để đạt độ chính xác cao (~97-98%)
    - Đủ nhỏ để nhét vừa vào BRAM của Zynq-7020 trên PYNQ-Z2
    - Chỉ dùng phép nhân-cộng (MAC) và ReLU -> dễ thiết kế bằng Verilog
    """
    
    def __init__(self):
        super(MLP_MNIST, self).__init__()
        
        # Layer 1: Fully Connected 784 -> 128
        self.fc1 = nn.Linear(INPUT_SIZE, HIDDEN1_SIZE)
        
        # Layer 2: Fully Connected 128 -> 64
        self.fc2 = nn.Linear(HIDDEN1_SIZE, HIDDEN2_SIZE)
        
        # Layer 3: Fully Connected 64 -> 10 (Output)
        self.fc3 = nn.Linear(HIDDEN2_SIZE, NUM_CLASSES)
        
        # Hàm kích hoạt ReLU: f(x) = max(0, x)
        # Trong Verilog, ReLU cực kỳ đơn giản: if (x[MSB] == 1) y = 0; else y = x;
        self.relu = nn.ReLU()
    
    def forward(self, x):
        # Duỗi phẳng ảnh 28x28 thành vector 784 phần tử
        x = x.view(-1, INPUT_SIZE)
        
        # Layer 1: Linear + ReLU
        x = self.relu(self.fc1(x))
        
        # Layer 2: Linear + ReLU
        x = self.relu(self.fc2(x))
        
        # Layer 3: Linear (không cần ReLU, vì CrossEntropyLoss đã bao gồm Softmax)
        x = self.fc3(x)
        
        return x


# ===========================================================================
#  HÀM TRAIN MÔ HÌNH
# ===========================================================================
def train_model(model, train_loader, test_loader):
    """Huấn luyện mô hình MLP trên tập MNIST."""
    
    # Hàm mất mát: CrossEntropyLoss (kết hợp Softmax + Negative Log Likelihood)
    criterion = nn.CrossEntropyLoss()
    
    # Bộ tối ưu: Adam (tự động điều chỉnh learning rate cho từng trọng số)
    optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)
    
    # Lưu lịch sử để vẽ biểu đồ
    train_losses = []
    test_accuracies = []
    
    print("=" * 60)
    print(f"  BẮT ĐẦU HUẤN LUYỆN - Device: {DEVICE}")
    print(f"  Kiến trúc: {INPUT_SIZE} -> {HIDDEN1_SIZE} -> {HIDDEN2_SIZE} -> {NUM_CLASSES}")
    print("=" * 60)
    
    for epoch in range(EPOCHS):
        model.train()  # Chế độ huấn luyện
        running_loss = 0.0
        correct = 0
        total = 0
        
        for batch_idx, (images, labels) in enumerate(train_loader):
            # Chuyển dữ liệu lên GPU (nếu có)
            images, labels = images.to(DEVICE), labels.to(DEVICE)
            
            # --- Quy trình huấn luyện chuẩn ---
            optimizer.zero_grad()       # 1. Xóa gradient cũ
            outputs = model(images)     # 2. Forward pass: tính đầu ra dự đoán
            loss = criterion(outputs, labels)  # 3. Tính loss
            loss.backward()             # 4. Backward pass: tính gradient
            optimizer.step()            # 5. Cập nhật trọng số
            
            running_loss += loss.item()
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
        
        # Tính loss trung bình và accuracy trên tập train
        avg_loss = running_loss / len(train_loader)
        train_acc = 100.0 * correct / total
        train_losses.append(avg_loss)
        
        # Đánh giá trên tập test
        test_acc = evaluate_model(model, test_loader)
        test_accuracies.append(test_acc)
        
        print(f"  Epoch [{epoch+1:2d}/{EPOCHS}] | "
              f"Loss: {avg_loss:.4f} | "
              f"Train Acc: {train_acc:.2f}% | "
              f"Test Acc: {test_acc:.2f}%")
    
    print("=" * 60)
    print(f"  HOÀN TẤT! Độ chính xác cuối cùng trên tập Test: {test_accuracies[-1]:.2f}%")
    print("=" * 60)
    
    return train_losses, test_accuracies


def evaluate_model(model, test_loader):
    """Đánh giá độ chính xác trên tập test."""
    model.eval()  # Chế độ đánh giá (tắt dropout nếu có)
    correct = 0
    total = 0
    
    with torch.no_grad():  # Không cần tính gradient khi đánh giá
        for images, labels in test_loader:
            images, labels = images.to(DEVICE), labels.to(DEVICE)
            outputs = model(images)
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
    
    return 100.0 * correct / total


# ===========================================================================
#  LƯỢNG TỬ HÓA TRỌNG SỐ (FLOAT32 -> INT8)
# ===========================================================================
def quantize_weights(model):
    """
    Lượng tử hóa trọng số từ Float32 sang INT8 (signed, phạm vi -127 đến +127).
    
    Công thức: weight_int8 = round(weight_float32 / scale * 127)
    Trong đó: scale = max(|weight_float32|) trong mỗi layer
    
    Tại sao cần lượng tử hóa?
    - FPGA không có FPU (Floating Point Unit) hiệu quả
    - Phép nhân số nguyên 8-bit trên FPGA cực kỳ nhanh và tiết kiệm tài nguyên
    - DSP48 slice trên Zynq-7020 hỗ trợ nhân 18x25 bit rất hiệu quả
    """
    
    quantized_params = {}
    scale_factors = {}
    
    print("\n--- LƯỢNG TỬ HÓA TRỌNG SỐ ---")
    
    for name, param in model.named_parameters():
        data = param.data.cpu().numpy()
        
        # Tìm giá trị tuyệt đối lớn nhất (scale factor)
        abs_max = np.max(np.abs(data))
        scale = abs_max / 127.0  # Scale để ánh xạ về [-127, +127]
        
        # Lượng tử hóa: chia cho scale, làm tròn, clip về [-127, +127]
        # Công thức: q = clip(round(data / scale), -127, 127)
        # Khôi phục:  data ≈ q * scale
        quantized = np.clip(np.round(data / scale), -127, 127).astype(np.int8)
        
        quantized_params[name] = quantized
        scale_factors[name] = scale
        
        # In thống kê
        print(f"  {name:15s} | Shape: {str(data.shape):15s} | "
              f"Float range: [{data.min():.4f}, {data.max():.4f}] | "
              f"Scale: {scale:.6f}")
    
    return quantized_params, scale_factors


# ===========================================================================
#  KIỂM TRA ĐỘ CHÍNH XÁC SAU LƯỢNG TỬ HÓA
# ===========================================================================
def test_quantized_accuracy(model, quantized_params, scale_factors, test_loader):
    """
    Mô phỏng suy luận bằng trọng số INT8 trên CPU (giống cách FPGA sẽ tính).
    So sánh kết quả với mô hình Float32 gốc.
    """
    print("\n--- KIỂM TRA ĐỘ CHÍNH XÁC SAU LƯỢNG TỬ HÓA ---")
    
    # Khôi phục trọng số: data ≈ quantized_value * scale
    fc1_w = quantized_params['fc1.weight'].astype(np.float32) * scale_factors['fc1.weight']
    fc1_b = quantized_params['fc1.bias'].astype(np.float32) * scale_factors['fc1.bias']
    fc2_w = quantized_params['fc2.weight'].astype(np.float32) * scale_factors['fc2.weight']
    fc2_b = quantized_params['fc2.bias'].astype(np.float32) * scale_factors['fc2.bias']
    fc3_w = quantized_params['fc3.weight'].astype(np.float32) * scale_factors['fc3.weight']
    fc3_b = quantized_params['fc3.bias'].astype(np.float32) * scale_factors['fc3.bias']
    
    correct = 0
    total = 0
    
    for images, labels in test_loader:
        x = images.view(-1, INPUT_SIZE).numpy()  # (batch, 784)
        
        # Layer 1: x = ReLU(x @ W1^T + b1)
        x = x @ fc1_w.T + fc1_b
        x = np.maximum(0, x)  # ReLU
        
        # Layer 2: x = ReLU(x @ W2^T + b2)
        x = x @ fc2_w.T + fc2_b
        x = np.maximum(0, x)  # ReLU
        
        # Layer 3: x = x @ W3^T + b3
        x = x @ fc3_w.T + fc3_b
        
        # Chọn chữ số có điểm cao nhất
        predicted = np.argmax(x, axis=1)
        total += labels.size(0)
        correct += (predicted == labels.numpy()).sum()
    
    acc = 100.0 * correct / total
    print(f"  Độ chính xác với trọng số INT8: {acc:.2f}%")
    return acc


# ===========================================================================
#  XUẤT TRỌNG SỐ RA FILE HEX/MEM CHO VIVADO
# ===========================================================================
def int8_to_hex(val):
    """Chuyển giá trị INT8 (signed) sang hex 2 chữ số (unsigned representation)."""
    if val < 0:
        val = val + 256  # Bù 2 (Two's complement): -1 -> 0xFF, -128 -> 0x80
    return f"{val:02X}"


def export_weights_hex(quantized_params):
    """
    Xuất trọng số INT8 ra file .hex và .mem để nạp vào BRAM trong Vivado.
    
    Định dạng .mem: Mỗi dòng là một giá trị hex (Vivado $readmemh() đọc được)
    Định dạng .hex: Mỗi dòng là một giá trị hex (dùng cho tham khảo)
    
    File được tạo:
    - fc1_weight.mem : Trọng số Layer 1 (128 x 784 = 100,352 giá trị)
    - fc1_bias.mem   : Bias Layer 1    (128 giá trị)
    - fc2_weight.mem : Trọng số Layer 2 (64 x 128 = 8,192 giá trị)
    - fc2_bias.mem   : Bias Layer 2    (64 giá trị)
    - fc3_weight.mem : Trọng số Layer 3 (10 x 64 = 640 giá trị)
    - fc3_bias.mem   : Bias Layer 3    (10 giá trị)
    """
    
    os.makedirs(WEIGHTS_DIR, exist_ok=True)
    
    print(f"\n--- XUẤT TRỌNG SỐ RA FILE ---")
    print(f"  Thư mục: {WEIGHTS_DIR}")
    
    total_params = 0
    
    for name, data in quantized_params.items():
        # Tạo tên file: "fc1.weight" -> "fc1_weight"
        filename_base = name.replace(".", "_")
        
        # Duỗi phẳng ma trận thành vector 1D
        flat_data = data.flatten()
        total_params += len(flat_data)
        
        # --- Xuất file .mem (Vivado $readmemh format) ---
        mem_path = os.path.join(WEIGHTS_DIR, f"{filename_base}.mem")
        with open(mem_path, 'w', encoding='utf-8') as f:
            for val in flat_data:
                f.write(int8_to_hex(int(val)) + "\n")
        
        # --- Xuất file .hex (tham khảo, giá trị signed gốc) ---
        hex_path = os.path.join(WEIGHTS_DIR, f"{filename_base}.hex")
        with open(hex_path, 'w', encoding='utf-8') as f:
            f.write(f"// {name} - Shape: {data.shape} - Total: {len(flat_data)} values\n")
            f.write(f"// Format: INT8 signed decimal | HEX (two's complement)\n")
            f.write(f"// {'='*50}\n")
            for i, val in enumerate(flat_data):
                f.write(f"{int(val):+4d}  // {int8_to_hex(int(val))} (index {i})\n")
        
        print(f"  ✓ {filename_base:15s} | Shape: {str(data.shape):15s} | "
              f"{len(flat_data):>7,d} giá trị | -> {os.path.basename(mem_path)}")
    
    print(f"\n  Tổng số tham số: {total_params:,d}")
    print(f"  Dung lượng ước tính trên FPGA: {total_params / 1024:.1f} KB (INT8)")


# ===========================================================================
#  XUẤT THÔNG TIN KIẾN TRÚC CHO VERILOG
# ===========================================================================
def export_architecture_info(quantized_params, scale_factors):
    """Tạo file tóm tắt kiến trúc để tham khảo khi viết Verilog."""
    
    info_path = os.path.join(OUTPUT_DIR, "architecture_info.txt")
    
    with open(info_path, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("  THÔNG TIN KIẾN TRÚC MLP CHO THIẾT KẾ VERILOG\n")
        f.write("=" * 60 + "\n\n")
        
        f.write("KIẾN TRÚC MẠNG:\n")
        f.write(f"  Input:    {INPUT_SIZE} (ảnh 28x28, mỗi pixel 8-bit grayscale)\n")
        f.write(f"  Hidden 1: {HIDDEN1_SIZE} nơ-ron + ReLU\n")
        f.write(f"  Hidden 2: {HIDDEN2_SIZE} nơ-ron + ReLU\n")
        f.write(f"  Output:   {NUM_CLASSES} nơ-ron (argmax để chọn kết quả)\n\n")
        
        f.write("LƯỢNG TỬ HÓA:\n")
        f.write("  Kiểu dữ liệu: INT8 (signed, -127 đến +127)\n")
        f.write("  Biểu diễn: Two's complement, 8-bit\n\n")
        
        f.write("SCALE FACTORS (cần lưu lại nếu muốn khôi phục giá trị Float):\n")
        for name, scale in scale_factors.items():
            f.write(f"  {name}: {scale:.8f}\n")
        
        f.write("\nCHI TIẾT TỪNG LAYER:\n")
        f.write("-" * 60 + "\n")
        
        for name, data in quantized_params.items():
            f.write(f"\n  [{name}]\n")
            f.write(f"    Shape: {data.shape}\n")
            f.write(f"    Tổng phần tử: {data.size:,d}\n")
            f.write(f"    Range: [{data.min()}, {data.max()}]\n")
            
            if 'weight' in name:
                rows, cols = data.shape
                f.write(f"    Trong Verilog: Ma trận {rows} hàng x {cols} cột\n")
                f.write(f"    Mỗi nơ-ron cần: {cols} phép nhân + {cols-1} phép cộng\n")
        
        f.write("\n" + "=" * 60 + "\n")
        f.write("  SỐ PHÉP TÍNH (MAC Operations):\n")
        
        mac_l1 = INPUT_SIZE * HIDDEN1_SIZE
        mac_l2 = HIDDEN1_SIZE * HIDDEN2_SIZE
        mac_l3 = HIDDEN2_SIZE * NUM_CLASSES
        total_mac = mac_l1 + mac_l2 + mac_l3
        
        f.write(f"    Layer 1: {INPUT_SIZE} x {HIDDEN1_SIZE} = {mac_l1:>10,d} MACs\n")
        f.write(f"    Layer 2: {HIDDEN1_SIZE} x {HIDDEN2_SIZE} = {mac_l2:>10,d} MACs\n")
        f.write(f"    Layer 3: {HIDDEN2_SIZE} x {NUM_CLASSES} = {mac_l3:>10,d} MACs\n")
        f.write(f"    TỔNG:  {' ':>20s} {total_mac:>10,d} MACs\n")
        f.write("=" * 60 + "\n")
    
    print(f"\n  ✓ Thông tin kiến trúc: {info_path}")


# ===========================================================================
#  VẼ BIỂU ĐỒ KẾT QUẢ
# ===========================================================================
def plot_results(train_losses, test_accuracies, quantized_acc):
    """Vẽ biểu đồ Loss và Accuracy qua các epoch."""
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    # Biểu đồ Loss
    ax1.plot(range(1, EPOCHS + 1), train_losses, 'b-o', linewidth=2, markersize=5)
    ax1.set_xlabel('Epoch', fontsize=12)
    ax1.set_ylabel('Loss', fontsize=12)
    ax1.set_title('Training Loss qua các Epoch', fontsize=14)
    ax1.grid(True, alpha=0.3)
    
    # Biểu đồ Accuracy
    ax2.plot(range(1, EPOCHS + 1), test_accuracies, 'g-o', linewidth=2, markersize=5, label='Float32')
    ax2.axhline(y=quantized_acc, color='r', linestyle='--', linewidth=2, 
                label=f'INT8 Quantized: {quantized_acc:.2f}%')
    ax2.set_xlabel('Epoch', fontsize=12)
    ax2.set_ylabel('Accuracy (%)', fontsize=12)
    ax2.set_title('Test Accuracy (Float32 vs INT8)', fontsize=14)
    ax2.legend(fontsize=11)
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim([90, 100])
    
    plt.tight_layout()
    plot_path = os.path.join(OUTPUT_DIR, "training_results.png")
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    print(f"\n  ✓ Biểu đồ kết quả: {plot_path}")
    plt.close()


# ===========================================================================
#  VẼ MỘT SỐ ẢNH MẪU VÀ KẾT QUẢ DỰ ĐOÁN
# ===========================================================================
def plot_predictions(model, test_loader):
    """Hiển thị 20 ảnh mẫu từ tập test cùng kết quả dự đoán."""
    
    model.eval()
    images, labels = next(iter(test_loader))
    images_gpu = images.to(DEVICE)
    
    with torch.no_grad():
        outputs = model(images_gpu)
        _, predicted = torch.max(outputs, 1)
    
    predicted = predicted.cpu().numpy()
    labels = labels.numpy()
    
    fig, axes = plt.subplots(2, 10, figsize=(16, 4))
    fig.suptitle('Kết quả dự đoán trên tập Test (Xanh = Đúng, Đỏ = Sai)', fontsize=13)
    
    for i in range(20):
        ax = axes[i // 10, i % 10]
        ax.imshow(images[i].squeeze(), cmap='gray')
        color = 'green' if predicted[i] == labels[i] else 'red'
        ax.set_title(f'{predicted[i]}', color=color, fontsize=14, fontweight='bold')
        ax.axis('off')
    
    plt.tight_layout()
    pred_path = os.path.join(OUTPUT_DIR, "sample_predictions.png")
    plt.savefig(pred_path, dpi=150, bbox_inches='tight')
    print(f"  ✓ Ảnh dự đoán mẫu: {pred_path}")
    plt.close()


# ===========================================================================
#  CHƯƠNG TRÌNH CHÍNH
# ===========================================================================
def main():
    # Tạo thư mục output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(MODEL_DIR, exist_ok=True)
    
    # ------ BƯỚC 1: Tải dữ liệu MNIST ------
    print("\n[1/6] Đang tải dữ liệu MNIST...")
    
    # Transform: Chuyển ảnh sang Tensor và chuẩn hóa về [0, 1]
    transform = transforms.Compose([
        transforms.ToTensor(),  # Chuyển PIL Image -> Tensor, tự động scale [0,255] -> [0,1]
    ])
    
    # Tải tập train (60,000 ảnh) và tập test (10,000 ảnh)
    train_dataset = datasets.MNIST(root='./data', train=True, download=True, transform=transform)
    test_dataset = datasets.MNIST(root='./data', train=False, download=True, transform=transform)
    
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=BATCH_SIZE, shuffle=False)
    
    print(f"  Tập train: {len(train_dataset):,d} ảnh")
    print(f"  Tập test:  {len(test_dataset):,d} ảnh")
    
    # ------ BƯỚC 2: Tạo mô hình và huấn luyện ------
    print(f"\n[2/6] Khởi tạo mô hình MLP và đưa lên {DEVICE}...")
    model = MLP_MNIST().to(DEVICE)
    
    # In tóm tắt kiến trúc
    total_params = sum(p.numel() for p in model.parameters())
    print(f"  Tổng số tham số: {total_params:,d}")
    
    print(f"\n[3/6] Bắt đầu huấn luyện ({EPOCHS} epochs)...\n")
    train_losses, test_accuracies = train_model(model, train_loader, test_loader)
    
    # ------ BƯỚC 3: Lưu mô hình Float32 ------
    model_path = os.path.join(MODEL_DIR, "mlp_mnist_float32.pth")
    torch.save(model.state_dict(), model_path)
    print(f"\n  ✓ Mô hình Float32 đã lưu: {model_path}")
    
    # ------ BƯỚC 4: Lượng tử hóa ------
    print(f"\n[4/6] Lượng tử hóa trọng số (Float32 -> INT8)...")
    quantized_params, scale_factors = quantize_weights(model)
    
    # Kiểm tra độ chính xác sau lượng tử hóa
    quantized_acc = test_quantized_accuracy(model, quantized_params, scale_factors, test_loader)
    
    # ------ BƯỚC 5: Xuất file cho Vivado ------
    print(f"\n[5/6] Xuất trọng số ra file .hex/.mem cho Vivado...")
    export_weights_hex(quantized_params)
    export_architecture_info(quantized_params, scale_factors)
    
    # Lưu scale factors (cần cho việc khôi phục giá trị nếu cần)
    scale_path = os.path.join(OUTPUT_DIR, "scale_factors.npy")
    np.save(scale_path, scale_factors)
    print(f"  ✓ Scale factors: {scale_path}")
    
    # ------ BƯỚC 6: Vẽ biểu đồ ------
    print(f"\n[6/6] Vẽ biểu đồ kết quả...")
    plot_results(train_losses, test_accuracies, quantized_acc)
    plot_predictions(model, test_loader)
    
    # ------ TÓM TẮT ------
    print("\n" + "=" * 60)
    print("  TÓM TẮT GIAI ĐOẠN 1")
    print("=" * 60)
    print(f"  Kiến trúc:      {INPUT_SIZE} -> {HIDDEN1_SIZE} -> {HIDDEN2_SIZE} -> {NUM_CLASSES}")
    print(f"  Tổng tham số:   {total_params:,d}")
    print(f"  Accuracy (F32): {test_accuracies[-1]:.2f}%")
    print(f"  Accuracy (INT8):{quantized_acc:.2f}%")
    print(f"  Sụt giảm:       {test_accuracies[-1] - quantized_acc:.2f}%")
    print(f"  Output folder:  {OUTPUT_DIR}")
    print("=" * 60)
    print("\n  ➜ BƯỚC TIẾP THEO: Dùng file .mem trong thư mục 'weights_hex'")
    print("    để nạp vào BRAM khi thiết kế Verilog trên Vivado.\n")


if __name__ == "__main__":
    main()
