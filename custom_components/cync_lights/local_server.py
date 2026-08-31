"""Local TLS server that impersonates the Cync cloud (cm.gelighting.com).

This is the "local control" path: with DNS pointing cm.gelighting.com at the
Home Assistant host, physical Cync devices connect here instead of to Cync's
cloud, and we speak their protocol directly — so control keeps working with no
internet connection.

Protocol note (this is what the earlier add-on got wrong and caused the
~15-second disconnect): the devices act as TCP *clients*, and this server must
respond exactly the way Cync's cloud does. The response header byte is
    (message_type << 4) | (is_response << 3) | version
with **version = 3**. The old implementation replied with version = 0
(0x18 login-ack, 0x28 handshake-ack, 0xAB, 0xD8), which are malformed; a device
that logs in, receives a bad ack, and never gets a correct PROBE reply hangs and
drops at its firmware timeout (~15s). Correct response bytes are 0x1b (login),
0x2b (handshake), 0xab (probe), 0xdb (ping). It also misread 0xA3 as a "legacy
connect" when 0xA3 is actually a PROBE *request* the device sends and expects a
PROBE response (0xab) for.

All packet building for outgoing commands reuses the vendored pycync
packet_builder so the byte formats stay consistent with the cloud client.
"""
from __future__ import annotations

import asyncio
import logging
import ssl
import struct
from typing import Callable, Optional

from .pycync.tcp import packet_builder

_LOGGER = logging.getLogger(__name__)

PROTOCOL_VERSION = 3


def _response_header(message_type: int, payload_len: int) -> bytes:
    """Build a 5-byte response header the way Cync's cloud does (version=3)."""
    info_byte = (message_type << 4) | (1 << 3) | PROTOCOL_VERSION
    return bytes([info_byte]) + struct.pack(">I", payload_len)


# Message type numbers (mirror pycync.tcp.packet.MessageType)
T_LOGIN = 1
T_HANDSHAKE = 2
T_SYNC = 4
T_PIPE = 7
T_PIPE_SYNC = 8
T_PROBE = 10
T_PING = 13
T_DISCONNECT = 14

# Pre-built fixed responses (all version=3)
LOGIN_ACK = _response_header(T_LOGIN, 0)          # 0x1b 00 00 00 00
HANDSHAKE_ACK = _response_header(T_HANDSHAKE, 0)  # 0x2b 00 00 00 00
PING_ACK = _response_header(T_PING, 0)            # 0xdb 00 00 00 00
SYNC_ACK = _response_header(T_SYNC, 0)            # 0x4b 00 00 00 00

# Cipher list Cync device firmware negotiates with (older suites required).
_CIPHERS = ":".join(
    [
        "ECDHE-RSA-AES256-GCM-SHA384", "ECDHE-RSA-AES128-GCM-SHA256",
        "ECDHE-RSA-AES256-SHA384", "ECDHE-RSA-AES128-SHA256",
        "ECDHE-RSA-AES256-SHA", "ECDHE-RSA-AES128-SHA",
        "AES256-GCM-SHA384", "AES128-GCM-SHA256",
        "AES256-SHA256", "AES128-SHA256",
        "AES256-SHA", "AES128-SHA", "DES-CBC3-SHA",
    ]
)


class DeviceConn:
    """One connected physical device (a WiFi device / mesh hub)."""

    def __init__(self, writer: asyncio.StreamWriter, device_id: int, peer: str):
        self.writer = writer
        self.device_id = device_id
        self.peer = peer
        self.logged_in = False

    def send(self, data: bytes) -> None:
        if not self.writer.is_closing():
            self.writer.write(data)

    def close(self) -> None:
        try:
            if not self.writer.is_closing():
                self.writer.close()
        except Exception:  # noqa: BLE001
            pass


