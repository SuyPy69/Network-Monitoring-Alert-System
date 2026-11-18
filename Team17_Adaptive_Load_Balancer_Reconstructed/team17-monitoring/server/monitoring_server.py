
import csv
import json
import os
import socket
import time
import math

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_FILE = os.path.join(BASE_DIR, "thresholds.json")
RESULTS_DIR = os.path.join(BASE_DIR, "results")

ALERTS_FILE = os.path.join(RESULTS_DIR, "alerts.csv")
REPORTS_FILE = os.path.join(RESULTS_DIR, "telemetry.csv")

HOST = "0.0.0.0"
PORT = 9999

with open(CONFIG_FILE, "r") as f:
    config = json.load(f)

INTERVAL = config.get("reporting_interval_seconds", 2)

REPORT_TIMEOUT = INTERVAL * config.get(
    "missed_reports", {}
).get("critical", 3)

CAPACITY_MBPS = config.get("default_link_capacity_mbps", 10)
SUSTAINED_INTERVALS = config.get("sustained_violation_intervals", 3)

# Map each monitored host to its OpenFlow switch port.
# Verify these port numbers using: sh ovs-ofctl show s1
HOST_PORT_MAP = {
    "h1": 1,
    "h2": 2,
    "h3": 3,
    "h4": 4
}

# Maximum permitted age of either rate measurement.
MISMATCH_MAX_AGE = 10

# Ignore extremely low traffic rates.
MISMATCH_MIN_RATE = 100  # bytes per second

os.makedirs(RESULTS_DIR, exist_ok=True)

# --------------------------------------------------
# CSV STRUCTURE
# --------------------------------------------------

report_fields = [
    "received_time", "timestamp", "source", "host_id",
    "switch_id", "sequence", "port_no", "packet_count",
    "byte_count", "tx_packets", "rx_packets",
    "tx_bytes", "rx_bytes", "packet_rate",
    "latency_ms", "packets_per_second",
    "bytes_per_second", "link_utilisation_percent"
]

alert_fields = [
    "timestamp", "severity", "subject", "message"
]


def ensure_csv(path, fields):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()


ensure_csv(REPORTS_FILE, report_fields)
ensure_csv(ALERTS_FILE, alert_fields)


# --------------------------------------------------
# ALERT HANDLING
# --------------------------------------------------

def alert(severity, subject, message):
    now = time.time()

    print(
        f"[{severity}] {subject}: {message}",
        flush=True
    )

    with open(ALERTS_FILE, "a", newline="") as f:
        csv.DictWriter(
            f, fieldnames=alert_fields
        ).writerow({
            "timestamp": now,
            "severity": severity,
            "subject": subject,
            "message": message
        })
# --------------------------------------------------
# SDN CONTROLLER ALERT NOTIFICATION
# --------------------------------------------------

CONTROLLER_HOST = "10.0.0.254"
CONTROLLER_PORT = 10000

controller_sock = socket.socket(
    socket.AF_INET,
    socket.SOCK_DGRAM
)

ALERT_FLOW_MAP = {
    "h1": ("10.0.0.1", "10.0.0.2"),
    "h2": ("10.0.0.2", "10.0.0.1"),
    "h3": ("10.0.0.3", "10.0.0.4"),
    "h4": ("10.0.0.4", "10.0.0.3")
}


def notify_controller(action, host_id):
    flow = ALERT_FLOW_MAP.get(host_id)

    if flow is None:
        return

    message = {
        "action": action,
        "src_ip": flow[0],
        "dst_ip": flow[1],
        "protocol": "icmp"
    }

    try:
        controller_sock.sendto(
            json.dumps(message).encode("utf-8"),
            (CONTROLLER_HOST, CONTROLLER_PORT)
        )

        print(
            f"[CONTROLLER ACTION] {action} "
            f"{flow[0]} -> {flow[1]}",
            flush=True
        )

    except OSError as exc:
        print(
            f"[CONTROLLER ACTION ERROR] {exc}",
            flush=True
        )

def valid_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def valid_counter(value):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )


# --------------------------------------------------
# THRESHOLD EVALUATION
# --------------------------------------------------

violation_states = {}


def evaluate_threshold(subject, metric, value, limits, unit):
    if not valid_number(value):
        return

    warning = limits.get("warning")
    critical = limits.get("critical")

    if (
        not valid_number(warning)
        or not valid_number(critical)
    ):
        return

    key = (subject, metric)
    previous_state = violation_states.get(key)

    # Fully recovered: below warning threshold.
    if value < warning:
        if (
            previous_state
            and previous_state.get("alerted")
            and metric == "traffic_mismatch_percent"
        ):
            notify_controller("clear", subject)

        violation_states.pop(key, None)
        return

    level = "CRITICAL" if value >= critical else "WARNING"

    # Preserve an existing critical state during warning-level recovery.
    if (
        previous_state
        and previous_state.get("level") == "CRITICAL"
        and level == "WARNING"
    ):
        previous_state["count"] += 1
        return

    if previous_state is None or previous_state["level"] != level:
        state = {
            "level": level,
            "count": 1,
            "alerted": False
        }
        violation_states[key] = state
    else:
        state = previous_state
        state["count"] += 1

    if (
        state["count"] >= SUSTAINED_INTERVALS
        and not state["alerted"]
    ):
        alert(
            level,
            subject,
            f"{metric} is {value} {unit}; threshold is "
            f"{critical if level == 'CRITICAL' else warning}"
        )

        state["alerted"] = True

        if (
            level == "CRITICAL"
            and metric == "traffic_mismatch_percent"
        ):
            notify_controller("block", subject)# TELEMETRY STATE
