# Validation and performance / Kiểm chứng và hiệu năng

[Tiếng Việt](#tiếng-việt) · [English below](#english)

## Tiếng Việt

### Nguồn bằng chứng

| Tệp trong `evidence/` | Phạm vi |
|---|---|
| `stage1_evaluation.json` | Checkpoint, lượng tử hóa, 10000 ảnh MNIST |
| `stage2_historical.json` | Mô phỏng ban đầu và timing FAIL lịch sử |
| `implementation_manifest.json` | Build cuối, timing, tài nguyên, hash RTL/trọng số/overlay |
| `recorded_board_verification.json` | Báo cáo board đã lưu: 120 ca, reset, 50 benchmark |
| `provenance.json` | Đối chiếu hash/fingerprint và phạm vi đóng gói |
| `host_checks.json` | Kết quả kiểm thử cục bộ của bản công khai |

`actual_board_test_performed: false` trong manifest build không mâu thuẫn với báo cáo board riêng: hai tệp mô tả hai bước khác nhau. Ngày giờ báo cáo board (2025-05-03) sớm hơn header bitstream (2026-10-16); chưa xác lập thời điểm đo tuyệt đối và không suy đoán nguyên nhân. Lần chuẩn bị publication không chạy lại board, train hay Vivado.

### Tính đúng và accuracy

Host đối chiếu cả ba tầng trên 120 ca và **24240 giá trị** với golden fixtures. Báo cáo build ghi core regression 120/120 và AXI regression 120/120; bộ test còn kiểm tra handshake, nạp pixel, timeout và reset. Báo cáo board ghi mọi ca khớp dự đoán tham chiếu, đúng **110208 chu kỳ**, **100000000 Hz**, cùng soft reset PASS.

Đánh giá MNIST được lưu: float32 **97.56%**, trọng số lượng tử hóa nhưng tính float **97.58%**, đường số nguyên **97.64%**, trên 10000 ảnh. Export đã chọn shift bằng tập test; các con số này mô tả cấu hình hiện có, không phải kết quả trên holdout độc lập. Hình `training-history.png` hiển thị mốc 97.58% của phiên bản lượng tử hóa/tính float, khác đường số nguyên 97.64%; không tráo hai con số.

120 ca gồm ảnh MNIST, mẫu biên và lặp lại, dùng kiểm chứng implementation. Sự khớp giữa FPGA và mô hình không đo chất lượng nhận diện camera. Report có 0 mẫu camera có nhãn, vì vậy chưa công bố phần trăm accuracy camera. Hai ảnh demo camera số 4 và số 8 do tác giả cung cấp được bổ sung riêng trong [CAMERA_DEMO](CAMERA_DEMO.md); chúng không thay đổi dữ liệu của report cũ.

### Đọc benchmark đúng cách

| Phép đo lưu trên ARM, 50 lần | Trung bình |
|---|---|
| NumPy integer reference | 6.382997 ms |
| Toàn lời gọi `ai.predict()` | 1.995950 ms |
| Driver `total_ms` nội bộ | 1.313451 ms |
| Lõi FPGA từ cycle counter | 1.102080 ms |

Tỷ số 6.382997/1.995950 ≈ **3.20×**, chỉ so với NumPy integer reference trên cùng ARM; chưa so với thư viện CPU C/SIMD được tối ưu. Các khoảng thời gian có phần chồng lên nhau, **không cộng bốn hàng**. `total_ms` bắt đầu sau một số thao tác Python/packing; lời gọi ngoài cùng gồm thêm các thao tác này.

Benchmark gọi driver trực tiếp, không gồm HTTP/camera và lớp đối chiếu NumPy của demo. Không suy từ 1.102080 ms ra FPS camera/web đảm bảo. Muốn đo mới, dùng `verify_board.py --benchmark-repeats 100`, ghi rõ môi trường và lưu report mới riêng.

### Timing và kiểm thử hiện tại

Build cuối: setup +0.906 ns, hold +0.043 ns, không có DRC Error/Critical Warning; còn cảnh báo không critical DPIP-1, DPOP-2 và cảnh báo DDR preset PSU-1..4. Tài nguyên sau route: 2211 LUT, 2002 FF, 34 RAMB36 + 2 RAMB18 (35 BRAM tile), 1 DSP. Bản stage2 lịch sử có WNS -2.614 ns và 110006 chu kỳ; không dùng các giá trị lịch sử này để mô tả bản cuối.

Để chạy kiểm tra host, dùng `python -B scripts/check_repository.py` sau khi cài `requirements.txt`. Bộ kiểm tra không cần PYNQ/Vivado/board: kiểm tra AST, hash mô hình và RTL, 120 ca từ báo cáo, HTTP, xử lý ảnh và driver giả lập. CI cung cấp Python 3.10/3.12 trên Ubuntu; lần đóng gói chạy cục bộ Python 3.12. Chi tiết số test thực chạy nằm trong `evidence/host_checks.json`, không thay thế bài thử board.

---

## English

### Evidence sources

| File in `evidence/` | Scope |
|---|---|
| `stage1_evaluation.json` | Checkpoint, quantization and 10000 MNIST images |
| `stage2_historical.json` | Initial simulation and historical failing timing |
| `implementation_manifest.json` | Final build, timing, resources, RTL/weight/overlay hashes |
| `recorded_board_verification.json` | Saved board report: 120 cases, reset, 50 benchmark repeats |
| `provenance.json` | Hash/fingerprint comparison and packaging scope |
| `host_checks.json` | Local tests of the public package |

The build manifest's `actual_board_test_performed: false` does not conflict with the separate board report: the files describe different stages. The board report timestamp (2025-05-03) predates the bitstream header (2026-10-16); the absolute measurement time has not been established and its cause is not assumed. Publication preparation did not rerun the board, training or Vivado.

### Correctness and accuracy

Host checks compare all three layers for 120 cases and **24240 values** against golden fixtures. The build report records core regression 120/120 and AXI regression 120/120; the tests also cover handshake, pixel upload, timeout and reset. The saved board report records reference-matching predictions for every case, **110208 cycles**, **100000000 Hz**, and a passing soft reset.

Recorded MNIST evaluation: float32 **97.56%**, quantized weights with float arithmetic **97.58%**, and the integer path **97.64%**, on 10000 images. The export selected shifts using the test set; these numbers describe the existing configuration rather than an independent holdout result. `training-history.png` shows the 97.58% quantized-weight/float result, which differs from the 97.64% integer path; do not interchange the two.

The 120 cases include MNIST images, edge patterns and repeated inputs to verify implementation. Agreement between FPGA and the model does not measure camera recognition quality. The report has 0 labeled camera samples, so no camera accuracy percentage is published. The author-provided camera examples of digits 4 and 8 are documented separately in [CAMERA_DEMO](CAMERA_DEMO.md); they do not change the original report data.

### Interpreting the benchmark

| Saved ARM measurement, 50 repeats | Mean |
|---|---|
| NumPy integer reference | 6.382997 ms |
| Complete `ai.predict()` call | 1.995950 ms |
| Internal driver `total_ms` | 1.313451 ms |
| FPGA core from cycle counter | 1.102080 ms |

The ratio 6.382997/1.995950 ≈ **3.20×** compares only against the NumPy integer reference on the same ARM; it is not a comparison against optimized C/SIMD CPU libraries. These timing intervals overlap, so **do not add the four rows**. `total_ms` starts after some Python/packing operations; the outer call includes those additional operations.

The benchmark calls the driver directly, excluding HTTP/camera capture and the demo's NumPy comparison wrapper. The 1.102080 ms core time does not establish a guaranteed camera/web FPS. For a new measurement, run `verify_board.py --benchmark-repeats 100`, record the environment and save the new report separately.

### Timing and current host checks

Final build: setup +0.906 ns, hold +0.043 ns, no DRC Error/Critical Warning; noncritical DPIP-1, DPOP-2 and DDR preset PSU-1..4 warnings remain. Post-route resources: 2211 LUT, 2002 FF, 34 RAMB36 + 2 RAMB18 (35 BRAM tiles), 1 DSP. The historical stage2 result has WNS -2.614 ns and 110006 cycles; those historical values do not describe the final build.

Run host checks with `python -B scripts/check_repository.py` after installing `requirements.txt`. These checks require no PYNQ/Vivado/board: they cover AST parsing, model/RTL hashes, 120 recorded report cases, HTTP, preprocessing and a mocked driver. CI is configured for Python 3.10/3.12 on Ubuntu; packaging was checked locally using Python 3.12. Actual executed test counts are in `evidence/host_checks.json`; host checks do not replace board tests.
