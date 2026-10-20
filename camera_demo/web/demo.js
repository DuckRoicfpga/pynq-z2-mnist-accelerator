"use strict";
const $ = (id) => document.getElementById(id);
let stream = null, generation = 0, running = false, latest = null;
let history = [], completions = [], config = null;
let lastConfidentDigit = null, lastConfidentTime = 0;
const capture = document.createElement("canvas");
capture.width = capture.height = 320;
const context = capture.getContext("2d");

function message(text, error = false) {
  $("message").textContent = text;
  $("message").className = error ? "error" : "";
}

async function api(path, payload) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(path, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload), signal: controller.signal,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Chương trình nhận diện báo lỗi.");
    return result;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("Nhận diện quá thời gian chờ; kiểm tra chương trình hoặc kết nối board.");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function preview(pixels) {
  const ctx = $("pixels").getContext("2d");
  const image = ctx.createImageData(28, 28);
  for (let i = 0; i < 784; i++) {
    image.data[i * 4] = image.data[i * 4 + 1] = image.data[i * 4 + 2] = pixels[i] || 0;
    image.data[i * 4 + 3] = 255;
  }
  ctx.putImageData(image, 0, 0);
}

function clearResult() {
  latest = null;
  lastConfidentDigit = null;
  lastConfidentTime = 0;
  history = []; completions = [];
  $("digit").textContent = "—";
  $("state").textContent = "Chưa có ảnh";
  $("detail").textContent = "Đưa một chữ số vào giữa khung.";
  for (const name of ["inference", "latency", "rate", "stability"]) $(name).textContent = "—";
  $("save").disabled = true;
  preview([]);
}

function render(result, elapsed, single = false) {
  preview(result.pixels);
  $("latency").textContent = `${elapsed.toFixed(0)} ms`;
  const now = performance.now();
  completions.push(now);
  completions = completions.filter((time) => now - time < 3000);
  const span = now - completions[0];
  $("rate").textContent = single ? "Ảnh đơn" : span > 500 ? `${((completions.length - 1) * 1000 / span).toFixed(1)} /s` : "Đang đo";

  if (result.status !== "ok") {
    history = [];
    latest = null;
    if (now - lastConfidentTime < 1500 && lastConfidentDigit !== null && !single) {
      $("digit").textContent = String(lastConfidentDigit);
      $("state").textContent = "Giữ kết quả vừa nhận";
      $("detail").textContent = result.message;
    } else {
      $("digit").textContent = "—";
      $("state").textContent = result.status === "no_digit" ? "Chưa thấy chữ số" : "Chỉnh lại khung ảnh";
      $("detail").textContent = result.message;
      $("inference").textContent = "—";
      $("stability").textContent = "—";
      $("save").disabled = true;
    }
    return;
  }

  latest = result;
  lastConfidentDigit = result.digit;
  lastConfidentTime = now;
  $("save").disabled = false;
  $("time-label").textContent = result.backend === "fpga" ? "FPGA tính toán" : "Python suy luận";
  $("inference").textContent = `${(result.fpga_compute_ms ?? result.inference_ms).toFixed(2)} ms`;

  history.push(result.digit);
  history = history.slice(-4);
  let consecutive = 0;
  for (let i = history.length - 1; i >= 0 && history[i] === result.digit; i--) consecutive++;
  const stable = single || consecutive >= 2;

  $("digit").textContent = String(result.digit);
  $("state").textContent = stable ? "Đã nhận diện (Ổn định)" : "Đang nhận diện";
  $("detail").textContent = single
    ? result.expected === undefined ? "Ảnh tải lên; cần đối chiếu với số thật." : `Nhãn mẫu: ${result.expected} · ${result.digit === result.expected ? "Khớp" : "Không khớp"}`
    : stable ? "Kết quả ổn định liên tục." : `Dự đoán mới nhất: ${result.digit}`;
  $("stability").textContent = single ? "Ảnh đơn" : `${Math.min(consecutive, 3)} / 3`;
}

function updateGuide() {
  const video = $("video"), viewport = $("viewport");
  if (!video.videoWidth) return;
  const fit = Math.min(viewport.clientWidth / video.videoWidth, viewport.clientHeight / video.videoHeight);
  const side = Math.min(video.videoWidth, video.videoHeight) * 0.62 * fit;
  Object.assign($("guide").style, {
    width: `${side}px`, height: `${side}px`,
    left: `${(viewport.clientWidth - side) / 2}px`, top: `${(viewport.clientHeight - side) / 2}px`, display: "block",
  });
}

function stopCamera(keepResult = true) {
  generation++;
  running = false;
  if (stream) stream.getTracks().forEach((track) => track.stop());
  stream = null;
  $("video").srcObject = null;
  $("guide").style.display = "none";
  $("placeholder").style.display = "flex";
  $("camera-status").textContent = "Camera đang tắt";
  $("start").disabled = !config;
  $("stop").disabled = true;
  $("sample").disabled = $("upload").disabled = !config;
  if (!keepResult) clearResult();
}

async function cameraLoop(token) {
  while (running && token === generation) {
    const started = performance.now();
    try {
      const video = $("video");
      if (!video.videoWidth || video.readyState < 2) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        continue;
      }
      const side = Math.min(video.videoWidth, video.videoHeight) * 0.62;
      context.drawImage(video, (video.videoWidth - side) / 2, (video.videoHeight - side) / 2, side, side, 0, 0, 320, 320);
      const result = await api("/api/predict", {image: capture.toDataURL("image/jpeg", 0.9), polarity: $("polarity").value});
      if (token !== generation) return;
      render(result, performance.now() - started);
    } catch (error) {
      if (token !== generation) return;
      stopCamera(false);
      $("state").textContent = "Nhận diện bị dừng";
      message(error.message, true);
      return;
    }
    // One request at a time: slow inference reduces cadence instead of queuing old frames.
    const wait = Math.max(0, Number($("interval").value) - (performance.now() - started));
    await new Promise((resolve) => setTimeout(resolve, wait));
  }
}

