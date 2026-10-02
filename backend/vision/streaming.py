from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from urllib.parse import quote

import httpx


class CameraStreams:
    """Authenticated browser MJPEG from a configured Frigate RTSP restream."""
    def __init__(self, frigate, rtsp_url: str = "", transport=None):
        self.frigate, self.rtsp_url, self.transport = frigate, rtsp_url, transport
        self.active = 0

    @asynccontextmanager
    async def open(self, camera: str):
        if self.active >= 4:
            raise RuntimeError("Four camera streams are already open")
        self.active += 1
        try:
            if self.rtsp_url:
                async with self._rtsp(camera) as stream:
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

    @asynccontextmanager
    async def _rtsp(self, camera):
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp",
            "-i", f"{self.rtsp_url}/{quote(camera, safe='')}", "-an", "-threads", "2",
            "-vf", "fps=3,scale=-2:720", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            frames = self._frames(process.stdout)
            first = await asyncio.wait_for(anext(frames), 20)
            async def body():
                yield first
                async for frame in frames:
                    yield frame
            yield body()
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

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
