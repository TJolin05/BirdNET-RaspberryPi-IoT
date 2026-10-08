# BirdNET Raspberry Pi IoT Monitoring System

A Raspberry Pi-based IoT bird monitoring system that integrates **BirdNET edge AI inference, SQLite offline buffering, MQTT communication, and Firebase Firestore cloud storage**.

The system continuously analyzes environmental audio to identify bird species, stores detection events locally, and transfers the results to a centralized cloud database. It is designed to support multiple Raspberry Pi nodes, unreliable network connections, and continuous monitoring.

## 1. Project Overview

This project implements an edge-based bird monitoring system using Raspberry Pi and BirdNET.

Instead of continuously uploading raw audio to the cloud, bird identification is performed locally on the Raspberry Pi using a pre-trained BirdNET model.

Detected bird events are stored in SQLite before being transmitted through MQTT to Firebase Firestore.

To improve reliability, the system uses:

- **BirdNET V2.4** for local bird species identification.
- **SQLite** for local detection storage and offline buffering.
- **MQTT QoS 1** for at-least-once MQTT message delivery.
- **Mosquitto** as the MQTT message broker.
- **Application-level ACK** to confirm successful Firestore storage.
- **Heartbeat monitoring** to track node activity.
- **Automatic SQLite cleanup** to manage local database storage.

## 2. System Architecture

```text
USB Microphone
      |
      v
Raspberry Pi
      |
      v
Continuous Audio Capture
(48 kHz, Mono)
      |
      v
BirdNET V2.4 Python API
(3-Second RAM Processing)
      |
      v
Species Filtering and Event Grouping
      |
      v
SQLite Local Database
(sent = 0)
      |
      v
sqlite_to_mqtt.py
MQTT Publisher (QoS 1)
      |
      v
Mosquitto MQTT Broker
      |
      v
mqtt_to_firebase.py
MQTT Subscriber / Firestore Bridge
      |
      v
Firebase Firestore
      |
      v
Application-Level ACK
      |
      v
SQLite Status Updated
(sent = 1)
```

A separate heartbeat service periodically publishes node status messages through MQTT.

A systemd cleanup timer periodically removes successfully delivered SQLite records older than 24 hours.

## 3. Hardware and Software

### Hardware

- Raspberry Pi running a 64-bit operating system
- USB microphone
- MicroSD card
- Wi-Fi or network connection
- Power supply

### Software

| Component | Technology |
|---|---|
| Operating system | Raspberry Pi OS Lite (64-bit) |
| Programming language | Python 3 |
| Bird identification | BirdNET V2.4 |
| Model execution | LiteRT / TensorFlow Lite |
| Local database | SQLite |
| Messaging protocol | MQTT |
| MQTT broker | Eclipse Mosquitto |
| Cloud database | Firebase Firestore |
| Service management | systemd |

## 4. BirdNET Edge AI Processing

The Raspberry Pi continuously captures environmental audio using a USB microphone.

Audio is sampled at **48 kHz in mono** and processed in **3-second windows**.

Bird identification is performed using the pre-trained BirdNET V2.4 model through its Python API.

The model runs locally on the Raspberry Pi, so Internet connectivity is not required for BirdNET inference.

### Main implementation

`script: scripts/streaming_ram_test_v3.py`

The implementation uses a persistent BirdNET prediction session and processes audio directly in memory rather than requiring a separate WAV file for every analysis window.

### Processing stages

1. Capture environmental audio.
2. Process audio in 3-second windows.
3. Perform BirdNET inference locally.
4. Filter predictions using the selected Malaysian bird species list.
5. Group related detections into continuous bird events.
6. Store finalized events in SQLite.

### Event grouping

The same bird may be detected repeatedly across consecutive audio windows.

Event grouping combines related detections into one continuous event instead of treating every 3-second prediction as an independent bird occurrence.

For example, 11 consecutive detections may be grouped into one 33-second bird event.

## 5. SQLite Offline Buffering

SQLite acts as the local storage layer between BirdNET detection and MQTT communication.

Each finalized bird event is stored locally before transmission.

The database uses a delivery-status field to track whether successful cloud storage has been confirmed.

| Status | Meaning |
|---|---|
| `sent = 0` | Firestore storage has not yet been confirmed |
| `sent = 1` | A matching Firestore ACK has confirmed successful storage |

If Internet connectivity is unavailable, BirdNET can continue processing locally and events remain buffered in SQLite.

When connectivity returns, pending events can be retried.

This prevents temporary network failures from immediately causing loss of finalized detection events.

## 6. MQTT Communication

