#!/usr/bin/env python3

import json
import uuid
import sys
import time

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import paho.mqtt.client as mqtt
import firebase_admin

from firebase_admin import credentials, firestore


# Make print() output appear immediately in systemd journal
sys.stdout.reconfigure(line_buffering=True)


# ============================================================
# Firebase
# ============================================================

FIREBASE_KEY = "/home/jolin/firebase-key.json"

cred = credentials.Certificate(
    FIREBASE_KEY
)

firebase_admin.initialize_app(
    cred
)

db = firestore.client()


# ============================================================
# MQTT Configuration
# ============================================================

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_QOS = 1

# Bird detection messages
DETECTION_TOPIC = "birdnet/+/detections"

# Raspberry Pi heartbeat messages
HEARTBEAT_TOPIC = "birdnet/+/heartbeat"

# ACK will be published to:
# birdnet/<node_id>/acks


# ============================================================
# Node Status Configuration
# ============================================================

NODE_STATUS_COLLECTION = "node_status"

# Heartbeat is sent every 120 seconds.
# More than 300 seconds without a successfully stored
# heartbeat is treated as an interruption/recovery condition.
OFFLINE_THRESHOLD_SECONDS = 300

# Cache the previous state so Firestore does not need to
# be read every 2 minutes.
node_status_cache = {}


# ============================================================
# Firestore Retry Configuration
# ============================================================

MAX_FIRESTORE_RETRIES = 5
INITIAL_RETRY_DELAY = 2


# ============================================================
# MQTT Callbacks
# ============================================================

def on_connect(
    client,
    userdata,
    flags,
    reason_code,
    properties
):

    if reason_code == 0:

        print(
            "[MQTT] Connected to local broker."
        )

        # ----------------------------------------------------
        # Subscribe to bird detections
        # ----------------------------------------------------

        print(
            f"[MQTT] Subscribing to: "
            f"{DETECTION_TOPIC}"
        )

        client.subscribe(
            DETECTION_TOPIC,
            qos=MQTT_QOS
        )

        # ----------------------------------------------------
        # Subscribe to Raspberry Pi heartbeat
        # ----------------------------------------------------

        print(
            f"[MQTT] Subscribing to: "
            f"{HEARTBEAT_TOPIC}"
        )

        client.subscribe(
            HEARTBEAT_TOPIC,
            qos=MQTT_QOS
        )

    else:

        print(
            f"[MQTT] Connection failed: "
            f"{reason_code}"
        )


# ============================================================
# Publish Firestore ACK
# ============================================================

def publish_ack(
    client,
    node_id,
    event_id,
    local_event_id,
    local_detection_id
):

    ack_topic = (
        f"birdnet/{node_id}/acks"
    )

    ack_payload = {
        "status": "saved",
        "event_id": event_id,
        "local_event_id": local_event_id,
        "local_detection_id": local_detection_id,
        "node_id": node_id,
        "saved_at": (
            datetime.now(
                ZoneInfo("Asia/Kuala_Lumpur")
            ).isoformat()
        )
    }

    try:

        result = client.publish(
            ack_topic,
            json.dumps(
                ack_payload,
                ensure_ascii=False
            ),
            qos=MQTT_QOS,
            retain=False
        )

        # IMPORTANT:
        #
        # Do NOT call wait_for_publish() here.
        #
        # publish_ack() is called from the MQTT message
        # callback while bridge.loop_forever() is running.
        # Blocking here would prevent Paho from processing
        # the QoS 1 PUBACK until the callback returns.

        if result.rc == mqtt.MQTT_ERR_SUCCESS:

            print(
                "[ACK] Queued for MQTT delivery:"
            )

            print(
                f"  Topic: "
                f"{ack_topic}"
            )

            print(
                f"  Event ID: "
                f"{event_id}"
            )

            print(
                f"  Local detection ID: "
                f"{local_detection_id}"
            )

        else:

            print(
                "[ACK] MQTT publish request failed:"
            )

            print(
                f"  Event ID: "
                f"{event_id}"
            )

            print(
                f"  MQTT result code: "
                f"{result.rc}"
            )

    except Exception as e:

        print(
            f"[ACK] Publish error for "
            f"event {event_id}: {e}"
        )

