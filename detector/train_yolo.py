"""Train reviewed workshop labels; never silently train on detector guesses."""
import argparse
from pathlib import Path
from ultralytics import YOLO

parser = argparse.ArgumentParser()
parser.add_argument("dataset", type=Path, help="Reviewed YOLO data.yaml with train/val splits and class names")
parser.add_argument("--weights", default="/opt/models/yolo26n.pt")
parser.add_argument("--epochs", type=int, default=100)
parser.add_argument("--device", default="cpu")
parser.add_argument("--project", default="/data/training")
args = parser.parse_args()
if not args.dataset.is_file():
    parser.error("Dataset YAML does not exist")
YOLO(args.weights).train(data=str(args.dataset), epochs=args.epochs, imgsz=640,
    device=args.device, project=args.project, name="workshop-tools")
