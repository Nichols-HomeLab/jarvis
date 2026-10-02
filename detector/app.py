"""Dedicated object localisation. Brand/model assessment belongs to Jarvis's VLM."""
from __future__ import annotations

import asyncio
import os
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image

app = FastAPI()
lock = asyncio.Lock()
models = {}


def load_model(mode):
    if mode not in models:
        if mode == "grounding-dino":
            from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
            path = os.getenv("GROUNDING_DINO_MODEL", "/opt/models/grounding-dino-tiny")
            models[mode] = (AutoProcessor.from_pretrained(path, local_files_only=True), AutoModelForZeroShotObjectDetection.from_pretrained(path, local_files_only=True).eval())
        elif mode == "yolo":
            from ultralytics import YOLO
            path = os.getenv("YOLO_MODEL", "/opt/models/yolo26n.pt")
            if not Path(path).is_file():
                raise ValueError("Configured YOLO weights do not exist")
            models[mode] = YOLO(path)
        else:
            raise ValueError("Unknown detector mode")
    return models[mode]


def detect(image, labels, mode, threshold):
    import torch
    torch.set_num_threads(int(os.getenv("DETECTOR_THREADS", "4")))
    if mode == "grounding-dino":
        processor, model = load_model(mode)
        inputs = processor(images=image, text=" . ".join(labels)+" .", return_tensors="pt")
        with torch.inference_mode():
            outputs = model(**inputs)
        result = processor.post_process_grounded_object_detection(outputs, inputs.input_ids,
            threshold=threshold, text_threshold=threshold, target_sizes=[(image.height, image.width)])[0]
        names = result.get("text_labels", result.get("labels"))
        raw = [(str(label), box.tolist(), float(score)) for label, box, score in zip(names, result["boxes"], result["scores"])]
    else:
        model = load_model(mode)
        result = model.predict(image, conf=threshold, device="cpu", verbose=False)[0]
        raw = [(model.names[int(box.cls.item())], box.xyxy[0].tolist(), float(box.conf.item())) for box in result.boxes]
        # Pretrained COCO weights only cover their declared classes. Never invent tools.
        raw = [r for r in raw if r[0].lower() in labels]
    detections = []
    for label, box, score in raw:
        box = [max(0, min(round(v), image.width if i%2 == 0 else image.height)) for i,v in enumerate(box)]
        if box[2] > box[0] and box[3] > box[1]:
            detections.append({"label": label, "description": label, "box": box, "confidence": score})
    return {"image_width": image.width, "image_height": image.height, "detector": mode, "detections": detections[:50]}


@app.get("/health")
def health():
    return {"status": "ok", "loaded": list(models)}


@app.post("/detect")
async def detection(file: UploadFile = File(...), labels: str = Form(...), mode: str = Form("grounding-dino"), threshold: float = Form(0.25)):
    if mode not in {"grounding-dino", "yolo"} or not 0 < threshold <= 1:
        raise HTTPException(422, "Invalid detector mode or threshold")
    names = list(dict.fromkeys(label.strip().lower() for label in labels.split(".") if label.strip()))
    if not names or len(names) > 100 or any(len(label) > 80 for label in names):
        raise HTTPException(422, "Supply 1–100 object labels")
    data = await file.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise HTTPException(413, "Image too large")
    try:
        with Image.open(BytesIO(data)) as original:
            if original.width * original.height > 20_000_000:
                raise ValueError("Image dimensions too large")
            image = original.convert("RGB")
    except Exception as exc:
        raise HTTPException(422, "Invalid image") from exc
    async with lock:
        return await asyncio.to_thread(detect, image, names, mode, threshold)