# ============================================================
# Firestore Detection Write With Retry
# ============================================================

def save_to_firestore(
    event_id,
    firestore_data
):

    delay = INITIAL_RETRY_DELAY

    for attempt in range(
        1,
        MAX_FIRESTORE_RETRIES + 1
    ):

        try:

            db.collection(
                "detections"
            ).document(
                event_id
            ).set(
                firestore_data
            )

            return True

        except Exception as e:

            print(
                f"[FIREBASE] Write attempt "
                f"{attempt}/"
                f"{MAX_FIRESTORE_RETRIES} "
                f"failed: {e}"
            )

            if (
                attempt
                < MAX_FIRESTORE_RETRIES
            ):

                print(
                    f"[FIREBASE] Retrying in "
                    f"{delay} s..."
                )

                time.sleep(
                    delay
                )

                delay *= 2

    return False


# ============================================================
# Node Status - Previous State
# ============================================================

def get_previous_node_state(
    node_id
):

    # --------------------------------------------------------
    # Return cached state if this node has already been seen
    # since the bridge started.
    # --------------------------------------------------------

    if node_id in node_status_cache:

        return node_status_cache[
            node_id
        ]

    # --------------------------------------------------------
    # Otherwise read the existing Firestore document once.
    # --------------------------------------------------------

    doc_ref = (
        db
        .collection(
            NODE_STATUS_COLLECTION
        )
        .document(
            node_id
        )
    )

    snapshot = doc_ref.get()

    if snapshot.exists:

        stored = (
            snapshot.to_dict()
            or {}
        )

        state = {
            "boot_id":
                stored.get(
                    "boot_id"
                ),

            "last_heartbeat":
                stored.get(
                    "last_heartbeat"
                ),
        }

    else:

        state = {
            "boot_id": None,
            "last_heartbeat": None,
        }

    node_status_cache[
        node_id
    ] = state

    return state


# ============================================================
# Node Status - Heartbeat Handler
# ============================================================

