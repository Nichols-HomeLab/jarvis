import { requireSession } from "./auth";

await requireSession();

type CameraInfo = {
  name: string;
  zone_name: string;
  enabled: boolean;
};

type SearchResult = {
  object_name: string;
  object_category: string;
  description: string;
  camera_name: string;
  zone_name: string;
  action: string;
  confidence: number;
  last_seen_at: string;
  snapshot_path?: string;
  bbox?: number[];
};

type ScanResult = {
  snapshot_path: string;
  detections: Array<{ label: string; description: string; box: number[]; confidence: number }>;
};

const cameraList = document.getElementById("camera-list") as HTMLDivElement;
const refreshCamerasButton = document.getElementById("refresh-cameras") as HTMLButtonElement;
const commandForm = document.getElementById("command-form") as HTMLFormElement;
const commandInput = document.getElementById("command-input") as HTMLInputElement;
const commandOutput = document.getElementById("command-output") as HTMLPreElement;
const searchForm = document.getElementById("search-form") as HTMLFormElement;
const searchInput = document.getElementById("search-input") as HTMLInputElement;
const searchOutput = document.getElementById("search-output") as HTMLPreElement;
const recentMemory = document.getElementById("recent-memory") as HTMLDivElement;
const preview = document.getElementById("scan-preview") as HTMLDivElement;
const scanImage = document.getElementById("scan-image") as HTMLImageElement;
const scanBoxes = document.getElementById("scan-boxes") as HTMLDivElement;
let latestScan: ScanResult | null = null;

function renderScanBoxes() {
  scanBoxes.innerHTML = "";
  if (!latestScan || !scanImage.naturalWidth || !scanImage.naturalHeight) return;
  const xScale = scanImage.clientWidth / scanImage.naturalWidth;
  const yScale = scanImage.clientHeight / scanImage.naturalHeight;
  latestScan.detections.forEach(item => {
    const [x1, y1, x2, y2] = item.box;
    const box = document.createElement("div");
    box.className = "scan-box";
    box.style.left = `${x1 * xScale}px`;
    box.style.top = `${y1 * yScale}px`;
    box.style.width = `${(x2 - x1) * xScale}px`;
    box.style.height = `${(y2 - y1) * yScale}px`;
    const label = document.createElement("span");
    label.textContent = `${item.description || item.label} ${Math.round(item.confidence * 100)}%`;
    box.appendChild(label);
    scanBoxes.appendChild(box);
  });
}
scanImage.addEventListener("load", renderScanBoxes);
window.addEventListener("resize", renderScanBoxes);

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function renderJson(target: HTMLElement, value: unknown) {
  target.textContent = JSON.stringify(value, null, 2);
}

function renderRecentMemory(items: SearchResult[]) {
  recentMemory.innerHTML = "";
  if (!items.length) {
    recentMemory.textContent = "No memory records yet.";
    return;
  }

  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "memory-card";
    for (const [className, value] of [
      ["memory-title", item.object_name],
      ["memory-meta", `${item.camera_name} / ${item.zone_name}`],
      ["memory-body", item.description || item.object_category],
      ["memory-time", new Date(item.last_seen_at).toLocaleString()],
    ]) {
      const field = document.createElement("div");
      field.className = className;
      field.textContent = value;
      card.appendChild(field);
    }
    recentMemory.appendChild(card);
  });
}

async function loadCameras() {
  const cameras = await request<CameraInfo[]>("/api/v2/cameras");
  cameraList.innerHTML = "";
  cameras.forEach((camera) => {
    const card = document.createElement("article");
    card.className = "camera-card";
    const button = document.createElement("button");
    button.textContent = `Scan ${camera.name}`;
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "Scanning...";
      try {
        const result = await request<ScanResult>(`/api/v2/scan/${camera.name}`, { method: "POST" });
        renderJson(commandOutput, result);
        latestScan = result;
        preview.classList.remove("hidden");
        scanImage.src = result.snapshot_path;
        await loadRecentMemory();
      } catch (error) {
        renderJson(commandOutput, { error: String(error) });
      } finally {
        button.disabled = false;
        button.textContent = `Scan ${camera.name}`;
      }
    });

    const name = document.createElement("div");
    name.className = "camera-name";
    name.textContent = camera.name;
    const zone = document.createElement("div");
    zone.className = "camera-zone";
    zone.textContent = camera.zone_name;
    card.append(name, zone);
    card.appendChild(button);
    cameraList.appendChild(card);
  });
}

async function loadRecentMemory() {
  const items = await request<SearchResult[]>("/api/v2/tool-memory/recent");
  renderRecentMemory(items);
}

refreshCamerasButton.addEventListener("click", () => {
  loadCameras().catch((error) => renderJson(commandOutput, { error: String(error) }));
});

commandForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = commandInput.value.trim();
  if (!text) return;
  try {
    const response = await request("/api/v2/assistant/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, project_result: true }),
    });
    renderJson(commandOutput, response);
    await loadRecentMemory();
  } catch (error) {
    renderJson(commandOutput, { error: String(error) });
  }
});

searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const q = searchInput.value.trim();
  if (!q) return;
  try {
    const result = await request<SearchResult>(`/api/v2/tool-memory/search?q=${encodeURIComponent(q)}`);
    renderJson(searchOutput, result);
  } catch (error) {
    renderJson(searchOutput, { error: String(error) });
  }
});

loadCameras().catch((error) => renderJson(commandOutput, { error: String(error) }));
loadRecentMemory().catch((error) => renderJson(commandOutput, { error: String(error) }));
