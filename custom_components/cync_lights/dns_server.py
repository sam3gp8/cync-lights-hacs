"""A tiny built-in DNS server for the local-control path.

Its only job is to answer the Cync device hostname(s) with the Home Assistant
host's IP so physical devices connect to the local server instead of Cync's
cloud - without the user running AdGuard/Pi-hole or a router host-override.
Every other query is forwarded to an upstream resolver unchanged, so this can
serve as the DNS server for the devices (or the whole LAN) without breaking
normal name resolution.

Important: this only takes effect for clients that actually send their DNS
queries here. The integration cannot change which resolver a device uses - the
user still points their DHCP/router at the Home Assistant host as the DNS
server (ideally scoped to the Cync devices' subnet/VLAN).

Design notes:
- Binds UDP and TCP on (host_ip, 53). Port 53 is privileged; on Home Assistant
  OS the core process runs as root so this works, but if the bind fails (port in
  use, permission, bridged network) we log and stay down rather than crash.
- Matched names get a minimal A response built by hand. Everything else is
  forwarded verbatim with a fresh short-lived upstream socket per query, so
  there is no transaction-id bookkeeping and no id-collision risk.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import struct
from typing import Iterable, Optional

_LOGGER = logging.getLogger(__name__)

DNS_PORT = 53
_UPSTREAM_TIMEOUT = 4.0
_A_RECORD_TTL = 60
_QTYPE_A = 1


def _parse_question(data: bytes) -> Optional[tuple[str, int, int]]:
    """Return (lowercased name, qtype, offset-after-question) or None.

    Only the first question is parsed, and compression pointers inside the
    question (which real clients don't use) abort the parse.
    """
    if len(data) < 12:
        return None
    qdcount = struct.unpack(">H", data[4:6])[0]
    if qdcount < 1:
        return None

    labels: list[str] = []
    pos = 12
    try:
        while True:
            length = data[pos]
            if length == 0:
                pos += 1
                break
            if length & 0xC0:  # compression pointer - unexpected in a question
                return None
            pos += 1
            labels.append(data[pos:pos + length].decode("ascii", "ignore"))
            pos += length
        qtype = struct.unpack(">H", data[pos:pos + 2])[0]
    except (IndexError, struct.error):
        return None

    return ".".join(labels).lower(), qtype, pos + 4


def _build_a_response(query: bytes, question_end: int, answer_ip: str) -> bytes:
    """Build an A-record response echoing the query's question section."""
    txn_id = query[0:2]
    # QR=1, opcode/AA/TC=0, RD copied from the query; RA=1, RCODE=0.
    byte2 = 0x80 | (query[2] & 0x01)
    byte3 = 0x80
    header = txn_id + bytes([byte2, byte3]) + struct.pack(">HHHH", 1, 1, 0, 0)
    question = query[12:question_end]
    answer = (
        b"\xc0\x0c"                      # pointer to the question's name
        + struct.pack(">HH", _QTYPE_A, 1)  # TYPE=A, CLASS=IN
        + struct.pack(">I", _A_RECORD_TTL)
        + struct.pack(">H", 4)           # RDLENGTH
        + socket.inet_aton(answer_ip)
    )
    return header + question + answer


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: "CyncDnsServer") -> None:
        self._server = server
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr) -> None:
        asyncio.create_task(self._server._handle_udp(data, addr, self.transport))


