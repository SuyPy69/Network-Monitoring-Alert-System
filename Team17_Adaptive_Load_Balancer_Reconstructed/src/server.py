#!/usr/bin/env python3
"""Threaded TCP backend server for Team 17.

Run two instances:
  python3 src/server.py --name server1 --port 9001
  python3 src/server.py --name server2 --port 9002

Each connection carries one newline-delimited JSON request.
"""
import argparse
import json
import os
import socket
import threading
import time

MAX_LINE = 1_000_000


class Backend:
    def __init__(self, name, host, port, max_active, delay):
        self.name = name
        self.host = host
        self.port = port
        self.max_active = max_active
        self.delay = delay
        self._lock = threading.Lock()
        self._active = 0
        self._completed = 0

    def snapshot(self):
        with self._lock:
            return self._active, self._completed

    def handle(self, conn, address):
        with self._lock:
            self._active += 1
            active_at_start = self._active

        started = time.perf_counter()
        try:
            conn.settimeout(10.0)
            stream = conn.makefile("rb")
            raw = stream.readline(MAX_LINE + 1)
            if not raw:
                return
            if len(raw) > MAX_LINE:
                raise ValueError("Request line too large")

            request = json.loads(raw.decode("utf-8").strip())
            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object")

            if request.get("type") == "health":
                active, completed = self.snapshot()
                response = {
                    "status": "ok",
                    "type": "health",
                    "server": self.name,
                    "healthy": True,
                    "overloaded": active >= self.max_active,
                    "active_requests": active,
                    "completed_requests": completed,
                }
            else:
                # Optional delay makes concurrency/overload tests reproducible.
                if self.delay > 0:
                    time.sleep(self.delay)

                overloaded = active_at_start > self.max_active
                response = {
                    "request_id": request.get("request_id"),
                    "server": self.name,
                    "status": "ok",
                    "payload": request.get("payload"),
                    "active_requests": active_at_start,
                    "overloaded": overloaded,
                    "processing_ms": round((time.perf_counter() - started) * 1000, 2),
                }

            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
            with self._lock:
                self._completed += 1

        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            error = {"status": "error", "server": self.name, "error": str(exc)}
            try:
                conn.sendall((json.dumps(error) + "\n").encode("utf-8"))
            except OSError:
                pass
        except (OSError, socket.timeout):
            pass
        finally:
            with self._lock:
                self._active = max(0, self._active - 1)

    def serve_forever(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen(128)
            print(f"[{self.name}] listening on {self.host}:{self.port}", flush=True)

            while True:
                conn, address = listener.accept()
                thread = threading.Thread(
                    target=self._serve_connection,
                    args=(conn, address),
                    daemon=True,
                )
                thread.start()

    def _serve_connection(self, conn, address):
        with conn:
            self.handle(conn, address)


def main():
    parser = argparse.ArgumentParser(description="Team 17 TCP backend")
    parser.add_argument("--name", default=os.getenv("SERVER_NAME", "server1"))
    parser.add_argument("--host", default=os.getenv("SERVER_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("SERVER_PORT", "9001")))
    parser.add_argument("--max-active", type=int, default=int(os.getenv("MAX_ACTIVE", "4")))
    parser.add_argument("--delay", type=float, default=float(os.getenv("PROCESSING_DELAY", "0")))
    args = parser.parse_args()

    if args.max_active < 1 or args.delay < 0:
        parser.error("--max-active must be >= 1 and --delay must be >= 0")

    Backend(args.name, args.host, args.port, args.max_active, args.delay).serve_forever()


if __name__ == "__main__":
    main()
