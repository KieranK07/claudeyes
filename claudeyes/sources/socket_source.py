"""Where actions come from.

Deliberately transport-dumb: one newline-delimited JSON object per action over
a Unix socket. Anything that acts on the screen -- your agent's tool wrapper, a
CGEventTap relaying your own keyboard and mouse, a Playwright driver -- posts
here before it acts. The bus does not care who the actor is; "self" just means
"an actor that told us what it was about to do".

    {"kind":"click","t":1724800000.12,"source":"agent",
     "params":{"bbox":{"x":620,"y":430,"w":150,"h":44},"app":"Safari"}}

Post BEFORE executing, not after. An action reported late is an action whose
consequences already surfaced as a false wake-up.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from typing import Callable

DEFAULT_PATH = os.environ.get(
    "CLAUDEYES_SOCK", os.path.expanduser("~/.claudeyes/actions.sock"))


class SocketActionSource:
    def __init__(self, on_action: Callable[[dict], None], path: str = DEFAULT_PATH):
        self.on_action = on_action
        self.path = path
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.path)
        srv.listen(8)
        srv.settimeout(0.5)
        self._thread = threading.Thread(target=self._serve, args=(srv,), daemon=True)
        self._thread.start()

    def _serve(self, srv: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()
        srv.close()

    def _client(self, conn: socket.socket) -> None:
        buf = b""
        with conn:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg.setdefault("t", time.time())
                    self.on_action(msg)

    def stop(self) -> None:
        self._stop.set()


def post(action: dict, path: str = DEFAULT_PATH) -> None:
    """Client helper. Wrap your agent's tool calls with this."""
    action.setdefault("t", time.time())
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path)
    s.sendall((json.dumps(action) + "\n").encode())
    s.close()
