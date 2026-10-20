# Hardware build / Phần cứng

[Tiếng Việt](#tiếng-việt) · [English below](#english)

## Tiếng Việt

### Điểm vào

Thiết kế dùng Zynq-7020 `xc7z020clg400-1`, Vivado 2022.2, PYNQ-Z2 preset và clock 100 MHz. Các script trong `scripts/` tạo IP AXI4-Lite, block design PS/PL và bitstream. Hướng dẫn chuẩn bị model/dataset/board files và lệnh build đầy đủ nằm trong [REPRODUCING](../docs/REPRODUCING.md); bản đồ thanh ghi nằm trong [ARCHITECTURE](../docs/ARCHITECTURE.md).

Nguồn `.mem` khi build ở `output/fpga_mem/` được helper chuẩn bị từ `camera_demo/model/`. Build phát sinh trong `hardware/build/`, `hardware/ip_repo/` và `output/stage3/`. Không commit các thư mục này. Bundle do build tạo mô tả kết quả build mới; báo cáo board lưu trong repository là bằng chứng riêng của bản phát hành đã có.

---

## English

### Entry points

The design uses Zynq-7020 `xc7z020clg400-1`, Vivado 2022.2, the PYNQ-Z2 preset and a 100 MHz clock. Scripts in `scripts/` create the AXI4-Lite IP, PS/PL block design and bitstream. Model/dataset/board-file preparation and complete build commands are in [REPRODUCING](../docs/REPRODUCING.md); the register map is in [ARCHITECTURE](../docs/ARCHITECTURE.md).

The helper prepares build `.mem` sources under `output/fpga_mem/` from `camera_demo/model/`. Build output is generated in `hardware/build/`, `hardware/ip_repo/` and `output/stage3/`. Do not commit these directories. A newly built bundle describes the new build results; the saved board report in the repository is separate evidence for the existing release.