def handle_heartbeat(
    data
):

    # --------------------------------------------------------
    # Validate node ID
    # --------------------------------------------------------

    node_id = str(
        data.get(
            "node_id",
            ""
        )
    ).strip()

    if not node_id:

        raise ValueError(
            "Heartbeat missing node_id"
        )

    # --------------------------------------------------------
    # Validate message type
    # --------------------------------------------------------

    message_type = str(
        data.get(
            "message_type",
            ""
        )
    ).strip()

    if message_type != "heartbeat":

        raise ValueError(
            "Invalid heartbeat message_type"
        )

    # --------------------------------------------------------
    # Read Linux boot ID
    # --------------------------------------------------------

    new_boot_id = str(
        data.get(
            "boot_id",
            ""
        )
    ).strip()

    if not new_boot_id:

        new_boot_id = "unknown"

    # --------------------------------------------------------
    # Load previous state
    # --------------------------------------------------------

    previous_state = (
        get_previous_node_state(
            node_id
        )
    )

    old_boot_id = (
        previous_state.get(
            "boot_id"
        )
    )

    old_last_heartbeat = (
        previous_state.get(
            "last_heartbeat"
        )
    )

    # --------------------------------------------------------
    # Current UTC time for interval calculation
    # --------------------------------------------------------

    now_utc = datetime.now(
        ZoneInfo("UTC")
    )

    # --------------------------------------------------------
    # Calculate time since last successfully stored heartbeat
    # --------------------------------------------------------

    gap_seconds = None

    if isinstance(
        old_last_heartbeat,
        datetime
    ):

        heartbeat_time = (
            old_last_heartbeat
        )

        if heartbeat_time.tzinfo is None:

            heartbeat_time = (
                heartbeat_time.replace(
                    tzinfo=ZoneInfo("UTC")
                )
            )

        gap_seconds = (
            now_utc
            - heartbeat_time.astimezone(
                ZoneInfo("UTC")
            )
        ).total_seconds()

    # --------------------------------------------------------
    # Fields updated on every successful heartbeat
    # --------------------------------------------------------

    update_data = {
        "node_id":
            node_id,

        "last_heartbeat":
            firestore.SERVER_TIMESTAMP,
    }

    if new_boot_id != "unknown":

        update_data[
            "boot_id"
        ] = new_boot_id

    # --------------------------------------------------------
    # Check whether Linux performed a new boot
    # --------------------------------------------------------

    boot_changed = (
        old_boot_id
        not in (
            None,
            "",
            "unknown",
        )
        and
        new_boot_id
        not in (
            None,
            "",
            "unknown",
        )
        and
        old_boot_id
        != new_boot_id
    )

    if boot_changed:

        update_data[
            "previous_boot_id"
        ] = old_boot_id

        update_data[
            "last_boot_change"
        ] = firestore.SERVER_TIMESTAMP

        update_data[
            "last_recovery_reason"
        ] = (
            "New Linux boot detected "
            "(reboot or power cycle)"
        )

        update_data[
            "last_recovery_at"
        ] = firestore.SERVER_TIMESTAMP

        print(
            "[NODE STATUS] "
            f"New boot detected: {node_id}"
        )

        print(
            "[NODE STATUS] "
            f"Old boot ID: {old_boot_id}"
        )

        print(
            "[NODE STATUS] "
            f"New boot ID: {new_boot_id}"
        )

    # --------------------------------------------------------
    # No reboot, but heartbeat had been absent > 5 minutes
    # --------------------------------------------------------

    elif (
        gap_seconds is not None
        and
        gap_seconds
        > OFFLINE_THRESHOLD_SECONDS
    ):

        update_data[
            "last_recovery_reason"
        ] = (
            "Heartbeat interruption "
            "without Linux reboot"
        )

        update_data[
            "last_recovery_at"
        ] = firestore.SERVER_TIMESTAMP

        print(
            "[NODE STATUS] "
            "Heartbeat recovered after timeout."
        )

        print(
            "[NODE STATUS] "
            f"Gap: {gap_seconds:.0f} seconds"
        )

    # --------------------------------------------------------
    # Write node status to Firestore
    # --------------------------------------------------------

    delay = INITIAL_RETRY_DELAY

    for attempt in range(
        1,
        MAX_FIRESTORE_RETRIES + 1
    ):

        try:

            (
                db
                .collection(
                    NODE_STATUS_COLLECTION
                )
                .document(
                    node_id
                )
                .set(
                    update_data,
                    merge=True
                )
            )

            print(
                "[FIRESTORE] "
                "Heartbeat updated: "
                f"{node_id}"
            )

            # ------------------------------------------------
            # Update local cache only after Firestore succeeds
            # ------------------------------------------------

            node_status_cache[
                node_id
            ] = {
                "boot_id":
                    (
                        new_boot_id
                        if new_boot_id
                        != "unknown"
                        else old_boot_id
                    ),

                "last_heartbeat":
                    now_utc,
            }

            return True

        except Exception as error:

            print(
                "[FIRESTORE] "
                f"Heartbeat attempt "
                f"{attempt}/"
                f"{MAX_FIRESTORE_RETRIES} "
                f"failed: {error}"
            )

            if (
                attempt
                < MAX_FIRESTORE_RETRIES
            ):

                print(
                    "[FIRESTORE] "
                    f"Retrying heartbeat "
                    f"in {delay} s..."
                )

                time.sleep(
                    delay
                )

                delay *= 2

    print(
        "[FIRESTORE] "
        "Heartbeat could not be uploaded "
        "after all retries."
    )

    return False


# ============================================================
# Process MQTT Message
# ============================================================