MQTT stands for Message Queuing Telemetry Transport.

It is a lightweight publish-subscribe messaging protocol commonly used in IoT applications.

The project uses MQTT as the communication layer between the Raspberry Pi and the Firestore bridge.

### MQTT components

| Component | Implementation | Role |
|---|---|---|
| Publisher | `sqlite_to_mqtt.py` | Reads pending SQLite events and publishes detection messages |
| Broker | Mosquitto | Receives and routes MQTT messages |
| Subscriber / Bridge | `mqtt_to_firebase.py` | Receives detection messages and writes them to Firestore |

### MQTT topic structure

Detection messages:

```text
birdnet/<node_id>/detections
```

Application-level acknowledgements:

```text
birdnet/<node_id>/acks
```

Heartbeat messages:

```text
birdnet/<node_id>/heartbeat
```

Example for BirdNode2:

```text
birdnet/birdnode2/detections
birdnet/birdnode2/acks
birdnet/birdnode2/heartbeat
```

The node ID identifies the Raspberry Pi that generated each message.

### Multi-node support

The topic structure is designed to support multiple Raspberry Pi nodes.

A subscriber can use a single-level wildcard subscription:

```text
birdnet/+/detections
```

This allows the subscriber to receive detection messages from different node IDs without requiring a separate subscriber implementation for every Raspberry Pi.

The current implementation has been verified on BirdNode2. Deployment across additional nodes requires configuring each node and validating the complete system.

## 7. MQTT Quality of Service (QoS)

Detection messages use **MQTT QoS 1**, which provides at-least-once delivery at the MQTT communication layer.

QoS 1 uses an acknowledgement mechanism to confirm MQTT message delivery.

If delivery is not acknowledged, retransmission may occur depending on the MQTT client and session behavior.

Because retransmission is possible, duplicate messages may also occur.

### Why QoS 1?

- QoS 0 provides no acknowledged delivery.
- QoS 1 provides at-least-once delivery with moderate protocol overhead.
- QoS 2 provides exactly-once MQTT delivery semantics but requires a more complex handshake.

QoS 1 was selected to balance delivery reliability and communication overhead.

**Important:** MQTT QoS 1 does not confirm that a message has been successfully stored in Firestore. A separate application-level acknowledgement is used for this purpose.

## 8. Firestore Application-Level ACK

The system implements an additional application-level ACK mechanism to confirm successful cloud storage.

### Delivery workflow

```text
SQLite Event
(sent = 0)
      |
      v
MQTT Publish (QoS 1)
      |
      v
Mosquitto Broker
      |
      v
Firestore Bridge
      |
      v
Successful Firestore Write
      |
      v
Publish Application ACK
      |
      v
Raspberry Pi Receives ACK
      |
      v
SQLite Event Updated
(sent = 1)
```

### ACK behavior

1. A finalized event is stored in SQLite with `sent = 0`.
2. The publisher sends the event through MQTT.
3. The Firestore bridge receives the detection message.
4. The bridge attempts to store the event in Firestore.
5. After successful storage, an application-level ACK is published.
6. The Raspberry Pi receives and matches the ACK.
7. SQLite updates the event to `sent = 1`.

If a valid ACK is not received, the event remains pending and can be retried.

This provides two distinct levels of reliability:

- **MQTT QoS 1:** Reliability of MQTT message delivery.
- **Application-level ACK:** Confirmation of successful Firestore storage.

Since QoS 1 and application-level retries can produce repeated messages, receiver-side event identification and duplicate handling are important.

## 9. Heartbeat Monitoring

The system includes a separate heartbeat publisher:

`script: scripts/node_heartbeat.py`

The heartbeat service periodically publishes node-status messages through MQTT.

For BirdNode2:

```text
birdnet/birdnode2/heartbeat
```

The MQTT-to-Firestore bridge processes heartbeat messages and updates the corresponding node-status information.

Firestore stores the latest heartbeat and boot-related status information for the node.

### Purpose

- Track when a Raspberry Pi last reported.
- Distinguish a quiet environment from a node that may have stopped reporting.
- Support identification of node restarts.
- Provide information for future node-health dashboards.

A monitoring application can compare the latest heartbeat timestamp against the expected reporting interval to identify potentially inactive nodes.

## 10. Automatic SQLite Cleanup

Continuous monitoring can cause the SQLite database to grow over time.

To manage local storage, the system includes an automatic cleanup mechanism.

### Implementation files

```text
scripts/birdnet_cleanup.py
services/birdnet-cleanup.service
services/birdnet-cleanup.timer
```

### Cleanup rules

