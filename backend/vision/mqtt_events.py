from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable

import paho.mqtt.client as mqtt

from backend.config import Settings


log = logging.getLogger(__name__)


def completed_event_id(payload: bytes) -> str | None:
    try:
        message = json.loads(payload)
        event = message.get("after", {})
        event_id = event.get("id", "")
        if message.get("type") == "end" and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", event_id):
            return event_id
    except (ValueError, AttributeError, TypeError):
        pass
    return None


class FrigateMQTTSubscriber:
    def __init__(self, settings: Settings, on_event: Callable[[str], Awaitable[object]]):
        self.settings = settings
        self.on_event = on_event
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if settings.mqtt_user:
            self.client.username_pw_set(settings.mqtt_user, settings.mqtt_password)
        self.loop: asyncio.AbstractEventLoop | None = None

        def on_connect(client, _userdata, _flags, reason_code, _properties):
            if reason_code == 0:
                client.subscribe(f"{settings.mqtt_topic_prefix}/events")
            else:
                log.warning("MQTT connection failed: %s", reason_code)

        def on_message(_client, _userdata, message):
            event_id = completed_event_id(message.payload)
            if event_id and self.loop:
                task = asyncio.run_coroutine_threadsafe(self.on_event(event_id), self.loop)
                task.add_done_callback(lambda future: log.error("Frigate event failed: %s", future.exception()) if future.exception() else None)

        self.client.on_connect = on_connect
        self.client.on_message = on_message

    def start(self) -> None:
        if not self.settings.mqtt_host:
            return
        self.loop = asyncio.get_running_loop()
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port)
        self.client.loop_start()

    def stop(self) -> None:
        if self.settings.mqtt_host:
            self.client.disconnect()
            self.client.loop_stop()
