# Network Monitoring and Alert System (UDP)

**Team 17 | PES University**

A network monitoring system built using **Mininet, Open vSwitch (OVS), POX, OpenFlow 1.0, and UDP socket programming**. The project combines host-side telemetry with network-side statistics collected through an SDN controller to monitor network activity in an emulated environment.

---

## 1. Project Overview

The Network Monitoring and Alert System monitors network activity across multiple virtual hosts in an emulated Software-Defined Networking (SDN) environment.

It uses two complementary monitoring approaches:

- **Application-side monitoring:** UDP telemetry agents send periodic reports from monitored hosts to a central monitoring server.
- **Network-side monitoring:** The POX SDN controller collects flow and port statistics from Open vSwitch using OpenFlow.

The central monitoring server receives telemetry, validates incoming reports, tracks host activity, and stores monitoring information in CSV files.

The project aims to provide a foundation for identifying abnormal network conditions such as silent hosts, congestion, and link failures.

## 2. Objectives

The main objectives are to:

- Collect periodic telemetry from multiple Mininet hosts using UDP sockets.
- Receive and validate telemetry reports through a centralized monitoring server.
- Detect missing, duplicate, and out-of-order telemetry reports using sequence numbers.
- Collect flow and port statistics from Open vSwitch through the POX controller.
- Calculate network traffic rates using successive counter readings.
- Calculate packets per second (PPS) and bytes per second (BPS).
- Maintain CSV-based records of telemetry and alert information.
- Integrate application-side and network-side monitoring information.

## 3. System Architecture

The system consists of four main components:

1. **Mininet Hosts:** Four virtual hosts generate network traffic and run telemetry agents.
2. **Open vSwitch:** Provides the virtual switching functionality.
3. **POX Controller:** Communicates with the switch using OpenFlow 1.0 and periodically requests flow and port statistics.
4. **Central Monitoring Server:** Receives UDP telemetry, processes reports, tracks host status, and records monitoring information.

### Monitoring workflow

1. Telemetry agents periodically collect and send host information through UDP.
2. The monitoring server receives reports on UDP port `9999`.
3. Incoming JSON reports are parsed and validated.
4. Sequence numbers and timestamps are used to track report ordering and missing reports.
5. The POX controller periodically requests flow and port statistics from the switch.
6. The controller calculates traffic rates using differences between successive counter readings and elapsed time.
7. Monitoring information is recorded in CSV files for further analysis.

## 4. Technologies Used

| Technology | Purpose |
|---|---|
| Python 3 | Implementation of agents, monitoring server and controller logic |
| Mininet | Network emulation |
| Open vSwitch (OVS) | Software-based network switching |
| POX | SDN controller |
| OpenFlow 1.0 | Controller-to-switch communication |
| UDP Sockets | Telemetry communication |
| JSON | Telemetry message representation |
| CSV | Persistent monitoring and alert records |
| Linux / Ubuntu | Development and execution environment |

## 5. Network Topology

The current project topology contains four Mininet hosts connected through one Open vSwitch.

| Component | Identifier | IP Address |
|---|---|---|
| Host 1 | h1 | 10.0.0.1 |
| Host 2 | h2 | 10.0.0.2 |
| Host 3 | h3 | 10.0.0.3 |
| Host 4 | h4 | 10.0.0.4 |
| Switch | s1 | — |

The POX controller manages the Open vSwitch through OpenFlow 1.0.

**Basic connectivity validation:** The recorded baseline test using `pingall` completed with 0% packet loss and 20 successful pings out of 20.

This validates basic host-to-host connectivity, not the complete monitoring functionality.

## 6. Communication and Configuration

The project uses the following baseline configuration:

| Parameter | Value |
|---|---|
| Telemetry transport | UDP |
| Telemetry format | JSON |
| Monitoring server port | 9999 |
| Agent reporting interval | 2 seconds |
| Controller polling interval | 5 seconds |
| Controller | POX |
| OpenFlow version | 1.0 |

UDP is connectionless and does not guarantee delivery, ordering, or duplicate protection. The application therefore uses sequence numbers and validation logic to identify missing, duplicated, or out-of-order reports.

## 7. Implemented Features

The following features are recorded as implemented or partially implemented in the current project baseline.

### Implemented

- UDP telemetry reception by the monitoring server.
- JSON parsing and basic message validation.
- Timestamp and sequence-number handling.
- Basic duplicate, out-of-order, and missing-report detection.
- POX flow-statistics and port-statistics polling.
- Calculation of PPS and BPS from successive counter readings.
- CSV-based telemetry and alert logging.

