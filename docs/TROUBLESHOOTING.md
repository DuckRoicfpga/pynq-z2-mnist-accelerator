# Troubleshooting / Lỗi và cách xử lý

[Tiếng Việt](#tiếng-việt) · [English below](#english)

## Tiếng Việt

### Lỗi phần cứng đã có bằng chứng

| Hiện tượng / vấn đề | Cách xử lý và bằng chứng |
|---|---|
| Stage2 mô phỏng đúng nhưng timing 100 MHz không đạt: WNS -2.614 ns, DSP chưa được suy ra | Tách pipeline đường nhân/cộng và điều chỉnh reset đồng bộ để tổng hợp RAM/DSP; build cuối dùng 1 DSP, setup +0.906 ns, hold +0.043 ns. Đối chiếu `stage2_historical.json`, RTL hiện tại và `implementation_manifest.json`. |
| Tích hợp PS/AXI có cảnh báo clock và preset | Tcl lấy clock GP0 từ FCLK0 100 MHz, trả derived frequency về DEFAULT để Vivado lan truyền clock. Giữ preset DDR của vendor; cảnh báo PSU-1..4 còn được ghi trong manifest. |
| Nguy cơ sai ảnh/trọng số giữa Python, testbench và bitstream | Kiểm tra sáu `.mem`, cấu hình shift, SHA256 bit/HWH và fingerprint; dùng golden 120 ca trước khi tin kết quả. Không đổi tên/cặp model tùy ý. |
| START khi chưa nạp đủ ảnh hoặc trạng thái DONE cũ | Wrapper kiểm tra số byte, báo mã lỗi; driver ACK, upload 196 word, START, poll có timeout và ACK sau đọc. `soft_reset()` hủy tác vụ và vô hiệu ảnh cũ. |

Không suy luận rằng mọi lỗi treo cũ đều có cùng nguyên nhân. Số chu kỳ tăng từ bản lịch sử 110006 lên 110208 là đặc điểm bản cuối có pipeline, không phải bằng chứng board chạy chậm vì hỏng.

### Demo, camera và lỗi phát hiện khi đóng gói

| Triệu chứng | Hướng xử lý |
|---|---|
| Camera không mở qua HTTP IP board | Mở giao diện tại localhost của laptop và dùng backend remote; trình duyệt cần secure context/quyền camera. |
| Mẫu MNIST đúng nhưng chữ trên giấy sai | Xem ảnh 28×28: polarity, bóng, nét mảnh, ROI bị cắt, nhiễu và khác biệt phân phối so với MNIST. Không dùng một ảnh đúng để tuyên bố accuracy camera. |
| Chữ chạm mép vẫn được chấp nhận | Kiểm thử publication phát hiện ngưỡng cũ đòi hơn 20% nét ở mép nên bỏ sót. Bản công khai từ chối thành phần chữ chạm biên. Đây là kiểm tra bảo thủ, cần đưa chữ vào giữa. |
| Đốm xa chữ thay đổi pixel chữ đã chuẩn hóa | Peak tương phản trước đây lấy toàn ảnh, nên nhiễu đã loại vẫn ảnh hưởng. Bản công khai lấy peak trên thành phần chữ đã chọn; test ảnh sạch/nhiễu trở lại khớp. |
| Cổng 8765/8766 đã có chương trình dùng | Dừng server cũ bằng Ctrl+C trước khi mở bản khác; không chạy hai app cùng cổng. |
| Remote báo model/backend sai hoặc board lỗi | Chạy self-test trên board, xác nhận `--backend fpga`, IP/port và fingerprint. Lỗi được trả thẳng, không ẩn bằng fallback CPU. |
| `^[[200~uptime: command not found` | Terminal nhận chuỗi bracketed-paste thay vì lệnh thuần; Ctrl+C và gõ lại lệnh, không phải lỗi FPGA. |

Hai sửa đổi tiền xử lý chỉ nằm trong bản publication, được kiểm thử host; không thay RTL, model hoặc driver. Chưa đo lại camera/board cho bản tiền xử lý này. Xem [ghi chú publication](PUBLICATION_NOTES.md).

### Sự cố hệ thống đã quan sát nhưng chưa kết luận nguyên nhân

Board từng ghi lỗi EXT4 `Directory block failed checksum`, bitmap/htree và Win32 Disk Imager từng báo `Verification failed at sector: 0`. Sao lưu SD image đã hoàn tất; ghi lại image hệ điều hành cũng báo thành công, nhưng verification lỗi sector 0 vẫn xuất hiện trong trao đổi. Việc chương trình sau đó chạy được không chứng minh lỗi filesystem/SD đã hết. Chưa có bằng chứng phân biệt chắc chắn thẻ, đầu đọc hay phần mềm verify; không ghi trạng thái “đã sửa hoàn toàn”.

LED tắt/bật, Jupyter mất kết nối hay một tiến trình không trả log chưa đủ để xác định thiếu nguồn, reset, kernel crash hay lỗi phần mềm. Cần uptime, danh sách tiến trình, log kernel/UART và nguồn phù hợp để phân biệt. `/sys/class/fpga_manager/fpga0/state = operating` chỉ cho biết trạng thái FPGA manager, không chứng minh kết quả MLP đúng.

Trang trắng Jupyter, Dead Kernel/VDMA/HDMI và sửa MMIO polling của **dự án 2** không được gán thành lỗi/sửa lỗi MLP của dự án 1. Dự án 1 hiện dùng terminal, HTTP và AXI4-Lite. Khi có lỗi mới, giữ log cùng bước tái hiện; không sửa filesystem đang mount chỉ dựa trên suy đoán.

---

## English

### Hardware issues supported by evidence

| Symptom / issue | Remedy and evidence |
|---|---|
| Stage2 simulation passed but 100 MHz timing failed: WNS -2.614 ns, no inferred DSP | Pipeline the multiply/accumulate path and adjust synchronous reset for RAM/DSP inference; the final build uses 1 DSP, setup +0.906 ns and hold +0.043 ns. Compare `stage2_historical.json`, the current RTL and `implementation_manifest.json`. |
| PS/AXI integration clock and preset warnings | Tcl derives the GP0 clock from 100 MHz FCLK0 and restores the derived frequency source to DEFAULT for Vivado clock propagation. The vendor DDR preset is retained; PSU-1..4 warnings remain recorded in the manifest. |
| Risk of different images/weights in Python, testbenches and bitstream | Check the six `.mem` files, shift configuration, bit/HWH SHA256 values and fingerprint; verify 120 golden cases before trusting results. Do not arbitrarily substitute model/overlay pairs. |
| START before uploading a full image, or stale DONE status | The wrapper checks the byte count and reports an error code; the driver ACKs, uploads 196 words, starts, polls with a timeout and ACKs after reading. `soft_reset()` aborts work and invalidates the previous image. |

Do not assume every historical hang has the same cause. The increase from the historical 110006 cycles to the final 110208 cycles reflects the pipelined final design; it does not establish damaged hardware.

### Demo, camera and packaging-time findings

| Symptom | Action |
|---|---|
| Camera cannot open through the board's HTTP IP | Open the interface on laptop localhost using remote mode; the browser requires a secure context and camera permission. |
| MNIST samples pass but paper digits fail | Inspect the 28×28 image for polarity, shadows, thin strokes, clipping, noise and distribution differences from MNIST. One correct image does not establish camera accuracy. |
| Border-touching digits were accepted | Publication checks found that the earlier rule required over 20% of the stroke on the border and missed clipping. The public version rejects selected digit components touching the border. This is conservative; center the digit. |
| A distant speckle changed normalized digit pixels | Contrast peak previously used the complete image, allowing discarded noise to affect the digit. The public version uses the selected digit component's peak; clean/noisy sample tests match again. |
| Port 8765/8766 is occupied | Stop the previous server with Ctrl+C before starting another; do not run two apps on the same port. |
| Remote reports the wrong model/backend or a board error | Run the board self-test and check `--backend fpga`, IP/port and fingerprint. Errors are returned directly, without hiding them through CPU fallback. |
| `^[[200~uptime: command not found` | The terminal received a bracketed-paste escape sequence instead of a plain command; press Ctrl+C and type the command again. This is not an FPGA fault. |

The two preprocessing fixes apply only to the publication copy and were host-tested; RTL, model and driver are unchanged. Camera/board measurements were not rerun for this preprocessing revision. See [publication notes](PUBLICATION_NOTES.md).

### Observed system issues without a confirmed root cause

The board previously logged EXT4 `Directory block failed checksum`, bitmap/htree errors, and Win32 Disk Imager reported `Verification failed at sector: 0`. An SD image backup completed; rewriting the OS image also reported success, but sector 0 verification failures still appeared in the conversation. Later successful application runs do not prove that filesystem/SD issues have disappeared. Evidence does not conclusively separate card, reader and verification software causes; this is not marked “fully fixed.”

LED changes, Jupyter disconnection or a silent process do not distinguish inadequate power, reset, a kernel crash or application failure. Uptime, process lists, kernel/UART logs and an appropriate supply are needed to distinguish them. `/sys/class/fpga_manager/fpga0/state = operating` only describes the FPGA manager state and does not establish correct MLP results.

The white Jupyter page, Dead Kernel/VDMA/HDMI issues and MMIO polling fix from **project 2** are not attributed to project 1's MLP. Project 1 uses a terminal, HTTP and AXI4-Lite. For a new issue, retain logs and reproduction steps; do not repair a mounted filesystem based solely on an assumed cause.