$("start").addEventListener("click", async () => {
  stopCamera(false);
  const token = generation;
  $("start").disabled = true;
  $("stop").disabled = false;
  $("sample").disabled = $("upload").disabled = true;
  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Mở demo tại http://127.0.0.1:8765 hoặc localhost bằng Chrome/Edge để dùng camera laptop.");
    }
    message("Cho phép trình duyệt dùng camera khi hộp thoại xuất hiện.");
    const acquired = await navigator.mediaDevices.getUserMedia({audio: false, video: {width: {ideal: 640}, height: {ideal: 480}}});
    if (token !== generation) { acquired.getTracks().forEach((track) => track.stop()); return; }
    stream = acquired;
    for (const track of acquired.getVideoTracks()) track.addEventListener("ended", () => {
      if (stream !== acquired) return;
      stopCamera(false);
      message("Camera đã ngắt kết nối. Kiểm tra camera rồi bấm Bật camera.", true);
    });
    $("video").srcObject = stream;
    await $("video").play();
    if (token !== generation) return;
    running = true;
    $("placeholder").style.display = "none";
    $("camera-status").textContent = "● Đang quay";
    updateGuide();
    message("Đưa một chữ số vào khung. Giữ giấy yên trong vài lần nhận diện.");
    cameraLoop(token);
  } catch (error) {
    if (token !== generation) return;
    stopCamera(false);
    const explanation = {
      NotAllowedError: "Camera chưa được cho phép. Cho phép camera cho trang này rồi bấm Bật camera.",
      NotFoundError: "Không tìm thấy camera trên laptop.",
      NotReadableError: "Không mở được camera; kiểm tra ứng dụng khác đang sử dụng camera.",
    };
    message(explanation[error.name] || error.message, true);
  }
});

$("stop").addEventListener("click", () => { stopCamera(); message("Đã tắt camera. Có thể ghi lại ảnh 28 × 28 vừa nhận để kiểm thử."); });
$("polarity").addEventListener("change", () => {
  clearResult();
  if (running) { generation++; cameraLoop(generation); }
});
window.addEventListener("resize", updateGuide);
window.addEventListener("pagehide", () => stopCamera());

$("sample").addEventListener("click", async () => {
  stopCamera(false);
  const token = generation;
  $("sample").disabled = true;
  try {
    const started = performance.now();
    const result = await api("/api/sample", {index: Number($("sample-index").value)});
    if (token !== generation) return;
    render(result, performance.now() - started, true);
    message(`Đã thử ảnh MNIST số ${result.expected}. Đây là ảnh mẫu có sẵn, không phải ảnh camera.`);
  } catch (error) { if (token === generation) message(error.message, true); }
  finally { if (token === generation) $("sample").disabled = false; }
});

$("upload").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", async () => {
  const file = $("file").files[0];
  if (!file) return;
  stopCamera(false);
  const token = generation;
  try {
    if (file.size > 1_400_000) throw new Error("Chọn ảnh dưới 1,4 MB, chứa một chữ số đã cắt riêng.");
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file);
    });
    if (token !== generation) return;
    const started = performance.now();
    const result = await api("/api/predict", {image: dataUrl, polarity: $("polarity").value});
    if (token !== generation) return;
    render(result, performance.now() - started, true);
    message("Đã xử lý ảnh tải lên. Nếu nền đen và nét sáng, đổi Màu nét rồi thử lại.");
  } catch (error) { if (token === generation) message(error.message, true); }
  finally { $("file").value = ""; }
});

$("save").addEventListener("click", async () => {
  if (!latest) return;
  const pixels = [...latest.pixels];
  const label = Number($("label").value);
  stopCamera();
  $("save").disabled = true;
  try {
    const saved = await api("/api/save", {pixels, label});
    message(`Đã ghi mẫu: nhãn thật ${saved.label}, dự đoán ${saved.digit} (${saved.correct ? "đúng" : "sai"}). Camera đã dừng để giữ đúng mẫu vừa chọn.`);
  } catch (error) { message(error.message, true); }
  finally { $("save").disabled = !latest; }
});

async function initialize() {
  for (let digit = 0; digit < 10; digit++) {
    for (const id of ["sample-index", "label"]) $(id).add(new Option(String(digit), String(digit)));
  }
  $("sample-index").value = "7";
  preview([]);
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error("Không đọc được cấu hình chương trình.");
    config = await response.json();
    const software = config.backend === "software";
    $("backend").textContent = software ? "Python INT8 · Chưa dùng FPGA" : config.backend === "remote" ? "FPGA · Kết nối qua mạng" : "FPGA · Chạy trên board";
    $("mode-note").textContent = software
      ? "Đang chạy Python với đúng trọng số INT8 đã xuất cho FPGA. Kết quả này giúp kiểm tra demo camera; chưa xác nhận board."
      : "Kết quả đến từ FPGA và được đối chiếu với Python INT8. Thời gian xử lý ảnh và truyền qua mạng được tính riêng trong độ trễ.";
    for (const id of ["start", "sample", "upload"]) $(id).disabled = false;
    message("Chương trình đã sẵn sàng. Bật camera hoặc thử ảnh MNIST số 7 trước.");
  } catch (error) { $("backend").textContent = "Chưa kết nối"; message(error.message, true); }
}
initialize();
