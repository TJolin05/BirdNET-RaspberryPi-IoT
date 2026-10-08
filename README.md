# BirdNET Raspberry Pi IoT Monitoring System

A Raspberry Pi-based bird monitoring system integrating **BirdNET V2.4 edge AI inference, SQLite offline buffering, MQTT communication, Firebase Firestore, heartbeat monitoring, and automatic database cleanup**.

The project was developed as a research prototype for continuous bird identification and reliable IoT data transmission. Bird identification is performed locally on the Raspberry Pi, while detection events are stored and forwarded to a cloud database.

## 1. Project Overview

The system uses a USB microphone connected to a Raspberry Pi to continuously capture environmental audio.

A pre-trained BirdNET V2.4 model analyzes the audio locally to identify bird species. Detected bird events are stored in SQLite and transmitted through MQTT to Firebase Firestore.

The architecture is designed to support:

- Continuous bird species detection.
- Local edge AI inference.
- Bird-event grouping across audio windows.
- SQLite offline buffering.
- MQTT QoS 1 message delivery.
- Firestore application-level acknowledgement (ACK).
- Automatic retry of unconfirmed events.
- Raspberry Pi heartbeat monitoring.
- Automatic cleanup of delivered SQLite records.
- Future deployment across multiple Raspberry Pi nodes.

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
SQLite-to-MQTT Publisher
(QoS 1)
      |
      v
Mosquitto MQTT Broker
      |
      v
MQTT-to-Firestore Bridge
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

A separate heartbeat service publishes node-status messages, while a daily cleanup timer manages local database storage.

## 3. Hardware and Software

### Hardware

- Raspberry Pi running a 64-bit operating system
- USB microphone
- MicroSD card
- Wi-Fi or network connection
- Suitable power supply

### Software

| Component | Technology |
|---|---|
| Operating system | Raspberry Pi OS Lite (64-bit) |
| Programming language | Python 3 |
| Bird identification | BirdNET V2.4 |
| Inference | BirdNET Python API / LiteRT |
| Audio processing | NumPy, SoundDevice |
| Local storage | SQLite |
| Messaging | MQTT |
| MQTT client | Paho MQTT |
| MQTT broker | Mosquitto |
| Cloud database | Firebase Firestore |
| Service management | systemd |

## 4. BirdNET Edge AI Processing

The system performs bird identification directly on the Raspberry Pi using a pre-trained BirdNET V2.4 model.

### Main script

` scripts/streaming_ram_test_v3.py `

The streaming detector uses:

| Parameter | Original configuration |
|---|---|
| Sampling rate | 48,000 Hz |
| Audio channels | Mono |
| Processing window | 3 seconds |
| Confidence threshold | 0.50 |
| Window overlap | 0 seconds |
| Audio device | `DEVICE = 1` |
| Node ID | `birdnode2` |

Audio is processed in memory using a persistent BirdNET prediction session.

### Processing workflow

1. Capture environmental audio from the USB microphone.
2. Divide the audio into 3-second analysis windows.
3. Perform BirdNET inference locally.
4. Filter predictions using the configured Malaysian species list.
5. Group related detections into continuous events.
6. Store finalized events in SQLite.

### Event grouping

A bird may be detected repeatedly in consecutive audio windows.

The event-grouping mechanism combines related detections of the same species into a continuous event instead of storing every prediction as a separate occurrence.

The implementation allows one missed analysis window before an active event is finalized.

## 5. Malaysian Bird Species Configuration

The project includes a Malaysian bird species configuration file:

```text
config/malaysia_28_species.txt
```

This file is required by the original streaming detector.

The original BirdNode2 script expects the file at:

```text
/home/jolin/malaysia_28_species.txt
```

For deployment on another Raspberry Pi, either copy the species file to the expected location or update the `SPECIES_LIST` variable in `streaming_ram_test_v3.py`.

For example:

```bash
cp config/malaysia_28_species.txt ~/malaysia_28_species.txt
```

The script also references the BirdNET Analyzer taxonomy file:

```text
eBird_taxonomy_codes_2024E.json
```

