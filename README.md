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
| Programming language | Python 3.13 |
| Bird identification model | BirdNET V2.4 |
| BirdNET Python API | `birdnet 1.1.1` |
| BirdNET Analyzer | `birdnet-analyzer 2.4.0` |
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

Although the filename contains `28`, the current file contains **60 species entries**. The original filename is retained for compatibility with the existing BirdNode2 implementation.

The original streaming script expects the file at:

```text
/home/jolin/malaysia_28_species.txt
```

For deployment on another Raspberry Pi, either copy the species file to the expected location or update the `SPECIES_LIST` variable in `streaming_ram_test_v3.py`.

For example, after cloning the repository:

```bash
cp config/malaysia_28_species.txt ~/malaysia_28_species.txt
```

The streaming script also references the BirdNET Analyzer taxonomy file:

```text
eBird_taxonomy_codes_2024E.json
```

The taxonomy file is provided by the installed BirdNET Analyzer package. Its path must be updated if the Python environment or package installation differs from the original deployment.

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

### Multi-node support

The topic structure can support multiple Raspberry Pi nodes using unique node identifiers.

For example, a subscriber can use:

```text
birdnet/+/detections
```

This allows one MQTT subscriber to receive detection messages from multiple nodes.

The original implementation has been tested on BirdNode2. Additional validation is required for larger multi-node deployments.

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

The MQTT-to-Firestore bridge can use heartbeat messages to update node-status information in Firestore.

Heartbeat data supports future monitoring dashboards and helps distinguish periods without bird detections from periods when a Raspberry Pi is not reporting.

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
|-- requirements-api.txt
|-- requirements-services.txt
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

### Dependency files

| File | Purpose |
|---|---|
| `requirements-api.txt` | Verified direct dependencies for BirdNET streaming and SQLite-to-MQTT |
| `requirements-services.txt` | Verified dependencies for Firestore, heartbeat and BirdNET Analyzer |

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

Additional audio dependencies and Python packages may be required.

### Step 3 — Configure Python environments

The original BirdNode2 implementation uses Python 3.13 with two separate virtual environments.

**Environment 1: BirdNET API (`birdnet-api-env`)**

This environment is used by:

- `streaming_ram_test_v3.py`
- `sqlite_to_mqtt.py`

The verified direct dependencies are:

| Package | Version |
|---|---|
| `birdnet` | 1.1.1 |
| `numpy` | 2.5.3 |
| `sounddevice` | 0.5.6 |
| `paho-mqtt` | 2.1.0 |

These are recorded in `requirements-api.txt`.

Create and activate the virtual environment:

```bash
python3 -m venv ~/birdnet-api-env
source ~/birdnet-api-env/bin/activate
```

Install the dependencies:

```bash
python -m pip install -r requirements-api.txt
```

Deactivate when finished:

```bash
deactivate
```

**Environment 2: BirdNET Services (`birdnet-env`)**

This environment is used by:

- `mqtt_to_firebase.py`
- `node_heartbeat.py`

It also contains BirdNET Analyzer, which provides the taxonomy JSON file referenced by the streaming detector.

The verified packages are:

| Package | Version |
|---|---|
| `firebase-admin` | 7.5.0 |
| `paho-mqtt` | 2.1.0 |
| `birdnet-analyzer` | 2.4.0 |

These are recorded in `requirements-services.txt`.

Create and activate the second virtual environment:

```bash
python3 -m venv ~/birdnet-env
source ~/birdnet-env/bin/activate
```

Install the dependencies:

```bash
python -m pip install -r requirements-services.txt
```

Deactivate when finished:

```bash
deactivate
```

**Note:** These versions were recorded from the original BirdNode2 installation. The installation commands are intended for a new deployment, not for modifying the existing working environments. Python version, operating-system packages, processor architecture and transitive dependencies may affect compatibility.

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

Verify that the taxonomy JSON file is available in the installed BirdNET Analyzer package and update the streaming script if necessary.

### Step 5 — Configure systemd services

The original systemd files use absolute paths under `/home/jolin/`.

Before installing them, update each service file to match the target Raspberry Pi username, Python environments and script locations.

The original service files expect the Python scripts to be deployed directly under the configured user's home directory, rather than executed from the repository's `scripts/` folder.

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
systemctl status mosquitto.service
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

## 19. Multi-Node Firestore Deployment

The BirdNET IoT architecture is designed to support multiple Raspberry Pi monitoring nodes contributing bird-detection records to a single Firebase Firestore database.

Each Raspberry Pi performs local bird detection and maintains its own SQLite buffer. Detection events are transmitted through MQTT to a central MQTT-to-Firestore bridge, allowing researchers to collect and analyze detections from multiple monitoring locations.

