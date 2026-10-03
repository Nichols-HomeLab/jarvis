type Detection = { label: string; description: string; box: number[]; confidence: number };
type Scan = { image_width: number; image_height: number; analyzed_at: string; detections: Detection[] };

export function cameraView(cameraName: string, card: HTMLElement) {
  const toggle = document.createElement("button");
  toggle.textContent = "View live camera";
  const wrapper = document.createElement("div");
  wrapper.className = "live-camera hidden";
  const frame = document.createElement("div");
  frame.className = "live-frame";
  const image = document.createElement("img");
  image.alt = `${cameraName} live camera`;
  const boxes = document.createElement("div");
  boxes.className = "live-boxes";
  frame.append(image, boxes);
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  wrapper.append(frame, status);
  card.append(toggle, wrapper);
  let running = false;
  let generation = 0;
  let scan: Scan | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let abort: AbortController | null = null;

  const draw = () => {
    boxes.replaceChildren();
    if (!scan || !running || Date.now() - Date.parse(scan.analyzed_at) > 45000) return;
    for (const item of scan.detections) {
      const [x1, y1, x2, y2] = item.box;
      if (!scan.image_width || !scan.image_height) continue;
      const box = document.createElement("div");
      box.className = "scan-box";
      box.style.cssText = `left:${100*x1/scan.image_width}%;top:${100*y1/scan.image_height}%;width:${100*(x2-x1)/scan.image_width}%;height:${100*(y2-y1)/scan.image_height}%`;
      const label = document.createElement("span");
      label.textContent = `${item.label} ${Math.round(item.confidence*100)}%`;
      box.title = item.description || item.label;
      box.append(label);
      boxes.append(box);
    }
  };
  const refresh = async (current: number) => {
    if (!running || generation !== current) return;
    abort = new AbortController();
    status.textContent = "Live camera · detecting objects…";
    try {
      const response = await fetch(`/api/v2/scan/${encodeURIComponent(cameraName)}`, { method: "POST", signal: abort.signal });
      if (!response.ok) throw new Error(`Detection failed (${response.status})`);
      const result: Scan = await response.json();
      if (generation !== current) return;
      scan = result;
      status.textContent = `Live camera · ${scan.detections.length} detections · scan ${new Date(scan.analyzed_at).toLocaleTimeString()}`;
      draw();
    } catch (error) {
      if (generation !== current) return;
      status.textContent = `Live camera · ${String(error)}`;
    }
    if (running && generation === current) timer = setTimeout(() => refresh(current), 15000);
  };
  const stop = () => {
    running = false;
    generation++;
    abort?.abort();
    clearTimeout(timer);
    image.removeAttribute("src");
    boxes.replaceChildren();
    wrapper.classList.add("hidden");
    toggle.textContent = "View live camera";
  };
  image.addEventListener("error", () => { status.textContent = "Camera stream unavailable. Close and reopen to retry."; });
  toggle.addEventListener("click", () => {
    if (running) return stop();
    running = true;
    generation++;
    wrapper.classList.remove("hidden");
    toggle.textContent = "Close live camera";
    image.src = `/api/v2/cameras/${encodeURIComponent(cameraName)}/stream`;
    void refresh(generation);
  });
  const expiry = setInterval(draw, 5000);
  return () => { stop(); clearInterval(expiry); };
}
