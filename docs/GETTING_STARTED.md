# Getting started / Hướng dẫn chạy

[Tiếng Việt](#tiếng-việt) · [English below](#english)

## Tiếng Việt

### Chuẩn bị và chế độ software

Dùng Python 3.10+ với NumPy/Pillow; PYNQ 3.1.1 là môi trường board được ghi trong báo cáo. Bản này không cần Flask, OpenCV hoặc PyTorch để suy luận. Chạy từ thư mục gốc mã nguồn:

```bash
python -m pip install -r requirements.txt
python camera_demo/app.py --backend software --self-test
```

Mở http://127.0.0.1:8765 trên Edge/Chrome, chọn **Thử ảnh mẫu**. Mẫu 7 phải ra 7; `--self-test` kiểm tra 10 ảnh mẫu trước khi server chạy. Backend software tính trên CPU laptop. Giữ terminal mở; Ctrl+C để dừng server. Windows có thể chạy `camera_demo/start_camera_demo.cmd` sau khi cài dependency.

### Cài gói board từ Release

1. Tải `pynq-z2-mnist-v1.0.0.zip`, `INSTALL.ipynb` và `SHA256SUMS.txt` từ cùng một Release. Checkpoint `.pth` không cần cho bước này.
2. Trên Jupyter của board, tạo thư mục trống, upload ZIP cùng installer. Mở `INSTALL.ipynb`, đọc hướng dẫn rồi chạy cell cài đặt. Installer kiểm tra SHA256 toàn ZIP và từng tệp, chặn đường dẫn thoát thư mục và từ chối ghi đè `camera_demo` có sẵn. Installer chưa nạp FPGA.
3. Dừng chương trình khác đang dùng PL, đặc biệt overlay video của dự án 2. Mỗi lần chỉ dùng một overlay. Kiểm tra nguồn và jumper theo tài liệu board; không suy ra khả năng chạy chỉ từ LED.
4. Mở terminal mới, chuyển vào thư mục `camera_demo` vừa giải nén. Ví dụ bên dưới dùng vị trí `/home/xilinx/jupyter_notebooks/mnist_demo/camera_demo`; thay theo chỗ cài thực tế.

```bash
cd /home/xilinx/jupyter_notebooks/mnist_demo/camera_demo
sudo /usr/local/share/pynq-venv/bin/python3 verify_board.py --benchmark-repeats 100
```

Chờ PASS 120 ca, reset và benchmark; kết quả mới ghi `board_verification.json`. Script báo lỗi thì chưa đạt, không lấy báo cáo cũ để thay thế. Python PYNQ trên image khác có thể nằm ở đường dẫn khác; dùng interpreter có `import pynq` thành công, không cài PYNQ desktop để thay môi trường board.

### Chạy FPGA và remote

Trên board, vẫn trong thư mục `camera_demo`:

```bash
sudo /usr/local/share/pynq-venv/bin/python3 app.py --backend fpga --host 0.0.0.0 --port 8766 --self-test
```

Trên laptop, dừng server software đang dùng cổng 8765 bằng Ctrl+C, rồi từ gốc repository chạy:

```bash
python camera_demo/app.py --backend remote --board-url http://BOARD_IP:8766 --self-test
```

Thay `BOARD_IP` bằng IP thật của board. Mở **http://127.0.0.1:8765** ở laptop. Backend phải thể hiện FPGA/remote; mất board hoặc sai fingerprint sẽ báo lỗi. Chỉ dùng server board trong mạng tin cậy; server demo không có đăng nhập/TLS và không dành để mở cổng Internet.

Driver đọc `.bit/.hwh` cùng tên gốc trong `camera_demo/fpga`. Nếu chỉ clone mã nguồn, hai tệp này chưa có; lấy đúng cặp từ Release, giữ nguyên `model.json` và trọng số tương ứng.

### Camera và ghi mẫu

Bấm **Bật camera**, cho phép truy cập camera, chọn một số 0–9 nét đậm trên giấy và giữ toàn bộ chữ trong khung. Chọn đúng polarity: nét tối/nền sáng hoặc nét sáng/nền tối. Quan sát ảnh 28×28 trước khi đánh giá kết quả. Chữ chạm mép, giấy trắng hay chữ quá nhỏ có thể bị từ chối; hoa văn vẫn có thể bị nhận nhầm vì kiểm tra ROI chỉ là heuristic.

Kết quả lớn ổn định sau 3 dự đoán liên tiếp giống nhau; đây không phải xác suất tin cậy. Nút **Ghi mẫu kiểm thử** lưu ảnh chữ đã chuẩn hóa PNG và JSON có nhãn trong `camera_demo/captures/`. Không tự lưu video đầy đủ; không đăng captures cá nhân lên repository. Camera dùng API trình duyệt tại localhost; không mở giao diện camera qua HTTP IP board.

Nhịp nhận diện phụ thuộc camera, tiền xử lý, HTTP và đối chiếu tham chiếu; thời gian 1.10208 ms trong lõi không phải FPS toàn hệ thống.

### Dừng và tắt an toàn

Bấm **Dừng** để dừng camera, rồi Ctrl+C ở terminal laptop và board để đóng server. Lưu các file cần giữ. Khi cần tắt Linux trên board, chạy:

```bash
sudo shutdown -h now
```

Phiên web/SSH sẽ mất kết nối trước hoặc trong quá trình tắt; riêng việc mất kết nối không xác nhận hệ thống đã halt. Nếu có UART, đợi thông báo halt/power-down. LED nguồn có thể vẫn sáng khi Linux đã halt vì nguồn vật lý còn nối; không chờ mọi LED tắt rồi mới ngắt công tắc nguồn. Nếu board còn phản hồi hoặc đang shutdown lỗi, xem log/UART trước khi rút nguồn.

---

## English

### Preparation and software mode

Use Python 3.10+ with NumPy/Pillow; PYNQ 3.1.1 is the board environment recorded in the report. Flask, OpenCV and PyTorch are not required for inference. Run from the source repository root:

```bash
python -m pip install -r requirements.txt
python camera_demo/app.py --backend software --self-test
```

Open http://127.0.0.1:8765 in Edge/Chrome and select **Thử ảnh mẫu** (test sample). Sample 7 should return 7; `--self-test` checks 10 samples before starting the server. Software mode computes on the laptop CPU. Keep the terminal open; use Ctrl+C to stop the server. On Windows, `camera_demo/start_camera_demo.cmd` is available after installing dependencies.

### Install the board Release package

1. Download `pynq-z2-mnist-v1.0.0.zip`, `INSTALL.ipynb` and `SHA256SUMS.txt` from the same Release. The `.pth` checkpoint is unnecessary for this step.
2. In the board's Jupyter interface, create an empty folder and upload the ZIP and installer together. Open `INSTALL.ipynb`, read the instructions and run the installation cell. It checks the complete ZIP and individual file SHA256 values, blocks paths escaping the folder, and refuses to overwrite an existing `camera_demo`. The installer does not load the FPGA.
3. Stop other programs using the PL, particularly the project 2 video overlay. Use only one overlay at a time. Check power and jumpers against the board documentation; LEDs alone do not establish correct operation.
4. Open a new terminal and enter the extracted `camera_demo` directory. The example below uses `/home/xilinx/jupyter_notebooks/mnist_demo/camera_demo`; substitute the actual installation location.

```bash
cd /home/xilinx/jupyter_notebooks/mnist_demo/camera_demo
sudo /usr/local/share/pynq-venv/bin/python3 verify_board.py --benchmark-repeats 100
```

Wait for PASS on 120 cases, reset and the benchmark; a new result is written to `board_verification.json`. An error means the run did not pass; do not substitute an old report. Other images may place the PYNQ interpreter elsewhere; use the interpreter where `import pynq` succeeds rather than installing desktop PYNQ as a replacement for the board environment.

### Run FPGA and remote modes

On the board, still inside `camera_demo`:

```bash
sudo /usr/local/share/pynq-venv/bin/python3 app.py --backend fpga --host 0.0.0.0 --port 8766 --self-test
```

On the laptop, stop the software server occupying port 8765 with Ctrl+C, then run from the repository root:

```bash
python camera_demo/app.py --backend remote --board-url http://BOARD_IP:8766 --self-test
```

Replace `BOARD_IP` with the board's actual IP address. Open **http://127.0.0.1:8765** on the laptop. The backend must show FPGA/remote; an unavailable board or mismatched fingerprint produces an error. Use the board server only on a trusted network; this demo server has no authentication/TLS and is not intended for Internet port forwarding.

The driver reads the same-basename `.bit/.hwh` pair in `camera_demo/fpga`. A source clone does not contain these two files; obtain the matching pair from Releases and retain the corresponding `model.json` and weights.

### Camera use and labeled samples

Click **Bật camera** (enable camera), grant permission, present one clearly written digit 0–9 on paper, and keep the entire digit inside the ROI. Select the correct polarity: dark ink/light background or light ink/dark background. Inspect the 28×28 preview before assessing the prediction. Border-touching digits, blank paper and very small digits may be rejected; patterns can still be misclassified because ROI validation is heuristic.

The large result stabilizes after 3 consecutive identical predictions; this is not a confidence probability. **Ghi mẫu kiểm thử** (save test sample) stores the normalized digit PNG and labeled JSON in `camera_demo/captures/`. Full video is not automatically recorded; do not publish private captures in the repository. Camera access uses the browser API on localhost; do not open the camera interface through the board's HTTP IP address.

Recognition rate depends on camera capture, preprocessing, HTTP and reference comparison; the core's 1.10208 ms is not the full system FPS.

### Stop and shut down safely

Click **Dừng** (stop) to stop the camera, then press Ctrl+C in the laptop and board terminals to close their servers. Save any files you need. To shut down Linux on the board, run:

```bash
sudo shutdown -h now
```

Web/SSH sessions disconnect before or during shutdown; disconnection alone does not confirm that the system has halted. If UART is available, wait for the halt/power-down message. Power LEDs may remain lit after Linux halts because the physical supply is still connected; do not wait for every LED to go dark before switching off power. If the board still responds or shutdown reports errors, inspect logs/UART before disconnecting power.
