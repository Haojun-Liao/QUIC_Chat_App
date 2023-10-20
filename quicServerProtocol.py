import asyncio
from typing import Dict, Optional, Union


from aioquic.asyncio import QuicConnectionProtocol
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h0.connection import H0_ALPN
from aioquic.quic.events import DatagramFrameReceived, ProtocolNegotiated, QuicEvent, ConnectionTerminated
from aioquic.h3.events import (
    DatagramReceived,
    DataReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)

from Http3 import HttpRequestHandler
from WebTransport import WebTransportHandler

from fastapiServer import application


Handler = Union[HttpRequestHandler, WebTransportHandler]
app = application


class HttpQuicServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._http: Optional[H3Connection] = None
        self._handlers: Dict[int, Handler] = {}

    def http_event_received(self, event: H3Event) -> None:
        if isinstance(event, HeadersReceived) and event.stream_id not in self._handlers:
            authority = None
            headers = []
            http_version = "3"
            raw_path = b""
            method = ""
            protocol = None
            for header, value in event.headers:
                if header == b':authority':
                    authority = value
                    headers.append((b'host', value))
                elif header == b':method':
                    method = value.decode()
                elif header == b":path":
                    raw_path = value
                elif header == b":protocol":
                    protocol = value.decode()
                elif header and not header.startswith(b":"):
                    headers.append((header, value))

            if b"?" in raw_path:
                path_bytes, query_string = raw_path.split(b"?", maxsplit=1)
            else:
                path_bytes, query_string = raw_path, b""
            path = path_bytes.decode()

            client_addr = self._http._quic._network_paths[0].addr
            client = (client_addr[0], client_addr[1])

            handler: Handler
            scope: Dict

            if method == "CONNECT" and protocol == "webtransport":
                scope = {
                    "client": client,
                    "headers": headers,
                    "http_version": http_version,
                    "method": method,
                    "path": path,
                    "query_string": query_string,
                    "raw_path": raw_path,
                    "root_path": "",
                    "scheme": "https",
                    "type": "webtransport",
                }
                handler = WebTransportHandler(
                    connection=self._http,
                    scope=scope,
                    stream_id=event.stream_id,
                    transmit=self.transmit,
                )

            else:
                extensions: Dict[str, Dict] = {}
                if isinstance(self._http, H3Connection):
                    extensions['http.response.push'] = {}
                scope = {
                        'client': client,
                        "headers": headers,
                        "http_version": http_version,
                        'method': method,
                        "path": path,
                        "query_string": query_string,
                        "raw_path": raw_path,
                        "root_path": "",
                        "scheme": "https",
                        "type": "http",
                }
                handler = HttpRequestHandler(
                    authority=authority,
                    connection=self._http,
                    protocol=self,
                    scope=scope,
                    stream_ended=event.stream_ended,
                    stream_id=event.stream_id,
                    transmit=self.transmit,
                )
            self._handlers[event.stream_id] = handler
            asyncio.ensure_future(handler.run_asgi(app))
        elif isinstance(event, (DataReceived, HeadersReceived)) and event.stream_id in self._handlers:
            handler = self._handlers[event.stream_id]
            handler.http_event_receive(event)
        elif isinstance(event, DatagramReceived):
            handler = self._handlers[event.flow_id]
            handler.http_event_receive(event)
        elif isinstance(event, WebTransportStreamDataReceived):
            handler = self._handlers[event.session_id]
            handler.http_event_receive(event)
        # else:
        print(event)

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, ProtocolNegotiated):
            if event.alpn_protocol in H3_ALPN:
                self._http = H3Connection(self._quic, enable_webtransport=True)
                print("connected")
            elif event.alpn_protocol in H0_ALPN:
                print("not h3 protocol")
        elif isinstance(event, DatagramFrameReceived):
            if event.data == b'quack':
                print("quack")
                self._quic.send_datagram_frame(b'quack-ack')
        elif isinstance(event, ConnectionTerminated):
            print("Connection terminated")
        if self._http is not None:
            for http_event in self._http.handle_event(event):
                self.http_event_received(http_event)

