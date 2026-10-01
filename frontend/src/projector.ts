import { createSocket } from "./ws";
import { requireSession } from "./auth";

await requireSession();

type DetectionBox = {
  label: string;
  description?: string;
  box: number[];
  confidence: number;
};

type ProjectorMessage =
  | {
      type: "show_bounding_box";
      title: string;
      image: string;
      boxes: DetectionBox[];
    }
  | {
      type: "show_card";
      title: string;
      content: string;
      kind: string;
    }
  | {
      type: "show_dimensions";
      title: string;
      width_mm: number;
      depth_mm: number;
      height_mm?: number;
      source: string;
      calibrated_width_mm: number;
      calibrated_height_mm: number;
    }
  | { type: "gesture"; x: number; y: number; scale: number; [key: string]: unknown };

const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
const socket = createSocket(`${wsProto}//${window.location.host}/ws/projector`);

const statusEl = document.getElementById("projector-status") as HTMLDivElement;
const titleEl = document.getElementById("projector-title") as HTMLHeadingElement;
const cardView = document.getElementById("card-view") as HTMLDivElement;
const cardKind = document.getElementById("card-kind") as HTMLDivElement;
const cardContent = document.getElementById("card-content") as HTMLDivElement;
const bboxView = document.getElementById("bbox-view") as HTMLDivElement;
const bboxImage = document.getElementById("bbox-image") as HTMLImageElement;
const bboxOverlay = document.getElementById("bbox-overlay") as HTMLDivElement;
if (new URLSearchParams(window.location.search).has("calibrate")) document.getElementById("calibration-corners")?.classList.remove("hidden");
const dimensionView = document.getElementById("dimension-view") as HTMLDivElement;
const dimensionObject = document.getElementById("dimension-object") as HTMLDivElement;
const dimensionName = document.getElementById("dimension-name") as HTMLSpanElement;
const dimensionMeasurements = document.getElementById("dimension-measurements") as HTMLSpanElement;
const dimensionNote = document.getElementById("dimension-note") as HTMLParagraphElement;
const dimensionSource = document.getElementById("dimension-source") as HTMLAnchorElement;

let latestBoxes: DetectionBox[] = [];

function hideAll() {
  cardView.classList.add("hidden");
  bboxView.classList.add("hidden");
  dimensionView.classList.add("hidden");
}

function renderBoxes() {
  bboxOverlay.innerHTML = "";
  if (!bboxImage.naturalWidth || !bboxImage.naturalHeight) return;

  const displayWidth = bboxImage.clientWidth;
  const displayHeight = bboxImage.clientHeight;
  const xScale = displayWidth / bboxImage.naturalWidth;
  const yScale = displayHeight / bboxImage.naturalHeight;

  latestBoxes.forEach((item) => {
    const [x1, y1, x2, y2] = item.box;
    const box = document.createElement("div");
    box.className = "detected-box";
    box.style.left = `${x1 * xScale}px`;
    box.style.top = `${y1 * yScale}px`;
    box.style.width = `${(x2 - x1) * xScale}px`;
    box.style.height = `${(y2 - y1) * yScale}px`;

    const label = document.createElement("div");
    label.className = "detected-label";
    label.textContent = `${item.description || item.label} (${Math.round(item.confidence * 100)}%)`;
    box.appendChild(label);
    bboxOverlay.appendChild(box);
  });
}

bboxImage.addEventListener("load", renderBoxes);
window.addEventListener("resize", renderBoxes);

socket.onMessage((raw) => {
  const msg = raw as unknown as ProjectorMessage;
  statusEl.textContent = socket.isConnected() ? "connected" : "updating";

  if (msg.type === "gesture") {
    const action = String(msg["type"] === "gesture" ? msg["action"] || msg["gesture"] || "" : "");
    if (action === "move" || action === "grab") {
      dimensionObject.style.left = `${msg.x * 100}%`;
      dimensionObject.style.top = `${msg.y * 100}%`;
    }
    if (action === "scale") dimensionObject.style.transform = `translate(-50%, -50%) scale(${msg.scale})`;
    if (action === "clear") hideAll();
    return;
  }

  if (msg.type === "show_card") {
    hideAll();
    titleEl.textContent = msg.title;
    cardKind.textContent = msg.kind;
    cardContent.textContent = msg.content;
    cardView.classList.remove("hidden");
    return;
  }

  if (msg.type === "show_bounding_box") {
    hideAll();
    titleEl.textContent = msg.title;
    latestBoxes = msg.boxes;
    bboxImage.src = msg.image;
    bboxView.classList.remove("hidden");
    return;
  }

  if (msg.type === "show_dimensions") {
    hideAll();
    titleEl.textContent = msg.title;
    dimensionName.textContent = msg.title;
    dimensionMeasurements.textContent = `${msg.width_mm} mm x ${msg.depth_mm} mm${msg.height_mm ? ` x ${msg.height_mm} mm high` : ""}`;
    const calibrated = msg.calibrated_width_mm > 0 && msg.calibrated_height_mm > 0;
    if (calibrated) {
      dimensionObject.style.width = `${msg.width_mm / msg.calibrated_width_mm * window.innerWidth}px`;
      dimensionObject.style.height = `${msg.depth_mm / msg.calibrated_height_mm * window.innerHeight}px`;
      dimensionNote.textContent = "Physical scale uses configured projector width and height. Verify with a ruler before relying on it.";
    } else {
      dimensionObject.style.width = "min(68vw, 680px)";
      dimensionObject.style.height = "min(36vh, 300px)";
      dimensionNote.textContent = "Illustrative scale. Set PROJECTOR_WIDTH_MM and PROJECTOR_HEIGHT_MM for physical size.";
    }
    dimensionObject.style.left = "50%";
    dimensionObject.style.top = "50%";
    dimensionObject.style.transform = "translate(-50%, -50%)";
    dimensionSource.textContent = msg.source;
    dimensionSource.href = msg.source;
    dimensionView.classList.remove("hidden");
  }
});

let dragging = false;
dimensionObject.addEventListener("pointerdown", event => {
  dragging = true;
  dimensionObject.setPointerCapture(event.pointerId);
});
dimensionObject.addEventListener("pointerup", () => { dragging = false; });
dimensionObject.addEventListener("pointermove", event => {
  if (!dragging) return;
  dimensionObject.style.left = `${event.clientX / window.innerWidth * 100}%`;
  dimensionObject.style.top = `${event.clientY / window.innerHeight * 100}%`;
});

window.setInterval(() => {
  statusEl.textContent = socket.isConnected() ? "connected" : "reconnecting...";
}, 1000);
