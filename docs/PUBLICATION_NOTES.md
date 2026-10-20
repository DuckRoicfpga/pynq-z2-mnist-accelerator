# Publication notes / Ghi chú bản công khai

[Tiếng Việt](#tiếng-việt) · [English below](#english)

## Tiếng Việt

### Nội dung giữ nguyên và điều chỉnh

Bản công khai được tuyển chọn từ dự án 1, giữ nguyên byte RTL, model, checkpoint và cặp bit/HWH. Mã app, inference và driver không thay thuật toán. Đường dẫn validation được chuyển khỏi thư mục generated; script dùng Python do người chạy chọn thay vì venv riêng của tác giả. `.gitattributes` tắt chuyển đổi newline để không làm sai SHA256 của `.mem`/RTL.

Kiểm thử hiện có phát hiện hai lỗi preprocessing: rule chạm mép quá yếu và peak tương phản bị ảnh hưởng bởi đốm đã loại. Bản công khai sửa hai vị trí trong `camera_demo/preprocess.py`, giữ nguyên các assertion kiểm thử. Do đó báo cáo board cũ vẫn mô tả cùng lõi/model/driver, không được diễn giải là đã thử lại đường camera của bản công khai. File `provenance.json` giữ hash runtime gốc và ghi riêng hash runtime công khai để phân biệt.

Các tệp tài liệu được viết lại bằng tiếng Việt và tiếng Anh đầy đủ. Launcher Windows dùng đường dẫn tương đối. CI và installer được thêm để hỗ trợ người dùng mới.

### Chỉ đăng những gì cần thiết

Repository chứa source, model `.mem`, dữ liệu test nhỏ, báo cáo được chọn và hình minh chứng. `.bit/.hwh`, checkpoint và board ZIP nằm ở Releases. Không đăng SD backup `.img`, venv, toàn bộ MNIST, camera captures, bộ cài Vivado, vendor board files, `.Xil`, log tạm và build cache.

Ảnh software-demo được giữ nguyên nội dung, caption nói rõ backend CPU. Hai ảnh camera số 4 và số 8 được bổ sung theo lựa chọn của tác giả, giữ nguyên tệp ảnh và giải thích rõ các nét mờ ở số 8 là chủ đích thử nghiệm. Biểu đồ benchmark dựng từ report đã lưu. Không tạo ảnh giả làm bằng chứng FPGA/camera. Project 2 và tài liệu sửa HDMI/Jupyter được giữ riêng, không chép vào repo này.

---

## English

### Preserved content and changes

The public package is curated from project 1, preserving exact RTL, model, checkpoint and paired bit/HWH bytes. App, inference and driver algorithms are unchanged. Validation paths were moved out of generated directories; scripts accept a user-selected Python interpreter instead of the author's environment. `.gitattributes` disables newline conversion to preserve `.mem`/RTL SHA256 values.

Existing tests exposed two preprocessing issues: an overly weak border rule and a contrast peak influenced by discarded speckles. The public version fixes two locations in `camera_demo/preprocess.py`, keeping the existing test assertions. The saved board report therefore still describes the same core/model/driver and must not be interpreted as a rerun of the public version's camera path. `provenance.json` retains original runtime hashes and records public runtime hashes separately.

Documentation was rewritten with complete Vietnamese and English sections. Windows launchers use relative paths. CI and an installer were added to help new users.

### Publish only the necessary material

The repository contains source, `.mem` model files, small test datasets, selected reports and evidence images. `.bit/.hwh`, the checkpoint and the board ZIP belong in Releases. Do not publish SD backup `.img` files, environments, the full MNIST dataset, camera captures, Vivado installers, vendor board files, `.Xil`, temporary logs or build caches.

The software demo image is retained unchanged, with a caption identifying the CPU backend. Camera images of digits 4 and 8 are added at the author's request, preserving their original files and explaining that the faint strokes on digit 8 were deliberately introduced for the experiment. The benchmark chart is generated from the saved report. No synthetic image is used as FPGA/camera evidence. Project 2 and its HDMI/Jupyter repair documents remain separate and are not copied into this repository.
