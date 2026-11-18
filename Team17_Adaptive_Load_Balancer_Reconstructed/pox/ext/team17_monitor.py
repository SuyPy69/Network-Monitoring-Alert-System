
from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.recoco import Timer
from pox.lib.addresses import IPAddr
from pox.lib.packet import ethernet, ipv4
import socket
import json
import time

log = core.getLogger()

MONITOR_HOST = "10.0.0.5"
MONITOR_PORT = 9999
CONTROL_PORT = 10000

BLOCK_PRIORITY = 65000
BLOCK_TIMEOUT = 60

ALLOWED_FLOWS = {
    ("10.0.0.1", "10.0.0.2"),
    ("10.0.0.2", "10.0.0.1"),
    ("10.0.0.3", "10.0.0.4"),
    ("10.0.0.4", "10.0.0.3")
}


class Team17Monitor:

    def __init__(self, poll_interval=5):
        self.poll_interval = float(poll_interval)

        self.sock = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM
        )

        self.control_sock = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM
        )
        self.control_sock.setsockopt(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
        )
        self.control_sock.bind(("", CONTROL_PORT))
        self.control_sock.setblocking(False)

        self.flow_counters = {}
        self.port_counters = {}

        core.openflow.addListeners(self)

        Timer(
            self.poll_interval,
            self._poll,
            recurring=True
        )

        # Poll control messages on the POX event loop.
        Timer(0.2, self._poll_control, recurring=True)

        log.info("Team 17 statistics monitor started")
        log.info("Statistics polling interval: %s seconds",
                 self.poll_interval)
        log.info("Telemetry destination: %s:%s",
                 MONITOR_HOST, MONITOR_PORT)
        log.info("Control alert listener active on UDP %s",
                 CONTROL_PORT)

    def _send_report(self, report):
        try:
            payload = json.dumps(report).encode("utf-8")
            self.sock.sendto(
                payload, (MONITOR_HOST, MONITOR_PORT)
            )
        except OSError:
            log.exception("Failed to send telemetry")

    # --------------------------------------------------
    # RECEIVE ALERTS FROM MONITORING SERVER
    # --------------------------------------------------

    def _poll_control(self):
        while True:
            try:
                data, address = self.control_sock.recvfrom(4096)
            except BlockingIOError:
                break
            except OSError:
                log.exception("Control socket error")
                break

            try:
                message = json.loads(data.decode("utf-8"))

                action = message.get("action")
                src_ip = message.get("src_ip")
                dst_ip = message.get("dst_ip")
                protocol = message.get("protocol")

                if (src_ip, dst_ip) not in ALLOWED_FLOWS:
                    log.warning("Rejected control flow: %s -> %s",
                                src_ip, dst_ip)
                    continue

                if protocol != "icmp":
                    log.warning("Rejected unsupported protocol")
                    continue

                if action not in ("block", "clear"):
                    log.warning("Rejected action: %s", action)
                    continue

                log.warning(
                    "[CONTROL] Received %s alert: %s -> %s",
                    action, src_ip, dst_ip
                )

                self._apply_control_action(
                    action, src_ip, dst_ip
                )

            except (ValueError, UnicodeDecodeError) as exc:
                log.warning("Invalid control message: %s", exc)

    def _apply_control_action(self, action, src_ip, dst_ip):
        for connection in list(core.openflow.connections.values()):
            try:
                match = of.ofp_match()
                match.dl_type = ethernet.IP_TYPE
                match.nw_proto = ipv4.ICMP_PROTOCOL
                match.nw_src = IPAddr(src_ip)
                match.nw_dst = IPAddr(dst_ip)

                message = of.ofp_flow_mod()
                message.match = match

                if action == "block":
                    message.command = of.OFPFC_ADD
                    message.priority = BLOCK_PRIORITY
                    message.idle_timeout = 0
                    message.hard_timeout = BLOCK_TIMEOUT
                    # No actions means matching packets are dropped.

                    connection.send(message)

                    log.warning(
                        "[CONTROL] Installed ICMP DROP rule "
                        "on switch %s: %s -> %s",
                        connection.dpid, src_ip, dst_ip
                    )

                else:
                    message.command = of.OFPFC_DELETE
                    message.priority = BLOCK_PRIORITY
                    message.out_port = of.OFPP_NONE

                    connection.send(message)

                    log.warning(
                        "[CONTROL] Removed ICMP DROP rule "
                        "on switch %s: %s -> %s",
                        connection.dpid, src_ip, dst_ip
                    )

            except Exception:
                log.exception("Failed to apply control action")

    # --------------------------------------------------
    # SWITCH EVENTS
    # --------------------------------------------------

    def _handle_ConnectionUp(self, event):
        log.info("Switch connected: dpid=%s", event.dpid)

    def _handle_ConnectionDown(self, event):
        log.warning("Switch disconnected: dpid=%s", event.dpid)

        self.flow_counters = {
            k: v for k, v in self.flow_counters.items()
            if k[0] != event.dpid
        }

        self.port_counters = {
            k: v for k, v in self.port_counters.items()
            if k[0] != event.dpid
        }

    # --------------------------------------------------
    # PERIODIC STATISTICS POLLING
    # --------------------------------------------------

    def _poll(self):
        for connection in list(core.openflow.connections.values()):
            try:
                flow_request = of.ofp_stats_request()
                flow_request.body = of.ofp_flow_stats_request()
                connection.send(flow_request)

                port_request = of.ofp_stats_request()
                port_request.body = of.ofp_port_stats_request(
                    port_no=of.OFPP_NONE
                )
                connection.send(port_request)

            except Exception:
                log.exception("Failed to request switch statistics")

    # --------------------------------------------------
    # FLOW STATISTICS
    # --------------------------------------------------

    def _handle_FlowStatsReceived(self, event):
        now = time.time()

        log.info("Flow statistics received: dpid=%s entries=%s",
                 event.dpid, len(event.stats))

        for stat in event.stats:
            key = (
                event.dpid,
                stat.table_id,
                stat.priority,
                str(stat.match),
                stat.cookie
            )

            previous = self.flow_counters.get(key)
            pps = 0.0
            bps = 0.0

            if previous:
                elapsed = now - previous["time"]
                packet_diff = stat.packet_count - previous["packets"]
                byte_diff = stat.byte_count - previous["bytes"]

                if elapsed > 0 and packet_diff >= 0 and byte_diff >= 0:
                    pps = packet_diff / elapsed
                    bps = byte_diff / elapsed

            self.flow_counters[key] = {
                "time": now,
                "packets": stat.packet_count,
                "bytes": stat.byte_count
            }

            self._send_report({
                "source": "openflow_flow",
                "switch_id": event.dpid,
                "timestamp": now,
                "table_id": stat.table_id,
                "priority": stat.priority,
                "cookie": stat.cookie,
                "flow_match": str(stat.match),
                "packet_count": stat.packet_count,
                "byte_count": stat.byte_count,
                "packets_per_second": round(pps, 2),
                "bytes_per_second": round(bps, 2)
            })

    # --------------------------------------------------
    # PORT STATISTICS
    # --------------------------------------------------

    def _handle_PortStatsReceived(self, event):
        now = time.time()

        log.info("Port statistics received: dpid=%s ports=%s",
                 event.dpid, len(event.stats))

        for stat in event.stats:
            key = (event.dpid, stat.port_no)
            previous = self.port_counters.get(key)

            rx_pps = tx_pps = rx_bps = tx_bps = 0.0

            if previous:
                elapsed = now - previous["time"]

                if elapsed > 0:
                    differences = [
                        stat.rx_packets - previous["rx_packets"],
                        stat.tx_packets - previous["tx_packets"],
                        stat.rx_bytes - previous["rx_bytes"],
                        stat.tx_bytes - previous["tx_bytes"]
                    ]

                    if min(differences) >= 0:
                        rx_pps = differences[0] / elapsed
                        tx_pps = differences[1] / elapsed
                        rx_bps = differences[2] / elapsed
                        tx_bps = differences[3] / elapsed

            self.port_counters[key] = {
                "time": now,
                "rx_packets": stat.rx_packets,
                "tx_packets": stat.tx_packets,
                "rx_bytes": stat.rx_bytes,
                "tx_bytes": stat.tx_bytes
            }

            self._send_report({
                "source": "openflow_port",
                "switch_id": event.dpid,
                "timestamp": now,
                "port_no": stat.port_no,
                "rx_bytes": stat.rx_bytes,
                "tx_bytes": stat.tx_bytes,
                "rx_packets": stat.rx_packets,
                "tx_packets": stat.tx_packets,
                "rx_dropped": stat.rx_dropped,
                "tx_dropped": stat.tx_dropped,
                "rx_packets_per_second": round(rx_pps, 2),
                "tx_packets_per_second": round(tx_pps, 2),
                "rx_bytes_per_second": round(rx_bps, 2),
                "tx_bytes_per_second": round(tx_bps, 2)
            })


def launch(poll_interval="5"):
    core.registerNew(Team17Monitor, float(poll_interval))