# --------------------------------------------------

latest_hosts = {}
host_counters = {}
previous_counters = {}
last_stale_alert = {}

# Calculated host TX and switch RX throughput.
host_rate_state = {}
switch_rate_state = {}

# Prevent repeating the same comparison.
last_mismatch_pair = {}


# --------------------------------------------------
# TRAFFIC MISMATCH DETECTION
# --------------------------------------------------

def check_traffic_mismatch(host_id):
    """
    Compare host TX throughput against the RX throughput
    of its corresponding OpenFlow switch port.

    These are independently sampled rates, so this is
    an approximate monitoring comparison, not an exact
    packet-loss measurement.
    """

    port_no = HOST_PORT_MAP.get(host_id)

    if port_no is None:
        return

    host_data = host_rate_state.get(host_id)
    switch_data = switch_rate_state.get(port_no)

    if not host_data or not switch_data:
        return

    now = time.time()

    # Ignore stale measurements.
    if now - host_data["time"] > MISMATCH_MAX_AGE:
        return

    if now - switch_data["time"] > MISMATCH_MAX_AGE:
        return

    # Only compare when at least one measurement is new.
    pair = (
        host_data["time"],
        switch_data["time"]
    )

    if last_mismatch_pair.get(host_id) == pair:
        return

    last_mismatch_pair[host_id] = pair

    host_rate = host_data["rate"]
    switch_rate = switch_data["rate"]

    maximum_rate = max(host_rate, switch_rate)

    # Avoid unstable percentages at very low traffic.
    if maximum_rate < MISMATCH_MIN_RATE:
        evaluate_threshold(
            host_id,
            "traffic_mismatch_percent",
            0,
            config.get("traffic_mismatch_percent", {}),
            "%"
        )
        return

    difference = abs(host_rate - switch_rate)

    mismatch_percent = (
        difference / maximum_rate
    ) * 100

    print(
        f"[MISMATCH CHECK] {host_id} "
        f"host_tx={host_rate:.2f} bytes/s "
        f"switch_rx={switch_rate:.2f} bytes/s "
        f"difference={mismatch_percent:.2f}%",
        flush=True
    )

    evaluate_threshold(
        host_id,
        "traffic_mismatch_percent",
        mismatch_percent,
        config.get("traffic_mismatch_percent", {}),
        "%"
    )


# --------------------------------------------------
# UDP SERVER
# --------------------------------------------------

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((HOST, PORT))
sock.settimeout(1.0)

print(
    f"Monitoring server listening on UDP {PORT}",
    flush=True
)


