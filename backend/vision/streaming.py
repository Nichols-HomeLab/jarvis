from __future__ import annotations

import asyncio
import anyio
from contextlib import asynccontextmanager
from urllib.parse import quote, urlsplit

import httpx


class CameraStreams:
    """Direct RTSP snapshots and browser MJPEG, with legacy Frigate support."""
    def __init__(self, frigate, rtsp_url: str = "", transport=None):
        self.frigate, self.rtsp_url, self.transport = frigate, rtsp_url, transport
        self.active = 0

    @asynccontextmanager
    async def open(self, camera: str, rtsp_url: str = ""):
        if self.active >= 4:
            raise RuntimeError("Four camera streams are already open")
        self.active += 1
        try:
            if rtsp_url or self.rtsp_url:
                url = rtsp_url or f"{self.rtsp_url}/{quote(camera, safe='')}"
                async with self._rtsp(url) as stream:
                    yield stream, "multipart/x-mixed-replace; boundary=frame"
            else:
                async with httpx.AsyncClient(timeout=httpx.Timeout(15, read=None), transport=self.transport) as client:
                    async with client.stream("GET", f"{self.frigate.base_url}/api/{quote(camera, safe='')}?fps=3&h=720", headers=await self.frigate._headers()) as response:
                        response.raise_for_status()
                        content_type = response.headers.get("content-type", "")
                        if not content_type.startswith("multipart/x-mixed-replace"):
                            raise RuntimeError("Frigate did not return an MJPEG stream")
                        yield response.aiter_bytes(), content_type
        finally:
            self.active -= 1

    async def snapshot(self, rtsp_url: str) -> bytes:
        async with self._rtsp(rtsp_url, snapshot=True) as frames:
            frame = await anext(frames)
            return frame.split(b"\r\n\r\n", 1)[1][:-2]

    @asynccontextmanager
    async def _rtsp(self, rtsp_url: str, snapshot: bool = False):
        output = ["-frames:v", "1"] if snapshot else ["-vf", "fps=3,scale=-2:720"]
        url = urlsplit(rtsp_url)
        tls = ["-tls_verify", "1", "-verifyhost", url.hostname] if url.scheme == "rtsps" else []
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp",
            *tls, "-i", rtsp_url, "-an", "-threads", "2",
            *output, "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            frames = self._frames(process.stdout)
            try:
                first = await asyncio.wait_for(anext(frames), 20)
            except (asyncio.TimeoutError, StopAsyncIteration) as exc:
                raise RuntimeError("Camera did not return a video frame; check the URL, credentials, and connection") from exc
            async def body():
                yield first
                async for frame in frames:
                    yield frame
            yield body()
        finally:
            with anyio.CancelScope(shield=True):
                if process.returncode is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        # Drain stdout as we reap; a full pipe can block wait().
                        await asyncio.wait_for(process.communicate(), 5)
                    except asyncio.TimeoutError:
                        if process.returncode is None:
                            process.kill()
                        await process.communicate()

    @staticmethod
    async def _frames(reader):
        buffer = bytearray()
        while chunk := await reader.read(65536):
            buffer.extend(chunk)
            if len(buffer) > 10 * 1024 * 1024:
                raise RuntimeError("Invalid camera frame size")
            while True:
                start = buffer.find(b"\xff\xd8")
                end = buffer.find(b"\xff\xd9", max(0, start + 2))
                if start < 0 or end < 0:
                    break
                frame = bytes(buffer[start:end + 2])
                del buffer[:end + 2]
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
