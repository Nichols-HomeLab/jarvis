import { FilesetResolver, HandLandmarker } from "@mediapipe/tasks-vision";
import { requireSession } from "./auth";

await requireSession();

const video = document.getElementById("gesture-video") as HTMLVideoElement;
const status = document.getElementById("gesture-status") as HTMLParagraphElement;
const start = document.getElementById("start-gestures") as HTMLButtonElement;
const stop = document.getElementById("stop-gestures") as HTMLButtonElement;
const calibrate = document.getElementById("calibrate-gestures") as HTMLButtonElement;
let stream: MediaStream | null = null;
let landmarker: HandLandmarker | null = null;
let running = false;
let pinched = false;
let lastSent = 0;
let corners: Array<[number, number]> = [];
let mapping: number[] | null = JSON.parse(localStorage.getItem("jarvis-gesture-mapping") || "null");

function solveMapping(points: Array<[number, number]>): number[] {
  const destinations: Array<[number, number]> = [[0, 0], [1, 0], [1, 1], [0, 1]];
  const matrix: number[][] = [];
  points.forEach(([x, y], index) => {
    const [u, v] = destinations[index];
    matrix.push([x, y, 1, 0, 0, 0, -u * x, -u * y, u]);
    matrix.push([0, 0, 0, x, y, 1, -v * x, -v * y, v]);
  });
  for (let col = 0; col < 8; col++) {
    let pivot = col;
    for (let row = col + 1; row < 8; row++) if (Math.abs(matrix[row][col]) > Math.abs(matrix[pivot][col])) pivot = row;
    if (Math.abs(matrix[pivot][col]) < 1e-9) throw new Error("Corners are too close together");
    [matrix[col], matrix[pivot]] = [matrix[pivot], matrix[col]];
    const divisor = matrix[col][col];
    for (let value = col; value < 9; value++) matrix[col][value] /= divisor;
    for (let row = 0; row < 8; row++) {
      if (row === col) continue;
      const factor = matrix[row][col];
      for (let value = col; value < 9; value++) matrix[row][value] -= factor * matrix[col][value];
    }
  }
  return matrix.map(row => row[8]);
}

function mapPoint(x: number, y: number): [number, number] {
  if (!mapping) return [1 - x, y];
  const [a, b, c, d, e, f, g, h] = mapping;
  const denominator = g * x + h * y + 1;
  return [(a * x + b * y + c) / denominator, (d * x + e * y + f) / denominator];
}

calibrate.addEventListener("click", () => {
  corners = [];
  status.textContent = "Click projected top-left corner in the video";
});

video.addEventListener("click", event => {
  if (corners.length === 0 && !status.textContent?.startsWith("Click projected")) return;
  const rectangle = video.getBoundingClientRect();
  corners.push([(event.clientX - rectangle.left) / rectangle.width, (event.clientY - rectangle.top) / rectangle.height]);
  const labels = ["top-right", "bottom-right", "bottom-left"];
  if (corners.length < 4) status.textContent = `Click projected ${labels[corners.length - 1]} corner in the video`;
  else {
    try {
      mapping = solveMapping(corners);
      localStorage.setItem("jarvis-gesture-mapping", JSON.stringify(mapping));
      status.textContent = "Camera-to-projector mapping saved";
    } catch (error) {
      status.textContent = String(error);
    }
    corners = [];
  }
});

async function sendGesture(type: string, x: number, y: number) {
  if (performance.now() - lastSent < 60 && type === "move") return;
  lastSent = performance.now();
  await fetch("/api/v2/projector/gesture", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, x, y }),
  });
}

async function loop() {
  if (!running || !landmarker) return;
  if (video.readyState >= 2) {
    const result = landmarker.detectForVideo(video, performance.now());
    const landmarks = result.landmarks[0];
    if (landmarks) {
      const thumb = landmarks[4];
      const index = landmarks[8];
      const wrist = landmarks[0];
      const middle = landmarks[9];
      const pinchDistance = Math.hypot(thumb.x - index.x, thumb.y - index.y);
      const handSize = Math.hypot(wrist.x - middle.x, wrist.y - middle.y);
      const isPinched = pinchDistance < handSize * 0.35;
      const [mappedX, mappedY] = mapPoint(index.x, index.y);
      const x = Math.max(0, Math.min(1, mappedX));
      const y = Math.max(0, Math.min(1, mappedY));
      if (isPinched && !pinched) void sendGesture("grab", x, y);
      else if (isPinched) void sendGesture("move", x, y);
      else if (pinched) void sendGesture("release", x, y);
      pinched = isPinched;
      status.textContent = isPinched ? "Dragging projection" : "Hand visible; pinch to grab";
    } else {
      if (pinched) void sendGesture("release", 0, 0);
      pinched = false;
      status.textContent = "Searching for hand";
    }
  }
  requestAnimationFrame(loop);
}

start.addEventListener("click", async () => {
  start.disabled = true;
  try {
    const vision = await FilesetResolver.forVisionTasks("/gestures");
    landmarker = await HandLandmarker.createFromOptions(vision, {
      baseOptions: { modelAssetPath: "/gestures/hand_landmarker.task" },
      runningMode: "VIDEO", numHands: 1,
    });
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
    video.srcObject = stream;
    await video.play();
    running = true;
    stop.disabled = false;
    loop();
  } catch (error) {
    status.textContent = `Gesture camera failed: ${error}`;
    start.disabled = false;
  }
});

stop.addEventListener("click", () => {
  running = false;
  stream?.getTracks().forEach(track => track.stop());
  stream = null;
  landmarker?.close();
  landmarker = null;
  start.disabled = false;
  stop.disabled = true;
  status.textContent = "Camera stopped";
});
