import asyncio
import time
from collections import deque
from typing import Dict, Callable, Deque
from email.utils import formatdate

from aioquic.h3.connection import H3Connection
from aioquic.h3.events import (
    DatagramReceived,
    DataReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)

SERVERNAME = 'QUICChat'


class WebTransportHandler:
    def __init__(self, *, connection: H3Connection, scope: Dict, stream_id: int, transmit: Callable[[], None]) -> None:
        self.accepted = False
        self.closed = False
        self.connection = connection
        self.http_event_queue: Deque[DataReceived] = deque()
        self.queue: asyncio.Queue[Dict] = asyncio.Queue()
        self.scope = scope
        self.stream_id = stream_id
        self.transmit = transmit

    async def receive(self) -> Dict:
        return await self.queue.get()

    async def send(self, message: Dict) -> None:
        data = b""
        end_stream = False

        if message["type"] == "webtransport.accept":
            self.accepted = True

            headers = [
                (b":status", b"200"),
                (b"server", SERVERNAME.encode()),
                (b"date", formatdate(time.time(), usegmt=True).encode()),
                (b"sec-webtransport-http3-draft", b"draft02"),
            ]
            self.connection.send_headers(stream_id=self.stream_id, headers=headers)

            while self.http_event_queue:
                self.http_event_receive(self.http_event_queue.popleft())
        elif message["type"] == "webtransport.close":
            if not self.accepted:
                self.connection.send_headers(
                    stream_id=self.stream_id, headers=[(b":status", b"403")]
                )
            end_stream = True
        elif message["type"] == "webtransport.datagram.send":
            self.connection.send_datagram(flow_id=self.stream_id, data=message["data"])
        elif message["type"] == "webtransport.stream.send":
            self.connection._quic.send_stream_data(
                stream_id=message["stream"], data=message["data"]
            )

        if data or end_stream:
            self.connection.send_data(
                stream_id=self.stream_id, data=data, end_stream=end_stream
            )
        if end_stream:
            self.closed = True

        self.transmit()

    def http_event_receive(self, event: H3Event) -> None:
        if not self.closed:
            if self.accepted:
                if isinstance(event, DatagramReceived):
                    self.queue.put_nowait(
                        {
                            "data": event.data,
                            "type": "webtransport.datagram.receive",
                        }
                    )
                elif isinstance(event, WebTransportStreamDataReceived):
                    self.queue.put_nowait(
                        {
                            "data": event.data,
                            "stream": event.stream_id,
                            "stream_ended": event.stream_ended,
                            "type": "webtransport.stream.receive",
                        }
                    )
                elif isinstance(event, DataReceived) and self.stream_id == event.stream_id:
                    if event.stream_ended:
                        self.queue.put_nowait(
                            {
                                "data": event.data,
                                "stream": event.stream_id,
                                "type": "webtransport.close",
                            }
                        )
            else:
                self.http_event_queue.append(event)

    async def run_asgi(self, app: Callable) -> None:
        self.queue.put_nowait({"type": "webtransport.connect"})

        try:
            await app(self.scope, self.receive, self.send)
        finally:
            if not self.closed:
                await self.send({"type": "webtransport.close"})