### Partially implemented / under testing

- Basic alert logging and alert handling.
- Full integration of four independent host agents.
- Multi-host monitoring and consolidated results presentation.

### Planned / pending

- Complete correlation of host telemetry with controller statistics.
- Discrepancy detection between application-side and network-side measurements.
- Link utilisation calculation and configurable thresholds.
- Sustained congestion detection.
- Complete alert categories, severity handling, suppression, and recovery events.
- Link-failure detection.
- Alert-driven controller responses, such as rate limiting or rerouting.
- Performance evaluation, including detection latency and monitoring overhead.
- Application-only versus combined monitoring comparison.

## 8. Installation and Prerequisites

The project is intended to run in a compatible Linux environment, preferably Ubuntu, with the required networking components installed.

### Required dependencies

- Python 3
- Mininet
- Open vSwitch
- POX controller
- OpenFlow 1.0 support
- Standard Python socket and JSON libraries

Check the Python installation:

```bash
python3 --version
```

Check Mininet:

```bash
mn --version
```

Check Open vSwitch:

```bash
sudo ovs-vsctl show
```

Make sure the POX controller and Mininet environment are installed and working before starting the project.

## 9. Running the Project

The following is the intended execution sequence. Replace the example filenames with the actual filenames in the repository.

### Step 1: Start the POX controller

Open a terminal in the POX directory and start the controller application:

```bash
./pox.py <controller_module>
```

### Step 2: Start the Mininet topology

Open another terminal and execute the topology script:

```bash
sudo python3 <topology_file>.py
```

Verify that the hosts and switch are created successfully.

### Step 3: Verify network connectivity

Inside the Mininet CLI, execute:

```text
pingall
```

Check that the hosts can communicate with one another.

### Step 4: Start the monitoring server

Open a separate terminal and run:

```bash
python3 <monitoring_server_file>.py
```

The server should listen for UDP telemetry on port `9999`.

### Step 5: Start the telemetry agents

Start the agent on each monitored host using the appropriate Mininet host command.

Example:

```text
mininet> h1 python3 <agent_file>.py
```

Repeat for the remaining hosts after configuring the appropriate host identifiers and server destination.

### Step 6: Verify monitoring output

Check the monitoring server's console output and generated CSV files to verify that reports are being received and recorded.

**Note:** The commands above are execution templates. Update the filenames, controller module name, and any required command-line arguments to match the actual source files in this repository.

## 10. Output Files

The monitoring server maintains CSV-based records.

| File | Purpose |
|---|---|
| `telemetry.csv` | Stores received telemetry records |
| `alerts.csv` | Stores alert and monitoring-condition records |

These files can be inspected using spreadsheet software or Python for further analysis and graph generation.

## 11. Testing and Validation

The project uses Mininet to create repeatable network conditions.

The current testing baseline includes:

- Verifying Mininet host connectivity using `pingall`.
- Checking UDP telemetry reception.
- Checking JSON parsing and validation.
- Checking sequence-number and missing-report handling.
- Verifying POX flow and port statistics collection.
- Verifying PPS and BPS calculations.
- Inspecting CSV output.

Additional planned testing includes:

- Stopping an agent to test silent-node detection.
- Increasing traffic to test congestion detection.
- Taking down a link to test link-failure detection.
- Measuring monitoring overhead and alert detection latency.
- Comparing application-only telemetry with combined telemetry and SDN statistics.

## 12. Project Limitations

The current implementation is designed for an emulated Mininet network and is not intended for direct production deployment on physical networks.

The following limitations apply to the current baseline:

- UDP telemetry does not include encryption or authentication.
- Full four-host telemetry integration is still being verified.
- Host CPU and memory utilisation are not part of the verified baseline.
- Complete discrepancy detection and link-utilisation thresholding are pending.
- Advanced alert handling and controller-driven mitigation are pending.
- Performance evaluation has not yet been completed.

## 13. Future Enhancements

Potential extensions include:

- Completing multi-host telemetry integration.
- Implementing configurable link-utilisation thresholds.
- Adding congestion and link-failure detection.
- Implementing complete alert severity, suppression, and recovery handling.
- Adding controller-driven traffic management.
- Developing a consolidated monitoring dashboard.
- Evaluating detection accuracy, latency, and monitoring overhead.

## 14. Team

**Team 17**  
PES University  
SDN–Socket Programming Project

---

*This README describes the project architecture and implementation baseline. Features listed as planned or pending should not be interpreted as completed functionality.*