while True:

    now = time.time()

    try:
        data, address = sock.recvfrom(65535)

        report = json.loads(data.decode("utf-8"))

        if not isinstance(report, dict):
            raise ValueError("Report must be a JSON object")

        source = report.get("source", "host_telemetry")

        # ------------------------------------------
        # HOST TELEMETRY
        # ------------------------------------------

        if source == "host_telemetry":

            host_id = report.get("host_id")
            sequence = report.get("sequence")

            if not isinstance(host_id, str) or not host_id:
                raise ValueError("Missing host_id")

            if (
                not isinstance(sequence, int)
                or isinstance(sequence, bool)
                or sequence < 0
            ):
                raise ValueError("Invalid sequence number")

            previous = latest_hosts.get(host_id)

            if previous and sequence <= previous["sequence"]:
                alert(
                    "WARNING",
                    host_id,
                    f"Duplicate or out-of-order sequence {sequence}"
                )
                continue

            if previous and sequence > previous["sequence"] + 1:
                missing = sequence - previous["sequence"] - 1
                alert(
                    "WARNING",
                    host_id,
                    f"Sequence gap detected: {missing} missing report(s), "
                    f"previous={previous['sequence']}, current={sequence}"
                )

            latest_hosts[host_id] = {
                "sequence": sequence,
                "last_seen": now
            }

            last_stale_alert.pop(host_id, None)

            latency = report.get("latency_ms")
            packet_rate = report.get("packet_rate")
            tx_bytes = report.get("tx_bytes")

            # Latency threshold.
            if valid_number(latency) and latency >= 0:
                evaluate_threshold(
                    host_id,
                    "latency_ms",
                    latency,
                    config.get("latency_ms", {}),
                    "ms"
                )

            # Packet-rate threshold.
            if valid_number(packet_rate) and packet_rate >= 0:
                evaluate_threshold(
                    host_id,
                    "packet_rate_pps",
                    packet_rate,
                    config.get("packet_rate_pps", {}),
                    "PPS"
                )

            utilisation = ""
            tx_rate = None

            # Calculate host TX throughput.
            if valid_counter(tx_bytes):

                previous_tx = host_counters.get(host_id)

                if previous_tx:

                    elapsed = now - previous_tx["time"]

                    difference = (
                        tx_bytes - previous_tx["tx_bytes"]
                    )

                    if elapsed > 0 and difference >= 0:

                        tx_rate = difference / elapsed
                        tx_bps = tx_rate * 8

                        utilisation = (
                            tx_bps /
                            (CAPACITY_MBPS * 1_000_000)
                        ) * 100

                        evaluate_threshold(
                            host_id,
                            "link_utilisation_percent",
                            utilisation,
                            config.get(
                                "link_utilisation_percent", {}
                            ),
                            "%"
                        )

                    elif difference < 0:
                        # Counter reset: discard old rate.
                        host_rate_state.pop(host_id, None)

                host_counters[host_id] = {
                    "time": now,
                    "tx_bytes": tx_bytes
                }

            # Store host throughput and compare.
            if tx_rate is not None:

                host_rate_state[host_id] = {
                    "time": now,
                    "rate": tx_rate
                }

                check_traffic_mismatch(host_id)

            report["link_utilisation_percent"] = utilisation

            print(
                f"[HOST] {host_id} "
                f"seq={sequence} "
                f"latency={latency} ms "
                f"rate={packet_rate} PPS "
                f"utilisation={utilisation}",
                flush=True
            )

        # ------------------------------------------
        # OPENFLOW FLOW AND PORT TELEMETRY
        # ------------------------------------------

        elif source in ("openflow_flow", "openflow_port"):

            if "switch_id" not in report:
                raise ValueError("Missing switch_id")

            if source == "openflow_port":
                if "port_no" not in report:
                    raise ValueError("Missing port_no")

            key = (
                source,
                report.get("switch_id"),
                report.get("port_no"),
                report.get("table_id"),
                report.get("flow_match"),
                report.get("cookie")
            )

            if source == "openflow_flow":
                packet_field = "packet_count"
                byte_field = "byte_count"

            else:
                packet_field = "rx_packets"
                byte_field = "rx_bytes"

            packets = report.get(packet_field)
            byte_count = report.get(byte_field)

            if (
                not valid_counter(packets)
                or not valid_counter(byte_count)
            ):
                raise ValueError("Invalid OpenFlow counters")

            previous = previous_counters.get(key)

            pps = ""
            bps = ""

            if previous:

                elapsed = now - previous["time"]

                dp = packets - previous["packets"]
                db = byte_count - previous["bytes"]

                if elapsed > 0 and dp >= 0 and db >= 0:

                    pps = round(dp / elapsed, 2)
                    bps = round(db / elapsed, 2)

                elif dp < 0 or db < 0:
                    # Counter reset: invalidate old rate.
                    if source == "openflow_port":
                        switch_rate_state.pop(
                            report.get("port_no"), None
                        )

            previous_counters[key] = {
                "time": now,
                "packets": packets,
                "bytes": byte_count
            }

            report["packets_per_second"] = pps
            report["bytes_per_second"] = bps

            # Store switch RX throughput and compare.
            if source == "openflow_port":

                port_no = report.get("port_no")

                if (
                    isinstance(port_no, int)
                    and not isinstance(port_no, bool)
                    and port_no in HOST_PORT_MAP.values()
                    and valid_number(bps)
                ):

                    switch_rate_state[port_no] = {
                        "time": now,
                        "rate": bps
                    }

                    for host_id, mapped_port in HOST_PORT_MAP.items():

                        if mapped_port == port_no:
                            check_traffic_mismatch(host_id)
                            break

            print(
                f"[SDN] {source} "
                f"switch={report['switch_id']} "
                f"port={report.get('port_no', '')} "
                f"packets={packets} "
                f"bytes={byte_count} "
                f"pps={pps} "
                f"bytes/s={bps}",
                flush=True
            )

        else:
            raise ValueError(
                f"Unknown report source: {source}"
            )

        # ------------------------------------------
        # SAVE TELEMETRY TO CSV
        # ------------------------------------------

        row = {
            "received_time": now,
            **{
                field: report.get(field, "")
                for field in report_fields
                if field != "received_time"
            }
        }

        with open(REPORTS_FILE, "a", newline="") as f:

            csv.DictWriter(
                f,
                fieldnames=report_fields
            ).writerow(row)

    except socket.timeout:
        pass

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError
    ) as exc:

        alert(
            "WARNING",
            str(address) if "address" in locals() else "UDP",
            f"Invalid report: {exc}"
        )

    except OSError as exc:

        print(
            f"Socket or file error: {exc}",
            flush=True
        )

    # ----------------------------------------------
    # MISSING HOST DETECTION
    # ----------------------------------------------

    now = time.time()

    for host_id, state in list(latest_hosts.items()):

        age = now - state["last_seen"]

        if age > REPORT_TIMEOUT:

            last_alert = last_stale_alert.get(host_id, 0)

            if now - last_alert > REPORT_TIMEOUT:

                alert(
                    "WARNING",
                    host_id,
                    f"No telemetry received for {age:.1f} seconds"
                )

                last_stale_alert[host_id] = now