class CyncDnsServer:
    """Answers the Cync host locally and forwards everything else upstream."""

    def __init__(
        self,
        host_ip: str,
        answer_ip: str,
        hostnames: Iterable[str],
        upstream: str,
        port: int = DNS_PORT,
    ) -> None:
        self._host_ip = host_ip
        self._answer_ip = answer_ip
        self._hostnames = {h.lower() for h in hostnames}
        self._upstream = upstream
        self._port = port
        self._udp_transport: Optional[asyncio.DatagramTransport] = None
        self._tcp_server: Optional[asyncio.AbstractServer] = None

    @property
    def running(self) -> bool:
        return self._udp_transport is not None or self._tcp_server is not None

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        try:
            self._udp_transport, _ = await loop.create_datagram_endpoint(
                lambda: _UdpProtocol(self),
                local_addr=(self._host_ip, self._port),
                reuse_port=False,
            )
            self._tcp_server = await asyncio.start_server(
                self._handle_tcp, host=self._host_ip, port=self._port
            )
        except Exception:
            # Roll back a partial bind (e.g. UDP up, TCP failed) so we don't leak
            # a listener; the caller treats this as "DNS server did not start".
            await self.stop()
            raise
        _LOGGER.info(
            "Built-in DNS server listening on %s:%d - answering %s -> %s, "
            "forwarding everything else to %s",
            self._host_ip,
            self._port,
            ", ".join(sorted(self._hostnames)),
            self._answer_ip,
            self._upstream,
        )

    async def stop(self) -> None:
        if self._udp_transport is not None:
            self._udp_transport.close()
            self._udp_transport = None
        if self._tcp_server is not None:
            self._tcp_server.close()
            try:
                await self._tcp_server.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self._tcp_server = None

    def _local_answer_for(self, data: bytes) -> Optional[bytes]:
        """Return an A response if this query is for a hijacked host, else None."""
        parsed = _parse_question(data)
        if parsed is None:
            return None
        name, qtype, question_end = parsed
        if qtype == _QTYPE_A and name in self._hostnames:
            return _build_a_response(data, question_end, self._answer_ip)
        return None

    async def _handle_udp(self, data: bytes, addr, transport) -> None:
        try:
            reply = self._local_answer_for(data)
            if reply is None:
                reply = await self._forward_udp(data)
            if reply and transport is not None:
                transport.sendto(reply, addr)
        except Exception as err:  # noqa: BLE001 - a bad query must never crash us
            _LOGGER.debug("DNS UDP query handling failed: %s", err)

    async def _forward_udp(self, data: bytes) -> Optional[bytes]:
        loop = asyncio.get_event_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        try:
            await loop.sock_connect(sock, (self._upstream, DNS_PORT))
            await loop.sock_sendall(sock, data)
            return await asyncio.wait_for(loop.sock_recv(sock, 4096), _UPSTREAM_TIMEOUT)
        except (OSError, asyncio.TimeoutError) as err:
            _LOGGER.debug("DNS upstream (UDP) forward to %s failed: %s", self._upstream, err)
            return None
        finally:
            sock.close()

    async def _handle_tcp(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            length_bytes = await reader.readexactly(2)
            query = await reader.readexactly(struct.unpack(">H", length_bytes)[0])
            reply = self._local_answer_for(query)
            if reply is None:
                reply = await self._forward_tcp(query)
            if reply:
                writer.write(struct.pack(">H", len(reply)) + reply)
                await writer.drain()
        except (asyncio.IncompleteReadError, OSError, asyncio.TimeoutError) as err:
            _LOGGER.debug("DNS TCP query handling failed: %s", err)
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def _forward_tcp(self, query: bytes) -> Optional[bytes]:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._upstream, DNS_PORT), _UPSTREAM_TIMEOUT
            )
        except (OSError, asyncio.TimeoutError) as err:
            _LOGGER.debug("DNS upstream (TCP) connect to %s failed: %s", self._upstream, err)
            return None
        try:
            writer.write(struct.pack(">H", len(query)) + query)
            await writer.drain()
            length_bytes = await asyncio.wait_for(reader.readexactly(2), _UPSTREAM_TIMEOUT)
            return await asyncio.wait_for(
                reader.readexactly(struct.unpack(">H", length_bytes)[0]), _UPSTREAM_TIMEOUT
            )
        except (asyncio.IncompleteReadError, OSError, asyncio.TimeoutError) as err:
            _LOGGER.debug("DNS upstream (TCP) forward to %s failed: %s", self._upstream, err)
            return None
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass
