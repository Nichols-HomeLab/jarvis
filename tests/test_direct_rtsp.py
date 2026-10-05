import asyncio
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from backend.config import CameraConfig
from backend.vision.camera_manager import CameraManager
from backend.vision.streaming import CameraStreams


def test_direct_rtsp_snapshot_and_live_frames_use_exact_url_and_reap_processes(tmp_path):
    import sys
    jpeg = BytesIO()
    Image.new("RGB", (640, 480), "gray").save(jpeg, "JPEG")
    fixture = tmp_path / "frame.jpg"
    fixture.write_bytes(jpeg.getvalue())
    url = "rtsp://user:password@camera:554/live?channel=1&subtype=0"
    calls, processes = [], []
    spawn = asyncio.create_subprocess_exec

    async def fake_ffmpeg(*args, **kwargs):
        calls.append(args)
        assert args[args.index("-i") + 1] == url
        assert args[args.index("-rtsp_transport") + 1] == "tcp"
        process = await spawn(sys.executable, "-u", "-c",
            "import sys,time,pathlib\nframe=pathlib.Path(sys.argv[1]).read_bytes()\nwhile True:\n sys.stdout.buffer.write(frame);sys.stdout.buffer.flush();time.sleep(.02)",
            str(fixture), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        processes.append(process)
        return process

    async def run():
        # No Frigate client or base/restream URL exists in this flow.
        streams = CameraStreams(None)
        config = CameraConfig("bench", "Workshop", rtsp_url=url)
        manager = CameraManager([config], tmp_path, None, streams=streams)
        snapshot = await manager.capture_snapshot("bench")
        with Image.open(snapshot.snapshot_path) as image:
            assert image.size == (640, 480)
        assert "-frames:v" in calls[0]
        async with streams.open("bench", config.rtsp_url) as (frames, content_type):
            assert content_type.startswith("multipart/x-mixed-replace")
            assert jpeg.getvalue() in await anext(frames)
        assert streams.active == 0
        assert all(p.returncode is not None for p in processes)

    with patch("asyncio.create_subprocess_exec", fake_ffmpeg):
        asyncio.run(run())


def test_direct_rtsp_failed_source_returns_generic_error_and_releases_slot():
    import sys
    spawn = asyncio.create_subprocess_exec
    processes = []

    async def failed_ffmpeg(*args, **kwargs):
        process = await spawn(sys.executable, "-c", "pass", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        processes.append(process)
        return process

    async def run():
        streams = CameraStreams(None)
        with pytest.raises(RuntimeError, match="Camera did not return a video frame") as error:
            async with streams.open("bench", "rtsp://user:password@camera/stream"):
                pass
        assert "password" not in str(error.value)
        assert streams.active == 0
        assert processes[0].returncode is not None

    with patch("asyncio.create_subprocess_exec", failed_ffmpeg):
        asyncio.run(run())
