import { createSocket } from "./ws";

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
    };

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

let latestBoxes: DetectionBox[] = [];

function hideAll() {
  cardView.classList.add("hidden");
  bboxView.classList.add("hidden");
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
  }
});

window.setInterval(() => {
  statusEl.textContent = socket.isConnected() ? "connected" : "reconnecting...";
}, 1000);