class CyncLocalServer:
    """TLS server that physical Cync devices connect to for local control."""

    def __init__(
        self,
        cert_file: str,
        key_file: str,
        port: int = 23779,
        state_callback: Optional[Callable] = None,
    ) -> None:
        self.cert_file = cert_file
        self.key_file = key_file
        self.port = port
        self._state_cb = state_callback
        self.connections: dict[int, DeviceConn] = {}
        self._server: Optional[asyncio.AbstractServer] = None

    @property
    def connected_device_ids(self) -> list[int]:
        return list(self.connections.keys())

    async def start(self) -> None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert_file, self.key_file)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers(_CIPHERS)
        except ssl.SSLError:
            pass
        # Cync firmware negotiates old TLS; allow it.
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1
        except (ValueError, AttributeError):
            pass

        self._server = await asyncio.start_server(
            self._handle, "0.0.0.0", self.port, ssl=ctx
        )
        _LOGGER.info(
            "Local Cync server listening on :%d (TLS) - waiting for devices",
            self.port,
        )

    async def stop(self) -> None:
        for conn in list(self.connections.values()):
            conn.close()
        self.connections.clear()
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self._server = None

    # -- Connection handler --------------------------------------------------

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = str(writer.get_extra_info("peername"))
        device_id: Optional[int] = None
        conn: Optional[DeviceConn] = None
        _LOGGER.info("Incoming device connection from %s", peer)

        try:
            while True:
                hdr = await asyncio.wait_for(reader.readexactly(5), timeout=90)
                info_byte = hdr[0]
                msg_type = (info_byte & 0xF0) >> 4
                is_response = bool((info_byte & 0x08) >> 3)
                length = struct.unpack(">I", hdr[1:5])[0]

                payload = b""
                if length:
                    payload = await asyncio.wait_for(
                        reader.readexactly(length), timeout=10
                    )

                if msg_type == T_HANDSHAKE and not is_response:
                    if len(payload) >= 5:
                        device_id = struct.unpack(">I", payload[1:5])[0]
                        _LOGGER.info("Device handshake: id=%d (%s)", device_id, peer)
                    conn = DeviceConn(writer, device_id or 0, peer)
                    if device_id:
                        self.connections[device_id] = conn
                    writer.write(HANDSHAKE_ACK)
                    await writer.drain()

                elif msg_type == T_LOGIN and not is_response:
                    if len(payload) >= 5:
                        device_id = struct.unpack(">I", payload[1:5])[0]
                    if conn is None:
                        conn = DeviceConn(writer, device_id or 0, peer)
                    if device_id:
                        self.connections[device_id] = conn
                    conn.logged_in = True
                    writer.write(LOGIN_ACK)
                    await writer.drain()
                    _LOGGER.info("Device logged in: id=%d (%s)", device_id or 0, peer)
                    # Ask the device to report full mesh state now that it's up.
                    if device_id:
                        await asyncio.sleep(0.3)
                        self.query_state(device_id)

                elif msg_type == T_PROBE and not is_response:
                    # Device probing whether the "cloud" knows it. Echo a PROBE
                    # response (version=3) so it considers itself connected.
                    if len(payload) >= 4:
                        _pid = payload[0:4]
                    else:
                        _pid = struct.pack(">I", device_id or 0)
                    resp_payload = _pid + bytes([0x00])
                    writer.write(_response_header(T_PROBE, len(resp_payload)) + resp_payload)
                    await writer.drain()

                elif msg_type in (T_SYNC, T_PIPE_SYNC) and not is_response:
                    self._parse_sync(payload, device_id)
                    writer.write(SYNC_ACK)
                    await writer.drain()

                elif msg_type == T_PIPE:
                    # PIPE can be a device status-page reply (response from the
                    # device) or an async status push. Parse either.
                    self._parse_pipe(payload, device_id)

                elif msg_type == T_PING and not is_response:
                    writer.write(PING_ACK)
                    await writer.drain()

                elif msg_type == T_DISCONNECT:
                    _LOGGER.info("Device %d requested disconnect", device_id or 0)
                    break

                # Responses to our own requests (is_response=True) need no reply.

        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionResetError):
            _LOGGER.info("Device %d (%s) disconnected", device_id or 0, peer)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Device handler error [%s]: %s", peer, err)
        finally:
            if device_id and self.connections.get(device_id) is conn:
                del self.connections[device_id]
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    # -- State parsers -------------------------------------------------------

    def _parse_sync(self, payload: bytes, hub_id: Optional[int]) -> None:
        """SYNC broadcast — state of BT mesh devices behind a hub."""
        if len(payload) < 12:
            return
        body = payload[4:]
        if body[:3] != bytes([0x01, 0x01, 0x06]):
            return
        body = body[3:]
        while len(body) > 3:
            try:
                rec_len = struct.unpack(">H", body[1:3])[0]
                rec = body[3 : 3 + rec_len]
                body = body[3 + rec_len :]
                if len(rec) < 7:
                    continue
                mesh_id = rec[0]
                is_on = bool(rec[1])
                brightness = rec[2]
                color_temp = rec[3]
                r, g, b = rec[4], rec[5], rec[6]
                if self._state_cb:
                    self._state_cb(mesh_id, is_on, brightness, color_temp, r, g, b, hub_id, True)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("SYNC parse error: %s", err)
                break

    def _parse_pipe(self, payload: bytes, hub_id: Optional[int]) -> None:
        """PIPE device-status-pages reply (result of query_state)."""
        if len(payload) < 8:
            return
        try:
            start = payload.find(b"\x7e")
            if start < 0:
                return
            end = payload.find(b"\x7e", start + 1)
            if end < 0:
                return
            inner = payload[start + 1 : end].replace(b"\x7d\x5e", b"\x7e")
            if len(inner) < 8:
                return
            cmd = inner[5]
            if cmd != 0x52:  # QUERY_DEVICE_STATUS_PAGES
                return
            data_len = struct.unpack("<H", inner[6:8])[0]
            data = inner[8 : 8 + data_len]
            if len(data) < 6:
                return
            device_count = struct.unpack("<H", data[4:6])[0]
            records = data[6:]
            for _ in range(device_count):
                if len(records) < 24:
                    break
                rec = records[:24]
                records = records[24:]
                mesh_id = struct.unpack("<H", rec[0:2])[0]
                is_online = bool(rec[3])
                is_on = bool(rec[8])
                brightness = rec[12]
                color_mode = rec[16]
                r, g, b = rec[20], rec[21], rec[22]
                if self._state_cb:
                    self._state_cb(mesh_id, is_on, brightness, color_mode, r, g, b, hub_id, is_online)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("PIPE parse error: %s", err)

    # -- Outgoing commands (reuse pycync packet builders) --------------------

    def query_state(self, hub_device_id: int) -> None:
        conn = self.connections.get(hub_device_id)
        if not conn:
            return
        try:
            conn.send(packet_builder.build_state_query_request_packet(hub_device_id))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("query_state error: %s", err)

    def query_all(self) -> None:
        for dev_id in list(self.connections.keys()):
            self.query_state(dev_id)

    def set_power(self, hub_device_id: int, mesh_id: int, is_on: bool) -> None:
        conn = self.connections.get(hub_device_id)
        if not conn:
            _LOGGER.warning("No local connection for hub %d", hub_device_id)
            return
        try:
            conn.send(
                packet_builder.build_power_state_request_packet(
                    hub_device_id, mesh_id, is_on
                )
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("set_power error: %s", err)

    def set_brightness(self, hub_device_id: int, mesh_id: int, brightness: int) -> None:
        conn = self.connections.get(hub_device_id)
        if not conn:
            return
        try:
            conn.send(
                packet_builder.build_brightness_request_packet(
                    hub_device_id, mesh_id, brightness
                )
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("set_brightness error: %s", err)

    def set_color_temp(self, hub_device_id: int, mesh_id: int, color_temp: int) -> None:
        conn = self.connections.get(hub_device_id)
        if not conn:
            return
        try:
            conn.send(
                packet_builder.build_color_temp_request_packet(
                    hub_device_id, mesh_id, color_temp
                )
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("set_color_temp error: %s", err)

    def set_rgb(self, hub_device_id: int, mesh_id: int, r: int, g: int, b: int) -> None:
        conn = self.connections.get(hub_device_id)
        if not conn:
            return
        try:
            conn.send(
                packet_builder.build_rgb_request_packet(
                    hub_device_id, mesh_id, (r, g, b)
                )
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("set_rgb error: %s", err)