def on_message(
    client,
    userdata,
    msg
):

    try:

        # ====================================================
        # Read MQTT JSON payload
        # ====================================================

        payload = msg.payload.decode(
            "utf-8"
        )

        data = json.loads(
            payload
        )

        # ====================================================
        # HEARTBEAT MESSAGE
        # ====================================================

        if msg.topic.endswith(
            "/heartbeat"
        ):

            print()

            print(
                "[MQTT] Heartbeat received:"
            )

            print(
                f"  Topic: {msg.topic}"
            )

            print(
                f"  Node: "
                f"{data.get('node_id', '')}"
            )

            handle_heartbeat(
                data
            )

            return

        # ====================================================
        # Ignore unknown topics
        # ====================================================

        if not msg.topic.endswith(
            "/detections"
        ):

            print(
                "[MQTT] Ignored unknown topic: "
                f"{msg.topic}"
            )

            return

        # ====================================================
        # BIRD DETECTION MESSAGE
        # ====================================================

        # ====================================================
        # Read detection fields
        # ====================================================

        event_id = data.get(
            "event_id"
        )

        common_name = data.get(
            "common_name",
            ""
        )

        scientific_name = data.get(
            "sci_name",
            ""
        )

        species_code = data.get(
            "species_code",
            ""
        )

        confidence = data.get(
            "confidence",
            0
        )

        node_id = data.get(
            "node_id",
            "node"
        )

        # ====================================================
        # Read SQLite transport identifiers
        # ====================================================

        local_event_id = data.get(
            "local_event_id"
        )

        local_detection_id = data.get(
            "local_detection_id"
        )

        # ====================================================
        # Read time values from MQTT
        # ====================================================

        timestamp_text = data.get(
            "timestamp",
            ""
        )

        start_offset = float(
            data.get(
                "start_time",
                0
            )
        )

        end_offset = float(
            data.get(
                "end_time",
                start_offset
            )
        )

        # ====================================================
        # Validate timestamp
        # ====================================================

        if not timestamp_text:

            raise ValueError(
                "Missing timestamp in MQTT payload"
            )

        # ====================================================
        # Convert timestamp to Python datetime
        # ====================================================

        event_timestamp = (
            datetime.fromisoformat(
                timestamp_text
            )
        )

        # If publisher sends Malaysia local time
        # without timezone information, explicitly
        # attach Asia/Kuala_Lumpur.
        if event_timestamp.tzinfo is None:

            event_timestamp = (
                event_timestamp.replace(
                    tzinfo=ZoneInfo(
                        "Asia/Kuala_Lumpur"
                    )
                )
            )

        # ====================================================
        # Calculate absolute start/end timestamps
        # ====================================================

        duration = (
            end_offset
            - start_offset
        )

        if duration < 0:

            raise ValueError(
                "end_time is earlier "
                "than start_time"
            )

        # Publisher timestamp represents
        # actual event start.
        start_datetime = (
            event_timestamp
        )

        end_datetime = (
            start_datetime
            + timedelta(
                seconds=duration
            )
        )

        # ====================================================
        # Generate fallback event ID if missing
        # ====================================================

        if not event_id:

            event_id = (
                f"{node_id}_"
                f"{timestamp_text}_"
                f"{species_code}_"
                f"{uuid.uuid4().hex[:6]}"
            )

            event_id = (
                event_id
                .replace(" ", "_")
                .replace(":", "-")
            )

        # ====================================================
        # Create clean Firestore document
        # ====================================================
        #
        # Internal SQLite transport fields are deliberately
        # NOT written to Firestore.
        # ====================================================

        firestore_data = {
            "event_id":
                event_id,

            "species_code":
                species_code,

            "common_name":
                common_name,

            "sci_name":
                scientific_name,

            "confidence":
                confidence,

            "timestamp":
                event_timestamp,

            "start_time":
                start_datetime,

            "end_time":
                end_datetime,

            "duration":
                duration,

            "node_id":
                node_id,

            "lat":
                data.get(
                    "lat"
                ),

            "lon":
                data.get(
                    "lon"
                )
        }

        # ====================================================
        # Display detection
        # ====================================================

        print()

        print(
            "[FIREBASE] New detection:"
        )

        print(
            f"  Species: "
            f"{common_name}"
        )

        print(
            f"  Scientific: "
            f"{scientific_name}"
        )

        print(
            f"  Code: "
            f"{species_code}"
        )

        print(
            f"  Confidence: "
            f"{confidence}"
        )

        print(
            f"  Timestamp: "
            f"{event_timestamp}"
        )

        print(
            f"  Start time: "
            f"{start_datetime}"
        )

        print(
            f"  End time: "
            f"{end_datetime}"
        )

        print(
            f"  Duration: "
            f"{duration} s"
        )

        print(
            f"  Event ID: "
            f"{event_id}"
        )

        # ====================================================
        # Write detection to Firestore
        # ====================================================

        success = save_to_firestore(
            event_id,
            firestore_data
        )

        # ====================================================
        # Firestore succeeded -> send detection ACK
        # ====================================================

        if success:

            print(
                "[FIREBASE] SUCCESS!"
            )

            print(
                f"  Document ID: "
                f"{event_id}"
            )

            # ACK is meaningful only for messages
            # originating from the SQLite transport.
            if (
                local_event_id is not None
                and
                local_detection_id is not None
            ):

                publish_ack(
                    client=client,
                    node_id=node_id,
                    event_id=event_id,
                    local_event_id=local_event_id,
                    local_detection_id=local_detection_id
                )

            else:

                print(
                    "[ACK] No SQLite transport "
                    "identifiers supplied; "
                    "no ACK required."
                )

        else:

            # IMPORTANT:
            # Do not send ACK if Firestore failed.

            print(
                "[FIREBASE] FAILED after "
                "all retries."
            )

            print(
                "[ACK] No ACK sent. "
                "SQLite event must remain sent=0."
            )

    except json.JSONDecodeError:

        print(
            "[ERROR] Invalid JSON received."
        )

    except Exception as e:

        print(
            f"[FIREBASE] Error "
            f"processing payload: {e}"
        )

        # This message is mainly relevant to detection
        # processing. Heartbeats do not use SQLite ACK.
        print(
            "[ACK] No ACK sent."
        )