### 19.1 Multi-Node Architecture

```text
BirdNode2 -- SQLite -- MQTT --+
                              |
BirdNode3 -- SQLite -- MQTT --+-- Central MQTT Broker
                              |           |
BirdNode4 -- SQLite -- MQTT --+           |
                                          v
                               MQTT-to-Firestore Bridge
                                          |
                                          v
                               One Firebase Firestore
                                          |
                                          v
                              Multi-Node Research Dashboard
```

The diagram represents the intended shared-broker architecture. Network connectivity and access to the central broker must be configured separately.

### 19.2 Unique Node Identification

Each Raspberry Pi must use a unique node identifier.

Examples:

```python
NODE_ID = "birdnode2"
NODE_ID = "birdnode3"
NODE_ID = "birdnode4"
```

The identifier must be configured consistently across the relevant scripts on each Raspberry Pi.

Each detection record should retain its originating `node_id` so that researchers can distinguish data from different monitoring locations.

### 19.3 MQTT Broker Configuration

The original BirdNode2 configuration uses:

```python
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
```

This connects to a broker running on the same Raspberry Pi.

For multiple nodes using one central broker, the participating nodes must connect to a reachable shared MQTT broker.

Example:

```python
MQTT_BROKER = "192.168.1.100"
MQTT_PORT = 1883
```

The IP address is an example only and must be replaced with the actual broker address.

Remote MQTT connections require appropriate network routing, broker listener configuration, authentication, and access controls. An unsecured MQTT port should not be exposed directly to the public internet.

### 19.4 MQTT Topic Structure

Each Raspberry Pi publishes detections using its unique node identifier.

Examples:

```text
birdnet/birdnode2/detections
birdnet/birdnode3/detections
birdnet/birdnode4/detections
```

The central MQTT-to-Firestore bridge can subscribe to:

```text
birdnet/+/detections
```

The `+` wildcard matches one MQTT topic level, allowing one bridge to receive detection messages from multiple nodes.

Application-level acknowledgements use node-specific topics:

```text
birdnet/birdnode2/acks
birdnet/birdnode3/acks
birdnet/birdnode4/acks
```

This enables acknowledgements to be directed to the appropriate originating node, provided the bridge and publisher are configured consistently.

### 19.5 Centralized Firebase Firestore

All participating nodes can contribute detection records to the same Firebase project and Firestore database.

Each record should preserve:

- `node_id` — Originating Raspberry Pi.
- `species_code` — Bird species identifier.
- `confidence` — BirdNET prediction confidence.
- `timestamp` — Detection time.
- `event_id` — Identifier used for event tracking and duplicate handling.

The exact Firestore field names and document structure should follow the deployed bridge implementation.

Researchers can filter and aggregate records by node identifier, species and detection time.

Each Raspberry Pi does not require its own Firebase service-account credential when a single authorized central bridge performs the Firestore writes.

### 19.6 Offline Buffering and ACK Handling

Each Raspberry Pi maintains its own SQLite database.

The local event-delivery workflow is:

1. BirdNET detects and finalizes a bird event.
2. The event is stored in the local SQLite database.
3. The publisher sends the event to the central MQTT broker.
4. The central bridge writes the event to Firestore.
5. After successful storage, the bridge publishes an application-level ACK.
6. The originating Raspberry Pi receives the ACK.
7. The matching local SQLite event is marked as delivered.

If an ACK is not received, the event remains pending and may be retried.

MQTT QoS 1 provides at-least-once message delivery, so duplicate handling remains important. Event identifiers should be unique across nodes, and Firestore writes should handle repeated deliveries safely.

### 19.7 Adding Another Raspberry Pi Node

To integrate another Raspberry Pi into the shared monitoring system:

1. Install and configure the required BirdNET detection, SQLite and MQTT publisher components.
2. Assign a unique `NODE_ID`.
3. Configure the microphone, species list and monitoring coordinates.
4. Set the MQTT broker address to the reachable central broker.
5. Ensure the publisher subscribes to the correct node-specific ACK topic.
6. Configure network access and MQTT authentication.
7. Start the appropriate monitoring and publishing services.
8. Verify that the central bridge receives the new node's detections.
9. Confirm that records appear in Firestore with the correct `node_id`.
10. Verify that successful Firestore writes generate ACK messages and update the originating node's SQLite delivery status.

### 19.8 Deployment and Validation Notes

The repository preserves the original BirdNode2 configuration and scripts. Multi-node deployment requires additional configuration on each Raspberry Pi and the central MQTT infrastructure.

The architecture supports centralized collection, but the README does not establish that every multi-node scenario has been experimentally validated.

Before research deployment, verify connectivity, event identifiers, ACK routing, Firestore record structure, and offline recovery for each participating node.
