import json
import socket
import time
import os
import subprocess

SERVER_IP = "10.0.0.5"
SERVER_PORT = 9999
INTERVAL = 1

# Automatically identify the Mininet interface
interfaces = os.listdir("/sys/class/net")
matching = [i for i in interfaces if i.endswith("-eth0")]

if not matching:
    raise RuntimeError("Mininet interface not found")

INTERFACE = matching[0]
HOST_ID = INTERFACE.split("-")[0]

def read_stats():
    base = f"/sys/class/net/{INTERFACE}/statistics/"

    fields = ["tx_bytes", "rx_bytes", "tx_packets", "rx_packets"]
    values = []

    for field in fields:
        with open(base + field) as f:
            values.append(int(f.read()))

    return values


def measure_latency():
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", SERVER_IP],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            for part in result.stdout.split():
                if part.startswith("time="):
                    return float(part.split("=")[1])

        return -1

    except Exception:
        return -1


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

sequence = 0
previous_packets = None
previous_time = None

print(
    f"Agent {HOST_ID} started on {INTERFACE}",
    flush=True
)

try:
    while True:
        now = time.time()
        current = time.monotonic()

        tx_bytes, rx_bytes, tx_packets, rx_packets = read_stats()

        if previous_packets is None:
            packet_rate = 0.0
        else:
            elapsed = current - previous_time
            packet_rate = (
                (tx_packets - previous_packets) / elapsed
                if elapsed > 0 else 0.0
            )

        latency = measure_latency()

        report = {
            "source": "host_telemetry",
            "host_id": HOST_ID,
            "timestamp": now,
            "sequence": sequence,
            "tx_bytes": tx_bytes,
            "rx_bytes": rx_bytes,
            "tx_packets": tx_packets,
            "rx_packets": rx_packets,
            "packet_rate": round(packet_rate, 2),
            "latency_ms": latency
        }

        sock.sendto(
            json.dumps(report).encode("utf-8"),
            (SERVER_IP, SERVER_PORT)
        )

        print(
            f"[{HOST_ID}] seq={sequence} "
            f"TX={tx_bytes} RX={rx_bytes} "
            f"rate={packet_rate:.2f} pps "
            f"latency={latency} ms",
            flush=True
        )

        previous_packets = tx_packets
        previous_time = current
        sequence += 1

        time.sleep(INTERVAL)

except KeyboardInterrupt:
    print(f"Agent {HOST_ID} stopped")

finally:
    sock.close()
