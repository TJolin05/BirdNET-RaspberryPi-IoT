#!/usr/bin/env python3

import json
import threading
import time
import sys

import paho.mqtt.client as mqtt

from birdnet_buffer import (
    get_pending,
    mark_sent_by_event_id,
    increment_attempts,
)


# Make print() output immediately
sys.stdout.reconfigure(line_buffering=True)


# ============================================================
# Configuration
# ============================================================

NODE_ID = "birdnode2"

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_QOS = 1

DETECTION_TOPIC = (
    f"birdnet/{NODE_ID}/detections"
)

ACK_TOPIC = (
    f"birdnet/{NODE_ID}/acks"
)

POLL_INTERVAL_SECONDS = 2
BATCH_SIZE = 100

# How long to wait for mqtt_to_firebase.py to confirm that
# Firestore successfully stored the event.
ACK_TIMEOUT_SECONDS = 30


# ============================================================
# MQTT State
# ============================================================

mqtt_connected = False

# event_id -> threading.Event()
ack_waiters = {}

# MQTT callback thread and main publisher thread both access
# ack_waiters, so protect it with a lock.
ack_lock = threading.Lock()


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

    global mqtt_connected

    try:
        success = (
            int(reason_code) == 0
        )

    except Exception:
        success = (
            reason_code == 0
        )

    if success:

        mqtt_connected = True

        print(
            "[MQTT] Connected to broker."
        )

        print(
            f"[MQTT] Detection topic: "
            f"{DETECTION_TOPIC}"
        )

        print(
            f"[MQTT] ACK topic: "
            f"{ACK_TOPIC}"
        )

        print(
            f"[MQTT] QoS: "
            f"{MQTT_QOS}"
        )

        # Subscribe every time we connect/reconnect.
        result, mid = client.subscribe(
            ACK_TOPIC,
            qos=MQTT_QOS
        )

        if result == mqtt.MQTT_ERR_SUCCESS:

            print(
                "[MQTT] Subscribed to "
                "Firestore ACK topic."
            )

        else:

            print(
                "[MQTT] ACK subscription "
                f"failed: {result}"
            )

    else:

        mqtt_connected = False

        print(
            f"[MQTT] Connection failed: "
            f"{reason_code}"
        )


def on_disconnect(
    client,
    userdata,
    disconnect_flags,
    reason_code,
    properties
):

    global mqtt_connected

    mqtt_connected = False

    print(
        f"[MQTT] Disconnected: "
        f"{reason_code}"
    )

    print(
        "[MQTT] SQLite events remain buffered."
    )


def on_message(
    client,
    userdata,
    msg
):

    # Only ACK messages should reach this client.
    if msg.topic != ACK_TOPIC:
        return

    try:

        payload = msg.payload.decode(
            "utf-8"
        )

        data = json.loads(
            payload
        )

        status = str(
            data.get(
                "status",
                ""
            )
        ).strip()

        event_id = str(
            data.get(
                "event_id",
                ""
            )
        ).strip()

        local_event_id = str(
            data.get(
                "local_event_id",
                ""
            )
        ).strip()

        local_detection_id = (
            data.get(
                "local_detection_id"
            )
        )

        # ====================================================
        # Validate ACK
        # ====================================================

        if status != "saved":

            print(
                f"[ACK] Ignored ACK with "
                f"status={status}"
            )

            return

        if not event_id:

            print(
                "[ACK] Ignored ACK without "
                "event_id."
            )

            return

        if (
            local_event_id
            and
            local_event_id != event_id
        ):

            print(
                "[ACK] Warning: event_id and "
                "local_event_id differ."
            )

            print(
                f"[ACK] event_id       : "
                f"{event_id}"
            )

            print(
                f"[ACK] local_event_id : "
                f"{local_event_id}"
            )

        print()
        print(
            "=========================================="
        )

        print(
            "[ACK] Firestore confirmation received"
        )

        print(
            "=========================================="
        )

        print(
            f"[ACK] Event ID           : "
            f"{event_id}"
        )

        print(
            f"[ACK] Local event ID     : "
            f"{local_event_id}"
        )

        print(
            f"[ACK] Local detection ID : "
            f"{local_detection_id}"
        )

        # ====================================================
        # Find publisher waiting for this event
        # ====================================================

        with ack_lock:

            waiter = ack_waiters.get(
                event_id
            )

            if waiter is not None:

                waiter.set()

                print(
                    "[ACK] Matching pending "
                    "SQLite event found."
                )

            else:

                # A valid ACK can arrive after the original
                # 30-second waiting period.
                #
                # Firestore has still confirmed the event was
                # stored, so it is safe to mark it sent.
                print(
                    "[ACK] No active waiter found."
                )

                print(
                    "[ACK] Treating as late "
                    "valid ACK."
                )

                mark_sent_by_event_id(
                    event_id
                )

                print(
                    "[SQLITE] Late-ACK event "
                    "marked sent=1."
                )

    except json.JSONDecodeError:

        print(
            "[ACK] Invalid JSON received."
        )

    except Exception as e:

        print(
            f"[ACK] Error processing ACK: "
            f"{e}"
        )


