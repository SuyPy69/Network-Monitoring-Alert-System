#!/usr/bin/env python3
"""Concurrent TCP reverse proxy with round-robin and adaptive selection.

The client protocol is newline-delimited JSON. The proxy forwards each request
to one backend and relays the backend's JSON response.

Adaptive selection uses:
  1. backend reachability (TCP health probe),
  2. backend overload information returned by health/request responses,
  3. locally tracked in-flight requests.

This is an application-layer load balancer. It does not itself install
OpenFlow rules.
"""
import argparse
import json
import socket
import threading
import time
from dataclasses import dataclass, field

MAX_LINE = 1_000_000


@dataclass
class BackendState:
    name: str
    host: str
    port: int
    active: int = 0
    healthy: bool = True
    overloaded_until: float = 0.0
    last_check: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def load_snapshot(self):
        with self.lock:
            return self.active, self.healthy, self.overloaded_until


class LoadBalancer:
    def __init__(self, listen_host, listen_port, backends, algorithm="adaptive",
                 connect_timeout=1.5, overload_cooldown=3.0):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.backends = backends
        self.algorithm = algorithm
        self.connect_timeout = connect_timeout
        self.overload_cooldown = overload_cooldown
        self._rr_index = 0
        self._rr_lock = threading.Lock()
        self._stop = threading.Event()

    def _probe(self, backend):
        now = time.time()
        try:
            with socket.create_connection((backend.host, backend.port),
                                          timeout=self.connect_timeout) as sock:
                sock.settimeout(self.connect_timeout)
                sock.sendall(b'{"type":"health"}\n')
                data = self._read_line(sock)
                health = json.loads(data.decode("utf-8"))
                healthy = bool(health.get("healthy", False))
                overloaded = bool(health.get("overloaded", False))
            with backend.lock:
                backend.healthy = healthy
                backend.last_check = now
                if overloaded:
                    backend.overloaded_until = now + self.overload_cooldown
            return healthy
        except (OSError, ValueError, json.JSONDecodeError, socket.timeout):
            with backend.lock:
                backend.healthy = False
                backend.last_check = now
            return False

    @staticmethod
    def _read_line(sock):
        data = bytearray()
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_LINE:
                raise ValueError("Message line too large")
        if not data:
            raise ConnectionError("Peer closed without sending a response")
        return bytes(data).rstrip(b"\r\n")

    def _choose_backend(self, excluded=None):
        excluded = excluded or set()
        candidates = [b for b in self.backends if b.name not in excluded]

        # Refresh health if the last probe is older than one second.
        for backend in candidates:
            with backend.lock:
                due = time.time() - backend.last_check > 1.0
            if due:
                self._probe(backend)

        available = []
        now = time.time()
        for backend in candidates:
            active, healthy, overloaded_until = backend.load_snapshot()
            if healthy:
                available.append((backend, active, overloaded_until > now))

        if not available:
            return None

        if self.algorithm == "round_robin":
            with self._rr_lock:
                for offset in range(len(self.backends)):
                    idx = (self._rr_index + offset) % len(self.backends)
                    candidate = self.backends[idx]
                    if any(candidate is item[0] for item in available):
                        self._rr_index = (idx + 1) % len(self.backends)
                        return candidate
            return available[0][0]

        # Adaptive: prefer not-overloaded servers, then lowest in-flight count.
        non_overloaded = [item for item in available if not item[2]]
        pool = non_overloaded or available
        return min(pool, key=lambda item: (item[1], item[0].name))[0]

    def _forward(self, backend, request):
        with backend.lock:
            backend.active += 1
        try:
            with socket.create_connection((backend.host, backend.port),
                                          timeout=self.connect_timeout) as upstream:
                upstream.settimeout(10.0)
                upstream.sendall((json.dumps(request) + "\n").encode("utf-8"))
                raw = self._read_line(upstream)
                response = json.loads(raw.decode("utf-8"))
                if response.get("overloaded"):
                    with backend.lock:
                        backend.overloaded_until = time.time() + self.overload_cooldown
                return response
        finally:
            with backend.lock:
                backend.active = max(0, backend.active - 1)

    def handle_client(self, conn, address):
        with conn:
            try:
                conn.settimeout(10.0)
                raw = self._read_line(conn)
                request = json.loads(raw.decode("utf-8"))
                if not isinstance(request, dict):
                    raise ValueError("Request must be a JSON object")

                attempted = set()
                last_error = None
                for _ in range(len(self.backends)):
                    backend = self._choose_backend(excluded=attempted)
                    if backend is None:
                        break
                    attempted.add(backend.name)
                    try:
                        response = self._forward(backend, request)
                        response.setdefault("request_id", request.get("request_id"))
                        response["load_balancer_algorithm"] = self.algorithm
                        print(f"[LB] {address} -> {backend.name} ({self.algorithm})", flush=True)
                        conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
                        return
                    except (OSError, ValueError, json.JSONDecodeError, socket.timeout) as exc:
                        last_error = str(exc)
                        with backend.lock:
                            backend.healthy = False
                            backend.last_check = time.time()
                        print(f"[LB] backend {backend.name} failed: {exc}", flush=True)

                error = {
                    "request_id": request.get("request_id"),
                    "status": "error",
                    "error": "No healthy backend available",
                    "detail": last_error or "All backends are unhealthy or overloaded",
                }
                conn.sendall((json.dumps(error) + "\n").encode("utf-8"))

            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OSError, socket.timeout) as exc:
                error = {"status": "error", "error": str(exc)}
                try:
                    conn.sendall((json.dumps(error) + "\n").encode("utf-8"))
                except OSError:
                    pass

    def serve_forever(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.listen_host, self.listen_port))
            listener.listen(256)
            print(f"[LB] listening on {self.listen_host}:{self.listen_port}; algorithm={self.algorithm}", flush=True)
            print("[LB] backends: " + ", ".join(
                f"{b.name}={b.host}:{b.port}" for b in self.backends
            ), flush=True)

            while not self._stop.is_set():
                conn, address = listener.accept()
                threading.Thread(
                    target=self.handle_client,
                    args=(conn, address),
                    daemon=True,
                ).start()


def parse_backend(value):
    # Format: name,host,port
    parts = value.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("Backend must be name,host,port")
    name, host, port = parts
    try:
        return BackendState(name=name, host=host, port=int(port))
    except ValueError:
        raise argparse.ArgumentTypeError("Backend port must be an integer")


def main():
    parser = argparse.ArgumentParser(description="Team 17 TCP load balancer")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--algorithm", choices=("round_robin", "adaptive"), default="adaptive")
    parser.add_argument("--backend", action="append", type=parse_backend, dest="backends",
                        help="Repeat for each backend: name,host,port")
    args = parser.parse_args()

    backends = args.backends or [
        BackendState("server1", "127.0.0.1", 9001),
        BackendState("server2", "127.0.0.1", 9002),
    ]
    if not backends:
        parser.error("At least one backend is required")

    LoadBalancer(args.host, args.port, backends, args.algorithm).serve_forever()


if __name__ == "__main__":
    main()
