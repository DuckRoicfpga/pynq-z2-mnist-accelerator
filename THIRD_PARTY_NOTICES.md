# Attribution and third-party notices

[Tiếng Việt](#tiếng-việt) · [English below](#english)

## Tiếng Việt

### Mã nguồn và công cụ

Mã nguồn gốc do Tran Minh Duc (Xavier) phát hành theo MIT, xem `LICENSE`. Điều này không đổi giấy phép của PYNQ, NumPy, Pillow, PyTorch, torchvision, matplotlib, GitHub Actions, Vivado hay IP/preset của AMD/Xilinx/TUL.

Các dependency được cài từ nguồn của chúng, không đóng gói thư viện hay bộ cài vào repository. Vivado và vendor board/IP files phải được sử dụng theo điều khoản nhà cung cấp; người rebuild tự cài các thành phần đó. Bitstream Release chứa thiết kế tích hợp trên nền IP của vendor; MIT của source tự viết không thay các quyền/điều kiện của thành phần vendor.

Tham khảo chính: [PYNQ MMIO](https://pynq.readthedocs.io/en/v2.6.1/pynq_libraries/mmio.html), [torchvision MNIST](https://docs.pytorch.org/vision/main/generated/torchvision.datasets.MNIST.html), [torchvision MNIST loader](https://github.com/pytorch/vision/blob/main/torchvision/datasets/mnist.py).

### Dữ liệu và hình ảnh

MNIST được ghi công cho **Yann LeCun, Corinna Cortes và Christopher J. C. Burges**, bắt nguồn từ dữ liệu NIST; xem [MNIST catalog và citation](https://github.com/tensorflow/datasets/blob/master/docs/catalog/mnist.md). Repo chỉ giữ mẫu/fixtures nhỏ cần kiểm thử, cùng trọng số suy ra từ huấn luyện; không chứa toàn bộ dataset.

MIT của mã dự án không tự cấp lại quyền dữ liệu MNIST hoặc nội dung bên thứ ba trong hình. Người dùng cần xem điều kiện tại nguồn dataset trước khi phân phối lại; không suy từ giấy phép loader sang giấy phép dataset. Ảnh giao diện và biểu đồ được lưu với phạm vi sử dụng minh họa dự án, không tuyên bố quyền sở hữu dữ liệu gốc. Không có video/captures camera riêng tư trong gói công khai.

---

## English

### Source and tools

Original project source by Tran Minh Duc (Xavier) is released under MIT; see `LICENSE`. This does not change the licenses of PYNQ, NumPy, Pillow, PyTorch, torchvision, matplotlib, GitHub Actions, Vivado or AMD/Xilinx/TUL IP/presets.

Dependencies are installed from their own sources; their libraries and installers are not bundled in the repository. Vivado and vendor board/IP files must be used under the suppliers' terms; users rebuilding the design install those components themselves. The Release bitstream integrates the design with vendor IP; the MIT license for original source does not replace vendor component rights/conditions.

Primary references: [PYNQ MMIO](https://pynq.readthedocs.io/en/v2.6.1/pynq_libraries/mmio.html), [torchvision MNIST](https://docs.pytorch.org/vision/main/generated/torchvision.datasets.MNIST.html), [torchvision MNIST loader](https://github.com/pytorch/vision/blob/main/torchvision/datasets/mnist.py).

### Data and images

MNIST is credited to **Yann LeCun, Corinna Cortes and Christopher J. C. Burges**, originating from NIST data; see the [MNIST catalog and citation](https://github.com/tensorflow/datasets/blob/master/docs/catalog/mnist.md). The repository retains only small test samples/fixtures and weights derived from training, rather than the complete dataset.

The project source MIT license does not automatically relicense MNIST data or third-party content in images. Users should consult the dataset source terms before redistribution; the loader's license does not establish the dataset's license. Saved interface images and charts illustrate the project without claiming ownership of the underlying data. The public package contains no private camera videos/captures.