# ============================================================
# Convert SQLite Row to MQTT Payload
# ============================================================

def build_payload(
    row
):

    # ========================================================
    # Final cloud fields remain:
    #
    # common_name
    # confidence
    # duration
    # end_time
    # event_id
    # lat
    # lon
    # node_id
    # sci_name
    # species_code
    # start_time
    # timestamp
    #
    # local_event_id and local_detection_id are transport
    # metadata used for ACK matching.
    # mqtt_to_firebase.py should not store those two internal
    # fields in the final Firestore detection document.
    # ========================================================

    duration = round(
        float(
            row["duration"]
        ),
        3
    )

    payload = {

        "common_name":
            row["common_name"],

        "confidence":
            round(
                float(
                    row["confidence"]
                ),
                4
            ),

        "duration":
            duration,

        # timestamp is the absolute beginning of the event.
        #
        # start_time/end_time remain relative offsets for the
        # existing mqtt_to_firebase.py format.
        "end_time":
            duration,

        "event_id":
            row["event_id"],

        "lat":
            row["lat"],

        "lon":
            row["lon"],

        "node_id":
            row["node_id"],

        "sci_name":
            row["sci_name"],

        "species_code":
            row["species_code"],

        "start_time":
            0.0,

        "timestamp":
            row["detected_at"],

        # Internal transport metadata
        "local_event_id":
            row["event_id"],

        "local_detection_id":
            row["id"],
    }

    return payload


# ============================================================
# Publish One Event and Wait for Firestore ACK
# ============================================================

def publish_event(
    client,
    row
):

    event_id = str(
        row["event_id"]
    )

    payload = build_payload(
        row
    )

    payload_json = json.dumps(
        payload,
        ensure_ascii=False
    )

    print()
    print(
        "=========================================="
    )

    print(
        "[MQTT] Publishing SQLite event"
    )

    print(
        "=========================================="
    )

    print(
        f"[MQTT] SQLite ID   : "
        f"{row['id']}"
    )

    print(
        f"[MQTT] Event ID    : "
        f"{event_id}"
    )

    print(
        f"[MQTT] Species     : "
        f"{row['common_name']}"
    )

    print(
        f"[MQTT] Species code: "
        f"{row['species_code']}"
    )

    print(
        f"[MQTT] Confidence  : "
        f"{row['confidence']}"
    )

    print(
        f"[MQTT] Start       : "
        f"{row['start_time']}"
    )

    print(
        f"[MQTT] End         : "
        f"{row['end_time']}"
    )

    print(
        f"[MQTT] Duration    : "
        f"{row['duration']} s"
    )

    # ========================================================
    # Create ACK waiter BEFORE publishing
    # ========================================================

    waiter = threading.Event()

    with ack_lock:

        ack_waiters[
            event_id
        ] = waiter

    try:

        # Count delivery attempt.
        increment_attempts(
            event_id
        )

        # ====================================================
        # Publish to local Mosquitto
        # ====================================================

        info = client.publish(
            DETECTION_TOPIC,
            payload_json,
            qos=MQTT_QOS,
            retain=False
        )

        # ====================================================
        # Stage 1:
        # Confirm local MQTT broker received publication
        # ====================================================

        info.wait_for_publish(
            timeout=10
        )

        if not info.is_published():

            print(
                "[MQTT] Publication was not "
                "confirmed."
            )

            print(
                "[SQLITE] Event remains sent=0."
            )

            return False

        print(
            "[MQTT] Publication confirmed "
            "by local broker."
        )

        print(
            "[SQLITE] Event STILL sent=0."
        )

        print(
            "[ACK] Waiting for Firestore "
            f"confirmation "
            f"({ACK_TIMEOUT_SECONDS} s timeout)..."
        )

        # ====================================================
        # Stage 2:
        # Wait for mqtt_to_firebase.py ACK
        # ====================================================

        ack_received = waiter.wait(
            timeout=ACK_TIMEOUT_SECONDS
        )

        if not ack_received:

            print(
                "[ACK] Firestore ACK timeout."
            )

            print(
                "[SQLITE] Event remains sent=0."
            )

            print(
                "[SYSTEM] Event will be retried."
            )

            return False

        # ====================================================
        # Firestore ACK received
        # ====================================================

        mark_sent_by_event_id(
            event_id
        )

        print(
            "[ACK] Firestore save confirmed."
        )

        print(
            "[SQLITE] Event marked sent=1."
        )

        return True

    except Exception as e:

        print(
            f"[MQTT] Delivery failed: "
            f"{e}"
        )

        print(
            "[SQLITE] Event remains sent=0."
        )

        return False

    finally:

        with ack_lock:

            ack_waiters.pop(
                event_id,
                None
            )


