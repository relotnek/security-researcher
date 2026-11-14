"""Allowlisting egress gateway.

The only way out of a contained instance. Contained instances sit on an
internal network with no route anywhere; this proxy is the single host that
is also attached to an egress network, and it forwards only to destinations
on the allowlist (default deny).

ALLOWLIST is a comma-separated list of ``host`` or ``host:port`` entries
(host may be a glob such as ``*.example.com``). A bare host allows ports 80
and 443 only.
"""

import asyncio
import fnmatch
import os
import sys
from urllib.parse import urlsplit

ALLOW = [e.strip().lower() for e in os.environ.get("ALLOWLIST", "").split(",") if e.strip()]
PORT = int(os.environ.get("PROXY_PORT", "3128"))


def allowed(host: str, port: int) -> bool:
    host = host.lower().rstrip(".")
    for entry in ALLOW:
        name, sep, eport = entry.rpartition(":")
        if sep and eport.isdigit():
            if fnmatch.fnmatchcase(host, name) and port == int(eport):
                return True
        elif fnmatch.fnmatchcase(host, entry) and port in (80, 443):
            return True
    return False


def log(verdict: str, peer, host: str, port: int) -> None:
    print(f"{verdict} src={peer[0] if peer else '?'} dst={host}:{port}", flush=True)


async def pipe(reader, writer) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def reply(writer, status: str) -> None:
    writer.write(f"HTTP/1.1 {status}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".encode())
    await writer.drain()
    writer.close()


async def handle(reader, writer) -> None:
    peer = writer.get_extra_info("peername")
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
        request_line, _, rest = head.partition(b"\r\n")
        method, target, version = request_line.decode("latin-1").split(" ", 2)
        if method.upper() == "CONNECT":
            host, _, port = target.rpartition(":")
            host, port, payload = host.strip("[]"), int(port), b""
        else:
            url = urlsplit(target)
            if url.scheme != "http" or not url.hostname:
                return await reply(writer, "400 Bad Request")
            host, port = url.hostname, url.port or 80
            path = (url.path or "/") + (f"?{url.query}" if url.query else "")
            headers = [
                line
                for line in rest.split(b"\r\n")
                if line and not line.lower().startswith((b"proxy-", b"connection:"))
            ]
            payload = (
                f"{method} {path} {version}\r\n".encode("latin-1")
                + b"\r\n".join(headers)
                + b"\r\nConnection: close\r\n\r\n"
            )
    except Exception:
        return await reply(writer, "400 Bad Request")

    if not allowed(host, port):
        log("DENY", peer, host, port)
        return await reply(writer, "403 Forbidden")
    try:
        up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(host, port), 15)
    except Exception:
        log("FAIL", peer, host, port)
        return await reply(writer, "502 Bad Gateway")
    log("ALLOW", peer, host, port)
    if method.upper() == "CONNECT":
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
    else:
        up_writer.write(payload)
        await up_writer.drain()
    await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))


async def main() -> None:
    server = await asyncio.start_server(handle, "0.0.0.0", PORT)
    print(f"egress gateway listening on :{PORT}, allowlist={ALLOW}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