| SQLite record | Action |
|---|---|
| `sent = 0` | Protected from age-based deletion |
| `sent = 1`, `sent_at` older than 24 hours | Deleted |
| `sent = 1`, `sent_at` within 24 hours | Retained |
| `sent = 1`, `sent_at` missing | Retained |

Only successfully delivered events older than the retention period are eligible for deletion.

The cleanup script also performs a SQLite integrity check and requests a passive WAL checkpoint.

### Cleanup scheduling

The cleanup is triggered by a systemd timer.

```ini
[Timer]
OnCalendar=daily
Persistent=true
```

The timer is configured to run daily and can catch up on missed scheduled executions after activation.

### Verification

Check the cleanup timer:

```bash
systemctl status birdnet-cleanup.timer
```

Check the cleanup service:

```bash
systemctl status birdnet-cleanup.service
```

View recent cleanup logs:

```bash
sudo journalctl -u birdnet-cleanup.service -n 30 --no-pager
```

A successful oneshot cleanup service may display `inactive (dead)` after completing its execution. This is expected behavior.

### Database path

The current implementation uses:

```text
/home/jolin/bird_monitor_data/birdnet_buffer.db
```

This path must be adjusted when deploying the system under another username or directory structure.

## 11. Project Files

```text
BirdNET-RaspberryPi-IoT/
|
|-- README.md
|-- .gitignore
|
|-- scripts/
|   |-- streaming_ram_test_v3.py
|   |-- sqlite_to_mqtt.py
|   |-- mqtt_to_firebase.py
|   |-- node_heartbeat.py
|   |-- birdnet_cleanup.py
|
|-- services/
|   |-- birdnet-stream.service
|   |-- sqlite-to-mqtt.service
|   |-- mqtt-bridge.service
|   |-- node-heartbeat.service
|   |-- birdnet-cleanup.service
|   |-- birdnet-cleanup.timer
|
|-- docs/
```

### Python scripts

| Script | Purpose |
|---|---|
| `streaming_ram_test_v3.py` | Continuous audio capture, BirdNET inference and event processing |
| `sqlite_to_mqtt.py` | SQLite event publishing and ACK handling |
| `mqtt_to_firebase.py` | MQTT subscription, Firestore storage and acknowledgement publishing |
| `node_heartbeat.py` | Periodic node-status publishing |
| `birdnet_cleanup.py` | Automatic SQLite record cleanup |

### Systemd units

| Unit | Purpose |
|---|---|
| `birdnet-stream.service` | Runs continuous BirdNET processing |
| `sqlite-to-mqtt.service` | Runs the SQLite-to-MQTT publisher |
| `mqtt-bridge.service` | Runs the MQTT-to-Firestore bridge |
| `node-heartbeat.service` | Runs heartbeat publishing |
| `birdnet-cleanup.service` | Executes the cleanup script |
| `birdnet-cleanup.timer` | Schedules daily cleanup |

Mosquitto is managed separately through `mosquitto.service`.

## 12. Deployment on a Raspberry Pi

The following is a deployment outline for researchers extending the project. It is not a fully automated installer.

### Step 1 — Clone the repository

```bash
git clone https://github.com/TJolin05/BirdNET-RaspberryPi-IoT.git
cd BirdNET-RaspberryPi-IoT
```

For a private repository, GitHub authentication and repository access are required.

