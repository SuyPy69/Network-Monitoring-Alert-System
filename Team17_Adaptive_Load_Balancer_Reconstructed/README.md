# Team 17 Adaptive Load Balancer — reconstructed application files

## Important provenance note
The uploaded archive contained the monitoring/SDN files but did not contain the TCP application files. The three files in `src/` were generated now from the project interface and requirements recovered from the earlier project notes. They are **new reconstructed implementations**, not recovered copies of the original files and have not been demonstrated on the user's Mininet setup yet.

## Files
- `src/client.py` — TCP client, one JSON request per connection, newline-delimited framing.
- `src/server.py` — threaded TCP backend; run two instances on ports 9001 and 9002.
- `src/load_balancer.py` — threaded TCP proxy on port 8000; supports `round_robin` and `adaptive`.
- `team17-monitoring/agent/udp_agent.py` — existing uploaded host telemetry agent.
- `team17-monitoring/server/monitoring_server.py` — existing uploaded telemetry receiver.
- `team17-monitoring/topology.py` — existing uploaded Mininet topology.
- `pox/ext/team17_monitor.py` — existing uploaded POX module.

## Quick local test (three terminals)
From the project root:

Terminal 1:
```bash
python3 src/server.py --name server1 --port 9001 --delay 0.2
```

Terminal 2:
```bash
python3 src/server.py --name server2 --port 9002 --delay 0.2
```

Terminal 3:
```bash
python3 src/load_balancer.py --host 127.0.0.1 --port 8000 --algorithm round_robin
```

Then:
```bash
python3 src/client.py --host 127.0.0.1 --port 8000 --count 10 --workers 5
```

Stop the load balancer with Ctrl+C and restart it with:
```bash
python3 src/load_balancer.py --host 127.0.0.1 --port 8000 --algorithm adaptive
```

For Mininet, use each host's actual IP address, not 127.0.0.1. Example:
```bash
# On backend host h3
python3 server.py --name server1 --host 0.0.0.0 --port 9001

# On backend host h4
python3 server.py --name server2 --host 0.0.0.0 --port 9002

# On the load-balancer host, substitute the real backend IPs:
python3 load_balancer.py --host 0.0.0.0 --port 8000 --algorithm adaptive \
  --backend server1,10.0.0.3,9001 \
  --backend server2,10.0.0.4,9002
```

## Protocol
Request:
```json
{"request_id": 1, "payload": "hello"}
```
Response:
```json
{"request_id": 1, "server": "server1", "status": "ok"}
```
The actual response also includes active-request, timing and algorithm metadata.

## Adaptive logic and limitations
- Health is checked by opening a TCP connection and sending `{"type":"health"}`.
- The proxy tracks in-flight requests and uses backend overload flags returned by the backend.
- The adaptive policy prefers healthy, non-overloaded backends with fewer in-flight requests.
- The overload signal is a simple demonstration mechanism, not OS-level CPU/memory measurement.
- The generated proxy is an application-layer TCP proxy. It does not install OpenFlow rules.

## Controller integration
The uploaded `pox/ext/team17_monitor.py` is the actual POX controller extension in the existing project. It currently accepts its own control messages for the ICMP flows defined in that file; it is **not automatically wired** to the new load balancer's backend-overload events. The old plan mentioned a separate `src/controller.py`, but the actual POX extension and current Mininet topology are the controller implementation present in the uploaded source. A separate app-to-controller event API must be agreed and tested before claiming end-to-end SDN integration. No fake `controller.py` shim is included.

## Thresholds
The user confirmed `~/team17-monitoring/thresholds.json` exists in WSL, but it was not in the uploaded ZIP, so its exact contents could not be copied. `thresholds.json.example` is a starter example only. Replace it with the user's actual file before running the monitoring server.

## Validation
The new Python files are syntax-compiled. This is not a runtime/integration test. Run the quick local test above before using this in the demo.
