# Reproducing / Tái tạo kết quả

[Tiếng Việt](#tiếng-việt) · [English below](#english)

## Tiếng Việt

### Ba mức tái tạo

1. **Demo suy luận:** NumPy/Pillow + source; dùng backend software. Board cần gói Release có cặp bit/HWH đúng hash.
2. **Kiểm tra host:** `python -B scripts/check_repository.py` kiểm tra mô hình/fixtures/HTTP và driver giả lập; không nạp board.
3. **Đánh giá mô hình, mô phỏng và build:** cần checkpoint, MNIST, PyTorch và Vivado 2022.2. Tệp generated vào `output/` và `hardware/build/`, bị loại khỏi Git. Không cần làm mức 3 để sử dụng demo đã có.

### Chuẩn bị checkpoint và dataset

Tải checkpoint tùy chọn `mlp_mnist_float32.pth` từ cùng Release; kiểm tra SHA256 trước khi dùng. Cài các dependency huấn luyện, tải MNIST từ nguồn được torchvision hỗ trợ rồi chuẩn bị thư mục generated:

```bash
python -m pip install -r requirements-training.txt
python -c "from torchvision.datasets import MNIST; MNIST('data', train=False, download=True)"
python scripts/prepare_workspace.py --checkpoint /path/to/mlp_mnist_float32.pth
python validation/verify_stage1.py
```

Thay `/path/to/` theo máy thực tế. Helper sao chép sáu `.mem` đúng byte và export summary vào `output/`; checkpoint chỉ được chấp nhận khi hash khớp bản phát hành. `verify_stage1.py` kiểm tra checkpoint/trọng số, 10000 ảnh, giới hạn accumulator và sinh 120 ca reference. Nó không train lại. Full dataset không có trong repository; xem [ghi công và điều khoản](../THIRD_PARTY_NOTICES.md).

### Mô phỏng và build overlay

Cài Vivado 2022.2 hỗ trợ Zynq-7000 và board preset **PYNQ-Z2** từ TUL/PYNQ, bao gồm DDR preset. Board files không được copy vào source công khai; cài vào board repository của Vivado hoặc đặt đúng cấu trúc vendor trong `hardware/board_files/`. Tcl báo lỗi nếu không tìm được preset.

Sau bước chuẩn bị checkpoint/dataset ở trên, tại PowerShell gốc repository:

```powershell
.\validation\run_checks.ps1 -VivadoBin 'C:\Xilinx\Vivado\2022.2\bin' -Python '.\.venv\Scripts\python.exe'
.\hardware\scripts\run_axi_sim.ps1 -VivadoBin 'C:\Xilinx\Vivado\2022.2\bin'
# Full build repeats the required validation and produces output/stage3.
.\hardware\scripts\build.ps1 -VivadoBin 'C:\Xilinx\Vivado\2022.2\bin' -Python '.\.venv\Scripts\python.exe'
```

Nếu Vivado ở chỗ khác, đổi `-VivadoBin`. Build kiểm tra timing/DRC và hash trước khi tạo bundle. Tcl đóng gói lại IP từ RTL và `.mem`; không cần đăng các file build hoặc IP cache. Tool/version/seed khác có thể tạo bitstream khác byte, nên hash cũ chỉ dành cho bản Release hiện có. Sau rebuild phải ghép lại model/overlay và chạy lại kiểm chứng board; việc đóng gói publication chưa thử full rebuild mới.

### Huấn luyện lại là một phiên bản mới

`train_mlp_mnist.py` dùng PyTorch, MLP 784→128→64→10, 15 epoch, batch 128, Adam với learning rate 0.001. `export_for_fpga.py` xuất trọng số và lựa chọn shift. Chạy hai script có thể thay dữ liệu trong `output/`; chỉ làm trong một bản workspace riêng nếu muốn thực nghiệm:

```bash
python train_mlp_mnist.py
python export_for_fpga.py
```

Không cam kết train lại đạt đúng accuracy/hash cũ. Quy trình export hiện tại dùng test set để calibration; khi nghiên cứu cải tiến, tách train/validation/test trước khi chọn shift và chỉ đánh giá test cuối cùng một lần. Muốn dùng trọng số mới trên board, cập nhật tham chiếu/test vectors, tổng hợp bitstream mới và kiểm chứng lại, không chỉ chép `.mem` vào SD.

---

## English

### Three reproduction levels

1. **Inference demo:** NumPy/Pillow plus source, using software mode. The board needs the Release package with the matching bit/HWH hashes.
2. **Host checks:** `python -B scripts/check_repository.py` validates the model/fixtures/HTTP and a mocked driver; it does not load a board.
3. **Model evaluation, simulation and build:** requires the checkpoint, MNIST, PyTorch and Vivado 2022.2. Generated files go into `output/` and `hardware/build/`, which are excluded from Git. Level 3 is unnecessary for using the supplied demo.

### Prepare the checkpoint and dataset

Download the optional `mlp_mnist_float32.pth` checkpoint from the same Release and verify its SHA256 before use. Install training dependencies, download MNIST through a torchvision-supported source, and prepare generated directories:

```bash
python -m pip install -r requirements-training.txt
python -c "from torchvision.datasets import MNIST; MNIST('data', train=False, download=True)"
python scripts/prepare_workspace.py --checkpoint /path/to/mlp_mnist_float32.pth
python validation/verify_stage1.py
```

Replace `/path/to/` with the actual location. The helper copies six byte-preserved `.mem` files and the export summary into `output/`; it accepts the checkpoint only when its hash matches the release. `verify_stage1.py` checks checkpoint/weights, 10000 images and accumulator bounds, then generates 120 reference cases. It does not retrain. The full dataset is not included in the repository; see [attribution and terms](../THIRD_PARTY_NOTICES.md).

### Simulation and overlay build

Install Vivado 2022.2 with Zynq-7000 support and the **PYNQ-Z2** board preset from TUL/PYNQ, including the DDR preset. Board files are not copied into the public source; install them in Vivado's board repository or place the vendor's proper directory structure under `hardware/board_files/`. Tcl fails when the preset is unavailable.

After preparing the checkpoint/dataset above, run from the repository root in PowerShell:

```powershell
.\validation\run_checks.ps1 -VivadoBin 'C:\Xilinx\Vivado\2022.2\bin' -Python '.\.venv\Scripts\python.exe'
.\hardware\scripts\run_axi_sim.ps1 -VivadoBin 'C:\Xilinx\Vivado\2022.2\bin'
# Full build repeats the required validation and produces output/stage3.
.\hardware\scripts\build.ps1 -VivadoBin 'C:\Xilinx\Vivado\2022.2\bin' -Python '.\.venv\Scripts\python.exe'
```

If Vivado is installed elsewhere, change `-VivadoBin`. The build checks timing/DRC and hashes before creating its bundle. Tcl regenerates the IP from RTL and `.mem` files; publishing build files or IP caches is unnecessary. Different tools/versions/seeds may produce a byte-different bitstream, so the old hashes apply only to the existing Release. After rebuilding, re-pair the model/overlay and rerun board verification; publication packaging has not performed a new full rebuild.

### Retraining creates a new revision

`train_mlp_mnist.py` uses PyTorch with an MLP 784→128→64→10, 15 epochs, batch size 128 and Adam with learning rate 0.001. `export_for_fpga.py` exports weights and selects shifts. Running these scripts can replace data in `output/`; use a separate workspace copy for experiments:

```bash
python train_mlp_mnist.py
python export_for_fpga.py
```

Retraining is not guaranteed to reproduce the old accuracy/hashes. The existing export uses the test set for calibration; for improved research practice, separate train/validation/test before selecting shifts and evaluate the final test set only once. New board weights require updated references/test vectors, a newly synthesized bitstream and renewed verification; copying `.mem` files onto the SD card alone is insufficient.
