#!/usr/bin/env python3
"""TCP client for the Team 17 adaptive load balancer.

Protocol: one newline-delimited JSON request per TCP connection.
Example request: {"request_id": 1, "payload": "hello"}
"""
import argparse
import concurrent.futures
import json
import socket
import time


def send_request(host, port, request_id, payload, timeout=5.0):
    request = {"request_id": request_id, "payload": payload}
    started = time.perf_counter()

    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall((json.dumps(request) + "\n").encode("utf-8"))

        received = bytearray()
        while not received.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            received.extend(chunk)
            if len(received) > 1_000_000:
                raise ValueError("Response exceeded 1 MB")

    if not received:
        raise ConnectionError("Load balancer closed the connection without a response")

    response = json.loads(received.decode("utf-8").strip())
    response["client_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return response


def main():
    parser = argparse.ArgumentParser(description="Send requests to the Team 17 load balancer")
    parser.add_argument("--host", default="127.0.0.1", help="Load balancer IP")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--count", type=int, default=1, help="Number of requests")
    parser.add_argument("--workers", type=int, default=1, help="Concurrent client workers")
    parser.add_argument("--payload", default="hello from Team 17")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    if args.count < 1 or args.workers < 1:
        parser.error("--count and --workers must both be at least 1")

    def run_one(request_id):
        return send_request(args.host, args.port, request_id, args.payload, args.timeout)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, i + 1) for i in range(args.count)]
        for future in concurrent.futures.as_completed(futures):
            try:
                print(json.dumps(future.result(), sort_keys=True))
            except Exception as exc:
                print(json.dumps({"status": "error", "error": str(exc)}))


if __name__ == "__main__":
    main()