The taxonomy file is expected from the installed BirdNET Analyzer package. Its path must be updated if the Python environment or package installation differs from the original deployment.

## 6. SQLite Offline Buffering

The SQLite database provides local storage for finalized bird-detection events.

### Main module

` scripts/birdnet_buffer.py `

This module handles:

- Database initialization.
- Event insertion.
- Event ID generation.
- Retrieval of pending events.
- Delivery attempt tracking.
- Updating event status after acknowledgement.

The original database location is:

```text
/home/jolin/bird_monitor_data/birdnet_buffer.db
```

### Delivery status

| Status | Meaning |
|---|---|
| `sent = 0` | Firestore storage has not yet been confirmed |
| `sent = 1` | Firestore storage has been confirmed by an application-level ACK |

The database uses SQLite WAL mode and includes a unique index on non-null event IDs to help prevent duplicate local event records.

### Offline behavior

If the network connection becomes unavailable, finalized detection events can remain stored in SQLite with `sent = 0`.

When communication becomes available again, the MQTT publisher can retry pending events.

This separates local bird detection from cloud communication and improves resilience during temporary connectivity interruptions.

## 7. MQTT Communication

MQTT is used to transmit bird-detection events between the Raspberry Pi and the Firebase bridge.

### Main scripts

- `scripts/sqlite_to_mqtt.py`
- `scripts/mqtt_to_firebase.py`

### MQTT components

| Component | Function |
|---|---|
| SQLite-to-MQTT publisher | Reads pending events and publishes them |
| Mosquitto broker | Routes MQTT messages |
| MQTT-to-Firestore bridge | Receives detections and stores them in Firestore |

### Detection topic

```text
birdnet/<node_id>/detections
```

Example:

```text
birdnet/birdnode2/detections
```

### ACK topic

```text
birdnet/<node_id>/acks
```

Example:

```text
birdnet/birdnode2/acks
```

### MQTT settings

The original BirdNode2 configuration uses:

```python
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_QOS = 1
```

`localhost` is appropriate when Mosquitto runs on the same Raspberry Pi.

If the broker is hosted on another device, the MQTT broker address must be updated.

## 8. MQTT QoS 1 and Application-Level ACK

The system uses two acknowledgement mechanisms.

### MQTT QoS 1

MQTT QoS 1 provides at-least-once delivery at the MQTT protocol layer.

It confirms MQTT message delivery according to the protocol but does not guarantee successful storage in Firebase Firestore.

### Application-Level ACK

To confirm cloud storage, the system implements an additional application-level acknowledgement mechanism.

```text
SQLite Event (sent = 0)
          |
          v
MQTT Publish (QoS 1)
          |
          v
MQTT-to-Firestore Bridge
          |
          v
Firestore Write
          |
          v
Application ACK
          |
          v
SQLite Event (sent = 1)
```

### ACK workflow

1. A finalized event is stored in SQLite.
2. The SQLite publisher transmits the event through MQTT.
3. The Firebase bridge receives the message.
4. The bridge writes the event to Firestore.
5. After successful storage, the bridge publishes an application-level ACK.
6. The publisher receives and matches the ACK.
7. The SQLite event is marked as delivered.

If the ACK is not received, the event remains pending and can be retried.

The original publisher uses a 30-second ACK timeout.

Because QoS 1 and retries may produce duplicate messages, event identification and duplicate handling remain important.

## 9. Firebase Firestore Integration

### Main script

` scripts/mqtt_to_firebase.py `

The Firebase bridge subscribes to MQTT detection messages and writes received events to Firestore.

The bridge also publishes application-level ACK messages after successful storage.

### Firebase credentials

The original script references:

```text
/home/jolin/firebase-key.json
```

This file contains Firebase service-account credentials and **must not be uploaded to GitHub**.

Researchers deploying the project must supply their own authorized Firebase credentials or receive appropriate access to the existing Firebase project.

The credential path should be updated in `mqtt_to_firebase.py` for the target deployment.

## 10. Node Heartbeat Monitoring

### Main script

` scripts/node_heartbeat.py `

The heartbeat service periodically publishes node-status information through MQTT.

The original heartbeat interval is 120 seconds.