# ============================================================
# Main
# ============================================================

def main():

    global mqtt_connected

    print()
    print(
        "=========================================="
    )

    print(
        "BirdNET SQLite → MQTT → Firestore "
        "ACK Publisher"
    )

    print(
        "=========================================="
    )

    print(
        f"[CONFIG] Node ID: "
        f"{NODE_ID}"
    )

    print(
        f"[CONFIG] MQTT broker: "
        f"{MQTT_BROKER}:{MQTT_PORT}"
    )

    print(
        f"[CONFIG] Detection topic: "
        f"{DETECTION_TOPIC}"
    )

    print(
        f"[CONFIG] ACK topic: "
        f"{ACK_TOPIC}"
    )

    print(
        f"[CONFIG] MQTT QoS: "
        f"{MQTT_QOS}"
    )

    print(
        f"[CONFIG] Firestore ACK timeout: "
        f"{ACK_TIMEOUT_SECONDS} s"
    )

    print(
        "[CONFIG] SQLite sent=1 only after "
        "Firestore ACK."
    )

    print(
        "=========================================="
    )

    # ========================================================
    # MQTT Client
    # ========================================================

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=(
            f"{NODE_ID}-sqlite-publisher"
        )
    )

    client.on_connect = (
        on_connect
    )

    client.on_disconnect = (
        on_disconnect
    )

    client.on_message = (
        on_message
    )

    # Paho will use this delay if its network loop needs
    # to reconnect after an unexpected connection loss.
    client.reconnect_delay_set(
        min_delay=1,
        max_delay=30
    )

    print(
        "[MQTT] Connecting..."
    )

    try:

        client.connect(
            MQTT_BROKER,
            MQTT_PORT,
            keepalive=60
        )

    except Exception as e:

        print(
            f"[MQTT] Initial connection "
            f"failed: {e}"
        )

        print(
            "[MQTT] SQLite data remains safe."
        )

    # IMPORTANT:
    #
    # loop_start() owns MQTT network processing.
    # We do NOT repeatedly call client.reconnect() from
    # the main loop.
    client.loop_start()

    print(
        "[SYSTEM] SQLite publisher started."
    )

    print(
        "[SYSTEM] Waiting for pending events."
    )

    print(
        "[SYSTEM] Press Ctrl+C to stop."
    )

    try:

        while True:

            # =================================================
            # MQTT currently unavailable
            # =================================================

            if not mqtt_connected:

                print(
                    "[MQTT] Broker unavailable. "
                    "SQLite events remain buffered."
                )

                # IMPORTANT:
                # Do NOT call client.reconnect() here.
                #
                # Paho's network loop manages the MQTT
                # connection/reconnection.
                time.sleep(
                    POLL_INTERVAL_SECONDS
                )

                continue

            # =================================================
            # Get unsent SQLite events
            # =================================================

            pending = get_pending(
                limit=BATCH_SIZE
            )

            if not pending:

                time.sleep(
                    POLL_INTERVAL_SECONDS
                )

                continue

            print()
            print(
                f"[SQLITE] Pending events: "
                f"{len(pending)}"
            )

            # =================================================
            # Publish oldest event first
            # =================================================

            for row in pending:

                if not mqtt_connected:

                    print(
                        "[MQTT] Connection lost."
                    )

                    print(
                        "[SQLITE] Remaining events "
                        "stay sent=0."
                    )

                    break

                success = publish_event(
                    client,
                    row
                )

                if not success:

                    # Keep chronological ordering.
                    #
                    # Failed event remains sent=0.
                    # Do not skip ahead to newer events.
                    break

            time.sleep(
                0.2
            )

    except KeyboardInterrupt:

        print()
        print(
            "[SYSTEM] Stop requested."
        )

    finally:

        try:

            client.disconnect()

        except Exception:

            pass

        client.loop_stop()

        print(
            "[SYSTEM] SQLite → MQTT "
            "publisher stopped."
        )


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    main()
