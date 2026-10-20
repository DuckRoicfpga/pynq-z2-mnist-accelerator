"""One isolated digit in a fixed camera ROI -> raw MNIST-style UINT8 pixels."""
from dataclasses import dataclass
from collections import deque

import numpy as np
from PIL import Image, ImageOps, ImageFilter


@dataclass
class PreparedDigit:
    pixels: np.ndarray
    status: str
    message: str
    ink_fraction: float = 0.0


def otsu_threshold(array):
    hist = np.bincount(array.reshape(-1), minlength=256).astype(np.float64)
    count = hist.cumsum()
    total = count[-1]
    weighted = (hist * np.arange(256)).cumsum()
    denominator = count * (total - count)
    between = np.zeros(256)
    valid = denominator > 0
    between[valid] = (weighted[-1] * count[valid] - weighted[valid] * total)**2 / denominator[valid]
    return int(np.argmax(between))


def components(mask):
    """8-connected components, keeping geometry so small camera speckles can be removed."""
    pending = mask.copy()
    height, width = mask.shape
    found = []
    for sy, sx in np.argwhere(mask):
        sy, sx = int(sy), int(sx)
        if not pending[sy, sx]:
            continue
        queue = deque([(sy, sx)])
        pending[sy, sx] = False
        pixels = []
        while queue:
            y, x = queue.popleft()
            pixels.append((y, x))
            for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < width and pending[ny, nx]:
                    pending[ny, nx] = False
                    queue.append((ny, nx))
        found.append(np.array(pixels, dtype=np.int32))
    return sorted(found, key=len, reverse=True)


def prepare_digit(image, polarity="dark"):
    if polarity not in ("dark", "light"):
        raise ValueError("Chọn nét đen trên nền sáng hoặc nét sáng trên nền đen.")
    gray_image = ImageOps.grayscale(ImageOps.exif_transpose(image))
    gray_image.thumbnail((320, 320), Image.Resampling.LANCZOS)
    gray = np.asarray(gray_image, dtype=np.uint8)
    empty = np.zeros((28, 28), dtype=np.uint8)
    if min(gray.shape) < 28:
        return PreparedDigit(empty, "no_digit", "Ảnh quá nhỏ; đưa chữ số rõ hơn vào khung.")

    # Adaptive background subtraction:
    # Estimates local paper illumination with Gaussian blur to cancel room lighting, glare & shadows.
    bg_image = gray_image.filter(ImageFilter.GaussianBlur(radius=15))
    g_arr = np.array(gray_image, dtype=np.int16)
    bg_arr = np.array(bg_image, dtype=np.int16)

    if polarity == "dark":
        diff = np.clip(bg_arr - g_arr, 0, 255).astype(np.uint8)
    else:
        diff = np.clip(g_arr - bg_arr, 0, 255).astype(np.uint8)

    # Reject blank / nearly uniform paper before proceeding
    if int(diff.max()) < 18:
        return PreparedDigit(empty, "no_digit", "Chưa thấy chữ số. Đưa một số 0–9 vào khung.")

    th = otsu_threshold(diff)
    effective_th = max(th, 14)
    raw_mask = diff > effective_th
    fraction = float(raw_mask.mean())

    if fraction < 0.001:
        return PreparedDigit(empty, "no_digit", "Chữ số quá nhỏ hoặc chưa có nét viết.", fraction)
    if fraction > 0.55:
        return PreparedDigit(empty, "invalid_roi", "Khung có quá nhiều vùng tối; chỉnh ánh sáng hoặc màu nền.", fraction)

    # Morphological dilation (1-pixel expansion) to thicken ballpoint/thin strokes to MNIST width
    thick_mask = Image.fromarray((raw_mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(size=3))
    mask = np.array(thick_mask) > 0

    groups = components(mask)
    if not groups:
        return PreparedDigit(empty, "no_digit", "Chưa thấy nét chữ đủ rõ.", fraction)
    largest = groups[0]
    if len(largest) < max(12, mask.size * 0.001):
        return PreparedDigit(empty, "no_digit", "Chưa thấy nét chữ đủ rõ.", fraction)

    y0, x0 = largest.min(axis=0)
    y1, x1 = largest.max(axis=0) + 1
    span = max(y1 - y0, x1 - x0)
    if span < min(gray.shape) * 0.08:
        return PreparedDigit(empty, "no_digit", "Đưa chữ số gần camera hơn.", fraction)

    # Merge nearby disconnected strokes; discard unrelated speckles.
    selected = np.zeros_like(mask)
    margin = max(3, int(span * 0.25))
    for group in groups:
        gy0, gx0 = group.min(axis=0)
        gy1, gx1 = group.max(axis=0) + 1
        if len(group) >= max(3, len(largest) * 0.02) and gx0 <= x1 + margin and gx1 >= x0 - margin and gy0 <= y1 + margin and gy1 >= y0 - margin:
            selected[group[:, 0], group[:, 1]] = True

    ys, xs = np.where(selected)
    if len(ys) == 0:
        return PreparedDigit(empty, "no_digit", "Chưa thấy chữ số.", fraction)

    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1

    # A selected stroke touching the outer border may be clipped.
    h, w = gray.shape
    border_pixels = int(np.sum(selected[0, :]) + np.sum(selected[h-1, :]) + np.sum(selected[:, 0]) + np.sum(selected[:, w-1]))
    if border_pixels > 0:
        return PreparedDigit(empty, "invalid_roi", "Chữ tràn mép khung; đưa toàn bộ chữ số vào giữa.", fraction)

    # Contrast enhancement on stroke
    # Discarded speckles must not set the contrast of the selected digit.
    selected_peak = int(diff[selected].max())
    foreground = np.where(selected, np.maximum(diff, int(selected_peak * 0.65)), 0).astype(np.float64)
    peak = float(foreground.max())
    foreground = np.clip(np.rint(foreground * 255.0 / max(peak, 1.0)), 0, 255).astype(np.uint8)

    crop = Image.fromarray(foreground[y0:y1, x0:x1])
    scale = 20.0 / max(crop.size)
    target_w = max(1, round(crop.width * scale))
    target_h = max(1, round(crop.height * scale))
    crop = crop.resize((target_w, target_h), Image.Resampling.LANCZOS)

    canvas = Image.new("L", (28, 28), 0)
    canvas.paste(crop, ((28 - target_w) // 2, (28 - target_h) // 2))

    values = np.asarray(canvas, dtype=np.float64)
    yy, xx = np.indices(values.shape)
    mass = values.sum()
    if not mass:
        return PreparedDigit(empty, "no_digit", "Chưa thấy chữ số.", fraction)

    dx = int(round(13.5 - (values * xx).sum() / mass))
    dy = int(round(13.5 - (values * yy).sum() / mass))
    centered = Image.new("L", (28, 28), 0)
    centered.paste(canvas, (dx, dy))
    return PreparedDigit(np.array(centered, dtype=np.uint8), "ok", "Ảnh đã sẵn sàng để nhận diện.", fraction)