### Heartbeat topic

```text
birdnet/<node_id>/heartbeat
```

Example:

```text
birdnet/birdnode2/heartbeat
```

Heartbeat messages can be used to track node activity and support future monitoring dashboards.

They can also help distinguish periods without bird detections from periods when a Raspberry Pi has stopped reporting.

## 11. Automatic SQLite Cleanup

Continuous bird monitoring can cause the SQLite database to grow over time.

The project includes a daily cleanup mechanism to manage local storage.

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
| `sent = 1`, older than 24 hours based on `sent_at` | Deleted |
| `sent = 1`, within 24 hours | Retained |
| `sent = 1`, `sent_at` is NULL | Retained |

Only successfully delivered records older than the configured retention period are eligible for deletion.

The cleanup script also performs a SQLite integrity check and requests a passive WAL checkpoint.

### Scheduling

The systemd timer uses:

```ini
[Timer]
OnCalendar=daily
Persistent=true
```

The cleanup is scheduled daily.

### Check cleanup status

```bash
systemctl status birdnet-cleanup.timer
```

### View cleanup logs

```bash
sudo journalctl -u birdnet-cleanup.service -n 30 --no-pager
```

The cleanup service uses `Type=oneshot`, so it normally exits after completing its task.

## 12. Repository Structure

```text
BirdNET-RaspberryPi-IoT/
|
|-- README.md
|-- .gitignore
|
|-- config/
|   |-- malaysia_28_species.txt
|
|-- scripts/
|   |-- streaming_ram_test_v3.py
|   |-- birdnet_buffer.py
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

### Python files

| File | Purpose |
|---|---|
| `streaming_ram_test_v3.py` | Continuous audio capture and BirdNET detection |
| `birdnet_buffer.py` | SQLite database management |
| `sqlite_to_mqtt.py` | MQTT event publishing and ACK handling |
| `mqtt_to_firebase.py` | MQTT subscription and Firestore integration |
| `node_heartbeat.py` | Node heartbeat publishing |
| `birdnet_cleanup.py` | Automatic database cleanup |

## 13. Deployment Configuration Notes

This repository preserves the original BirdNode2 implementation developed using the Raspberry Pi username `jolin`.

Some paths and configuration values are specific to that deployment.

### Settings to update on another Raspberry Pi

| Setting | Original configuration |
|---|---|
| Username | `jolin` |
| Node ID | `birdnode2` |
| Home directory | `/home/jolin/` |
| SQLite directory | `/home/jolin/bird_monitor_data/` |
| Species list | `/home/jolin/malaysia_28_species.txt` |
| Firebase credentials | `/home/jolin/firebase-key.json` |
| MQTT broker | `localhost` |
| MQTT port | `1883` |
| BirdNET Python environment | `/home/jolin/birdnet-api-env/` |
| Other Python environment | `/home/jolin/birdnet-env/` |
| Microphone device | `DEVICE = 1` |

The streaming detector also contains deployment-specific latitude and longitude coordinates. These must be updated to match the new monitoring location.

The taxonomy file path references the original Python 3.13 environment and may need adjustment.

### Important

The repository provides the original implementation for reference and further research.

It is not a fully automated installation package. Researchers must configure the hardware, Python dependencies, paths, Firebase credentials, MQTT broker and systemd services before deployment.

## 14. Basic Deployment Guide

### Step 1 — Clone the repository

```bash
git clone https://github.com/TJolin05/BirdNET-RaspberryPi-IoT.git
cd BirdNET-RaspberryPi-IoT
```

Access permission is required if the repository is private.

### Step 2 — Install basic system packages

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv mosquitto mosquitto-clients ffmpeg
```

Additional audio dependencies and Python packages are required.

### Step 3 — Configure Python environments

Create Python virtual environments compatible with the selected BirdNET and Firebase dependencies.

The original implementation uses separate environments for BirdNET inference and other services.

Install the required libraries for the corresponding scripts, including BirdNET, NumPy, SoundDevice, Paho MQTT and Firebase Admin SDK.

Exact dependency versions should be verified against the original tested environments before attempting full reproduction.