# ============================================================
# MQTT Client
# ============================================================

bridge = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id=(
        f"MQTT_Firebase_Bridge_"
        f"{uuid.uuid4().hex[:6]}"
    )
)

bridge.on_connect = (
    on_connect
)

bridge.on_message = (
    on_message
)


# ============================================================
# Start
# ============================================================

print(
    "=========================================="
)

print(
    "BirdNET MQTT to Firestore Bridge + ACK"
)

print(
    "=========================================="
)

print(
    f"[CONFIG] Detection topic: "
    f"{DETECTION_TOPIC}"
)

print(
    f"[CONFIG] Heartbeat topic: "
    f"{HEARTBEAT_TOPIC}"
)

print(
    "[CONFIG] ACK topic: "
    "birdnet/<node_id>/acks"
)

print(
    f"[CONFIG] Node status collection: "
    f"{NODE_STATUS_COLLECTION}"
)

print(
    f"[CONFIG] Offline threshold: "
    f"{OFFLINE_THRESHOLD_SECONDS} seconds"
)

print(
    f"[CONFIG] Firestore retries: "
    f"{MAX_FIRESTORE_RETRIES}"
)

print(
    "=========================================="
)

print(
    "[MQTT] Connecting to local broker..."
)

try:

    bridge.connect(
        MQTT_BROKER,
        MQTT_PORT,
        keepalive=60
    )

    bridge.loop_forever()


except KeyboardInterrupt:

    print()

    print(
        "[MQTT] Firebase bridge stopped."
    )


except Exception as e:

    print(
        f"[MQTT] Bridge error: {e}"
    )
