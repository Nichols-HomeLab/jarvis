FROM python:3.14-slim@sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 YOLO_CONFIG_DIR=/tmp/yolo
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch==2.14.1 torchvision --index-url https://download.pytorch.org/whl/cpu
COPY detector/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN HF_HUB_OFFLINE=0 python -c "from huggingface_hub import snapshot_download; snapshot_download('IDEA-Research/grounding-dino-tiny', local_dir='/opt/models/grounding-dino-tiny', ignore_patterns=['*.bin']); from ultralytics import YOLO; import os; os.makedirs('/opt/models', exist_ok=True); os.chdir('/opt/models'); YOLO('yolo26n.pt')"
COPY detector/app.py detector/train_yolo.py ./
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
