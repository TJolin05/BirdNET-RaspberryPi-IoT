#!/usr/bin/env python3

import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import paho.mqtt.client as mqtt


# ============================================================
# CONFIGURATION
# ============================================================

NODE_ID = "birdnode2"

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_QOS = 1

HEARTBEAT_INTERVAL = 120

HEARTBEAT_TOPIC = (
    f"birdnet/{NODE_ID}/heartbeat"
)

MALAYSIA_TZ = ZoneInfo(
    "Asia/Kuala_Lumpur"
)


# ============================================================
# LINUX BOOT ID
# ============================================================

def get_boot_id():
    try:
        return Path(
            "/proc/sys/kernel/random/boot_id"
        ).read_text(
            encoding="utf-8"
        ).strip()

    except Exception as error:
        print(
            f"[HEARTBEAT] Unable to read boot ID: "
            f"{error}",
            flush=True,
        )

        return "unknown"


# ============================================================
# MQTT CLIENT
# ============================================================

def create_mqtt_client():

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"{NODE_ID}-heartbeat",
    )

    return client


# ============================================================
# MAIN
# ============================================================

def main():

    boot_id = get_boot_id()

    print(
        "==========================================",
        flush=True,
    )

    print(
        " BirdNET Node Heartbeat",
        flush=True,
    )

    print(
        "==========================================",
        flush=True,
    )

    print(
        f"[CONFIG] Node ID: {NODE_ID}",
        flush=True,
    )

    print(
        f"[CONFIG] Topic: {HEARTBEAT_TOPIC}",
        flush=True,
    )

    print(
        f"[CONFIG] Interval: "
        f"{HEARTBEAT_INTERVAL} seconds",
        flush=True,
    )

    print(
        f"[CONFIG] Boot ID: {boot_id}",
        flush=True,
    )

    print(
        "==========================================",
        flush=True,
    )

    client = None

    while True:

        try:

            # --------------------------------------------
            # Connect/reconnect to local Mosquitto
            # --------------------------------------------

            if client is None:

                print(
                    "[MQTT] Connecting to local broker...",
                    flush=True,
                )

                client = create_mqtt_client()

                client.connect(
                    MQTT_BROKER,
                    MQTT_PORT,
                    keepalive=60,
                )

                client.loop_start()

                print(
                    "[MQTT] Connected.",
                    flush=True,
                )

            # --------------------------------------------
            # Build heartbeat
            # --------------------------------------------

            heartbeat_time = datetime.now(
                MALAYSIA_TZ
            )

            message = {
                "message_type": "heartbeat",
                "node_id": NODE_ID,
                "timestamp":
                    heartbeat_time.isoformat(),
                "boot_id": boot_id,
            }

            payload = json.dumps(
                message,
                ensure_ascii=False,
            )

            # --------------------------------------------
            # Publish heartbeat
            # --------------------------------------------

            result = client.publish(
                HEARTBEAT_TOPIC,
                payload,
                qos=MQTT_QOS,
                retain=False,
            )

            result.wait_for_publish(
                timeout=10
            )

            if not result.is_published():
                raise RuntimeError(
                    "Heartbeat publish was "
                    "not confirmed."
                )

            print(
                "[HEARTBEAT] Sent: "
                f"{NODE_ID} | "
                f"{heartbeat_time.strftime('%Y-%m-%d %H:%M:%S')}",
                flush=True,
            )

            # --------------------------------------------
            # Wait 2 minutes
            # --------------------------------------------

            time.sleep(
                HEARTBEAT_INTERVAL
            )

        except KeyboardInterrupt:

            print(
                "\n[HEARTBEAT] Stopping...",
                flush=True,
            )

            break

        except Exception as error:

            print(
                "[HEARTBEAT] Error: "
                f"{error}",
                flush=True,
            )

            if client is not None:

                try:
                    client.loop_stop()
                    client.disconnect()

                except Exception:
                    pass

                client = None

            print(
                "[HEARTBEAT] Retrying in "
                "5 seconds...",
                flush=True,
            )

            time.sleep(5)

    if client is not None:

        try:
            client.loop_stop()
            client.disconnect()

        except Exception:
            pass


if __name__ == "__main__":
    main()