### Step 4 — Configure required files

Copy the Malaysian species list to the location expected by the streaming script:

```bash
cp config/malaysia_28_species.txt ~/malaysia_28_species.txt
```

Update the following settings as required:

- Python virtual environment paths.
- SQLite database directory.
- MQTT broker address.
- Firebase credential location.
- BirdNET taxonomy file path.
- Microphone device index.
- Node identifier.
- Geographic coordinates.

### Step 5 — Configure systemd services

The original systemd files use absolute paths under `/home/jolin/`.

Before installing them, update each service file to match the target Raspberry Pi username, Python environments and script locations.

After configuring and deploying the scripts to their intended paths, install the service files:

```bash
sudo cp services/*.service /etc/systemd/system/
sudo cp services/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

### Step 6 — Enable services

After all configuration and dependencies are ready:

```bash
sudo systemctl enable --now mosquitto.service
sudo systemctl enable --now birdnet-stream.service
sudo systemctl enable --now sqlite-to-mqtt.service
sudo systemctl enable --now mqtt-bridge.service
sudo systemctl enable --now node-heartbeat.service
sudo systemctl enable --now birdnet-cleanup.timer
```

### Step 7 — Check service status

```bash
systemctl status birdnet-stream.service
systemctl status sqlite-to-mqtt.service
systemctl status mqtt-bridge.service
systemctl status node-heartbeat.service
systemctl status birdnet-cleanup.timer
```

### Step 8 — View logs

```bash
sudo journalctl -u birdnet-stream.service -n 30 --no-pager
sudo journalctl -u sqlite-to-mqtt.service -n 30 --no-pager
sudo journalctl -u mqtt-bridge.service -n 30 --no-pager
sudo journalctl -u node-heartbeat.service -n 30 --no-pager
sudo journalctl -u birdnet-cleanup.service -n 30 --no-pager
```

## 15. Reliability and Network Recovery

The system is designed to separate bird detection from cloud communication.

### Normal operation

```text
Bird Detection
      |
      v
SQLite (sent = 0)
      |
      v
MQTT Publish
      |
      v
Firestore Storage
      |
      v
Application ACK
      |
      v
SQLite (sent = 1)
```

### Network interruption

When cloud communication is unavailable, pending events remain in SQLite.

The publisher can retry these events after connectivity is restored.

### Database cleanup

Pending events are protected from age-based cleanup. Successfully delivered events are eligible for deletion after the configured retention period.

This combination supports offline buffering, acknowledged cloud delivery and controlled local storage growth.

## 16. Testing and Validation

The BirdNode2 implementation has been used to test:

- Local BirdNET inference.
- Continuous 3-second audio processing.
- Bird-event grouping.
- SQLite event buffering.
- MQTT QoS 1 publishing.
- Firestore integration.
- Application-level ACK handling.
- Pending-event retry.
- Heartbeat publishing.
- Daily SQLite cleanup.

The cleanup script has successfully deleted delivered records older than 24 hours while protecting pending records, with SQLite integrity verification.

Further testing is recommended for multi-node deployments, prolonged connectivity outages, unexpected power loss, duplicate handling and reproducible installation on a new Raspberry Pi.

## 17. Future Research

Potential extensions include:

### MQTT Payload Optimization

Evaluate ways to reduce MQTT message size while preserving the information required for bird monitoring.

Possible evaluation metrics include payload size, bandwidth consumption, transmission efficiency and scalability.

### Multi-Node Deployment

Deploy additional Raspberry Pi nodes using unique node identifiers and centralized MQTT subscriptions.

### Monitoring Dashboard

Develop a dashboard displaying bird detections, species statistics, node heartbeat status and monitoring activity.

### Reliability Evaluation

Evaluate retry performance, cloud delivery latency, database growth, network recovery and system behavior during extended offline operation.

## 18. Research Purpose

This repository provides the original BirdNode2 implementation of a Raspberry Pi-based bird monitoring system.

It demonstrates the integration of local BirdNET inference, SQLite buffering, MQTT communication, Firebase Firestore, application-level acknowledgement and automatic storage management.

The repository is intended to support documentation, further development and future research.
