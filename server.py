import asyncio
import importlib
import socket
import time
import ssl
import logging
from os import getpid
from typing import Dict, Optional, Union, Callable, cast
from email.utils import formatdate

from aioquic.asyncio import QuicConnectionProtocol, serve
from aioquic.asyncio.server import QuicServer
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import logger as quic_connection_logger
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h0.connection import H0_ALPN, H0Connection
from aioquic.h3.exceptions import NoAvailablePushIDError
from aioquic.quic.events import DatagramFrameReceived, ProtocolNegotiated, QuicEvent, ConnectionTerminated
from aioquic.h3.events import (
    DatagramReceived,
    DataReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)

from Utils import SessionTicketStore
from quicServerProtocol import HttpQuicServerProtocol


async def run_server(config, binding):
    config.verify_mode = ssl.CERT_NONE
    session = SessionTicketStore()
    loop = asyncio.get_event_loop()

    a, protocol = await loop.create_datagram_endpoint(
        lambda: QuicServer(
            configuration=config,
            create_protocol=HttpQuicServerProtocol,
            retry=False,
            stream_handler=None,
        ),
        local_addr=binding,
    )


async def main():
    configuration = QuicConfiguration(
        alpn_protocols=H3_ALPN,
        is_client=False,
        max_datagram_frame_size=65536,
        idle_timeout=600
    )

    configuration.load_cert_chain('server.pem', 'serverKey.pem')
    binding = ("127.0.0.1", 443)
    try:
        await run_server(configuration, binding)
        print("starting")
        await asyncio.Future()
        print("End")
    except KeyboardInterrupt:
        print("Exiting")
        pass


if __name__ == '__main__':
    quic_connection_logger.setLevel(logging.WARNING)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