### Step 2 — Install system dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip mosquitto mosquitto-clients ffmpeg
```

Additional audio libraries, Python packages, and system dependencies may be required for the BirdNET model and microphone.

### Step 3 — Configure the Python environments

The original BirdNode2 installation uses separate Python virtual environments:

```text
/home/jolin/birdnet-api-env
/home/jolin/birdnet-env
```

The BirdNET streaming and SQLite-to-MQTT services use the first environment.

The Firestore bridge and heartbeat services use the second environment.

When reproducing the project, create suitable environments and install the dependencies required by the corresponding scripts.

The exact package versions should be documented from the tested environment before claiming a reproducible installation.

### Step 4 — Configure the system

Before starting the services:

1. Configure the USB microphone and confirm audio capture works.
2. Configure BirdNET and any required species-list files.
3. Configure the SQLite database path and schema.
4. Configure Mosquitto and the MQTT connection settings.
5. Configure Firebase Firestore and its service-account credentials securely.
6. Set a unique node ID for each Raspberry Pi.
7. Adjust Python executable paths and working directories in the systemd files.

Do not commit Firebase service-account keys, Wi-Fi passwords, MQTT credentials, or other secrets to the repository.

### Step 5 — Install the systemd units

After updating the service paths and configuration for the target device:

```bash
sudo cp services/*.service /etc/systemd/system/
sudo cp services/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

The service files refer to scripts under `/home/jolin/`. These paths must be changed or the scripts deployed to the expected locations before starting the services.

### Step 6 — Enable the services

Once the Python environments, database, configuration and credentials are ready:

```bash
sudo systemctl enable --now mosquitto.service
sudo systemctl enable --now birdnet-stream.service
sudo systemctl enable --now sqlite-to-mqtt.service
sudo systemctl enable --now mqtt-bridge.service
sudo systemctl enable --now node-heartbeat.service
sudo systemctl enable --now birdnet-cleanup.timer
```

The cleanup service itself is triggered by the timer and does not need to run continuously.

### Step 7 — Check service status

```bash
systemctl status birdnet-stream.service
systemctl status sqlite-to-mqtt.service
systemctl status mqtt-bridge.service
systemctl status node-heartbeat.service
systemctl status birdnet-cleanup.timer
systemctl status mosquitto.service
```

### Step 8 — View logs

BirdNET inference:

```bash
sudo journalctl -u birdnet-stream.service -f
```

MQTT publisher and ACK handling:

```bash
sudo journalctl -u sqlite-to-mqtt.service -f
```

MQTT-to-Firestore bridge:

```bash
sudo journalctl -u mqtt-bridge.service -f
```

Heartbeat monitoring:

```bash
sudo journalctl -u node-heartbeat.service -f
```

SQLite cleanup:

```bash
sudo journalctl -u birdnet-cleanup.service -n 30 --no-pager
```

## 13. Network Failure and Recovery

The system is designed to preserve finalized detection events during temporary Internet outages.

### Normal operation

```text
Bird Detection
    |
    v
SQLite sent=0
    |
    v
MQTT Publish
    |
    v
Firestore Write
    |
    v
Application ACK
    |
    v
SQLite sent=1
```

### During an Internet outage

```text
Bird Detection
    |
    v
SQLite sent=0
    |
    v
Event Remains Pending
```

BirdNET inference and local event storage can continue while cloud connectivity is unavailable.

### After reconnection

```text
Pending SQLite Event
    |
    v
MQTT Retry
    |
    v
Firestore Write
    |
    v
Application ACK
    |
    v
SQLite sent=1
```

The ACK mechanism prevents the publisher from marking an event as delivered before receiving confirmation of successful Firestore storage.

## 14. Testing and Validation

The BirdNode2 implementation has been used to test the following behaviors:

- Continuous local BirdNET inference.
- Three-second audio processing.
- Bird-event grouping.
- SQLite event buffering.
- MQTT detection publishing.
- Firestore event storage.
- Application-level ACK handling.
- Recovery of pending events after an Internet outage.
- Heartbeat publishing.
- Automatic SQLite cleanup.

The cleanup service has successfully removed delivered records older than 24 hours while protecting pending events.

Additional testing is recommended for full multi-node deployment, prolonged network outages, duplicate delivery handling, and system recovery after unexpected power loss.

## 15. Future Work

### MQTT Payload Optimization

Future work can investigate reducing the amount of information transmitted in each MQTT detection message.

The current payload can be compared with an optimized format containing only the fields required by downstream applications.

Potential evaluation metrics include:

- MQTT payload size.
- Bandwidth usage.
- Message transmission efficiency.
- Cloud storage usage.
- Performance as the number of Raspberry Pi nodes increases.

### Multi-Node Validation

Deploy the system across additional Raspberry Pi nodes and evaluate simultaneous publishing, topic-based routing, network recovery, and centralized data collection.

### Monitoring and Reliability

Further improvements may include automated offline-node detection, delivery latency measurements, more extensive retry testing, and additional monitoring of system resource usage.

## 16. Research and Development Notes

This repository documents the BirdNode2 implementation of the BirdNET IoT monitoring pipeline.

Researchers extending the project should review:

- Hardware-specific microphone settings.
- Raspberry Pi OS and Python versions.
- BirdNET model and dependency versions.
- SQLite database schema.
- MQTT broker configuration.
- Firestore collection structure.
- Credentials and authentication configuration.
- Systemd service paths.
- Species-list configuration.

The current repository contains the core implementation scripts and systemd definitions. Environment-specific setup and additional supporting files may be required to reproduce the complete deployment on another device.

## 17. Project Purpose

This project demonstrates how edge AI, local database buffering, MQTT messaging and cloud storage can be integrated into a Raspberry Pi-based bird monitoring system.

The main objective is to provide a practical foundation for continuous bird detection, reliable IoT communication, centralized data collection and future research development.
