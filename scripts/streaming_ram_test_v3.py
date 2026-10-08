#!/usr/bin/env python3

import json
import queue
import threading
import time
from datetime import datetime

import birdnet
import numpy as np
import sounddevice as sd

from birdnet_buffer import insert_event


# ============================================================
# Configuration
# ============================================================

DEVICE = 1

SAMPLE_RATE = 48000
WINDOW_SECONDS = 3
WINDOW_SAMPLES = SAMPLE_RATE * WINDOW_SECONDS

MIN_CONF = 0.50
TOP_K = None
OVERLAP_SECONDS = 0.0

SPECIES_LIST = "/home/jolin/malaysia_28_species.txt"

TAXONOMY_CODES = (
    "/home/jolin/birdnet-env/lib/python3.13/"
    "site-packages/birdnet_analyzer/"
    "eBird_taxonomy_codes_2024E.json"
)

NODE_ID = "birdnode2"

# Fixed deployment location.
# Keep the same values already used by your system.
LAT = 3.235339
LON = 101.634269

# One complete 3-second window may be missed before
# an active event is finalized.
#
# miss 1 -> keep pending
# miss 2 -> finalize
MAX_MISSED_WINDOWS = 1


# ============================================================
# Queues
# ============================================================

raw_audio_queue = queue.Queue(
    maxsize=200
)

birdnet_queue = queue.Queue(
    maxsize=10
)

stop_event = threading.Event()


# ============================================================
# Statistics
# ============================================================

window_number = 0
dropped_audio_blocks = 0


# ============================================================
# Active Events
# ============================================================

# Multiple species can be active simultaneously.
#
# Key:
# BirdNET full species name:
#
# "Geopelia striata_Zebra Dove"
#
# Value:
# event information

active_events = {}


# ============================================================
# Load Official eBird Taxonomy Codes
# ============================================================

def load_taxonomy_codes():

    print(
        "[TAXONOMY] Loading eBird taxonomy codes..."
    )

    try:

        with open(
            TAXONOMY_CODES,
            "r",
            encoding="utf-8"
        ) as file:

            taxonomy = json.load(
                file
            )

        print(
            f"[TAXONOMY] Mapping loaded: "
            f"{len(taxonomy)} entries"
        )

        print(
            f"[TAXONOMY] Source: "
            f"{TAXONOMY_CODES}"
        )

        return taxonomy

    except Exception as e:

        print(
            f"[TAXONOMY] ERROR: {e}"
        )

        raise


EBIRD_CODES = load_taxonomy_codes()


# ============================================================
# Species Parsing
# ============================================================

def parse_species_name(
    species_name
):

    species_name = str(
        species_name
    ).strip()

    if "_" in species_name:

        scientific_name, common_name = (
            species_name.split(
                "_",
                1
            )
        )

        scientific_name = (
            scientific_name.strip()
        )

        common_name = (
            common_name.strip()
        )

    else:

        scientific_name = ""
        common_name = species_name

    return (
        scientific_name,
        common_name
    )


# ============================================================
# Official Species Code Lookup
# ============================================================

def get_species_code(
    species_name
):

    species_name = str(
        species_name
    ).strip()

    species_code = (
        EBIRD_CODES.get(
            species_name
        )
    )

    if species_code:

        return str(
            species_code
        ).strip().lower()

    # --------------------------------------------------------
    # IMPORTANT:
    # Do NOT invent a species code.
    #
    # If the taxonomy does not contain the BirdNET species,
    # return None so the problem is visible instead of storing
    # an incorrect code.
    # --------------------------------------------------------

    print(
        f"[TAXONOMY WARNING] "
        f"Species code not found: "
        f"{species_name}"
    )

    return None


# ============================================================
# Microphone Callback
# ============================================================

def audio_callback(
    indata,
    frames,
    time_info,
    status
):

    global dropped_audio_blocks

    if status:

        print(
            f"[AUDIO WARNING] "
            f"{status}"
        )

    try:

        block = (
            indata[:, 0].copy()
        )

        raw_audio_queue.put_nowait(
            block
        )

    except queue.Full:

        dropped_audio_blocks += 1

        print(
            "[WARNING] Raw audio queue full. "
            "Audio block dropped."
        )


# ============================================================
# Audio Assembler
# ============================================================

def audio_assembler():

    global window_number

    buffer = np.empty(
        WINDOW_SAMPLES,
        dtype=np.float32
    )

    position = 0

    while not stop_event.is_set():

        try:

            block = (
                raw_audio_queue.get(
                    timeout=0.5
                )
            )

        except queue.Empty:

            continue

        try:

            block_position = 0
            block_length = len(
                block
            )

            while (
                block_position
                < block_length
            ):

                remaining_window = (
                    WINDOW_SAMPLES
                    - position
                )

                remaining_block = (
                    block_length
                    - block_position
                )

                copy_count = min(
                    remaining_window,
                    remaining_block
                )

                buffer[
                    position:
                    position + copy_count
                ] = block[
                    block_position:
                    block_position + copy_count
                ]

                position += copy_count
                block_position += copy_count

                # ============================================
                # Complete 3-second BirdNET window
                # ============================================

                if (
                    position
                    == WINDOW_SAMPLES
                ):

                    window_number += 1

                    completed_window = (
                        buffer.copy()
                    )

                    # Timestamp immediately after assembling
                    # the complete continuous window.
                    window_end = time.time()

                    window_start = (
                        window_end
                        - WINDOW_SECONDS
                    )

                    try:

                        birdnet_queue.put(
                            (
                                window_number,
                                completed_window,
                                window_start,
                                window_end
                            ),
                            timeout=1.0
                        )

                        print(
                            f"[AUDIO] Window "
                            f"{window_number} "
                            f"assembled → "
                            f"BirdNET queue"
                        )

                    except queue.Full:

                        print(
                            f"[WARNING] "
                            f"BirdNET queue full. "
                            f"Window "
                            f"{window_number} "
                            f"dropped."
                        )

                    position = 0

        finally:

            raw_audio_queue.task_done()


# ============================================================
# Create New Event
# ============================================================

def create_event(
    species_name,
    confidence,
    current_window,
    window_start,
    window_end
):

    scientific_name, common_name = (
        parse_species_name(
            species_name
        )
    )

    species_code = (
        get_species_code(
            species_name
        )
    )

    event = {

        "node_id":
            NODE_ID,

        "species_name":
            species_name,

        "species_code":
            species_code,

        "common_name":
            common_name,

        "sci_name":
            scientific_name,

        "start_time":
            window_start,

        "end_time":
            window_end,

        "first_window":
            current_window,

        "last_window":
            current_window,

        "max_confidence":
            confidence,

        "confidence_sum":
            confidence,

        "detections":
            1,

        "missed_windows":
            0
    }

    active_events[
        species_name
    ] = event

    print(
        f"[EVENT] NEW → "
        f"{species_name}"
    )

    if species_code:

        print(
            f"[EVENT] Species code → "
            f"{species_code}"
        )


# ============================================================
# Update Existing Event
# ============================================================

def update_event(
    event,
    confidence,
    current_window,
    window_end
):

    event[
        "end_time"
    ] = window_end

    event[
        "last_window"
    ] = current_window

    event[
        "detections"
    ] += 1

    event[
        "confidence_sum"
    ] += confidence

    event[
        "missed_windows"
    ] = 0

    event[
        "max_confidence"
    ] = max(
        event[
            "max_confidence"
        ],
        confidence
    )

    print(
        f"[EVENT] CONTINUE → "
        f"{event['species_name']}"
    )


# ============================================================
# Build Human-Readable Event ID
# ============================================================

def build_event_id(
    event
):

    start_datetime = (
        datetime.fromtimestamp(
            event[
                "start_time"
            ]
        )
    )

    end_datetime = (
        datetime.fromtimestamp(
            event[
                "end_time"
            ]
        )
    )

    event_date = (
        start_datetime.strftime(
            "%Y%m%d"
        )
    )

    start_id = (
        start_datetime.strftime(
            "%H%M%S"
        )
    )

    end_id = (
        end_datetime.strftime(
            "%H%M%S"
        )
    )

    species_code = (
        event[
            "species_code"
        ]
    )

    return (
        f"{NODE_ID}_"
        f"{species_code}_"
        f"{event_date}_"
        f"{start_id}_"
        f"{end_id}"
    )


# ============================================================
# Finalize Event
# ============================================================

def finalize_event(
    species_name
):

    event = (
        active_events.pop(
            species_name
        )
    )

    duration = (
        event[
            "end_time"
        ]
        - event[
            "start_time"
        ]
    )

    average_confidence = (
        event[
            "confidence_sum"
        ]
        / event[
            "detections"
        ]
    )

    start_datetime = (
        datetime.fromtimestamp(
            event[
                "start_time"
            ]
        ).astimezone()
    )

    end_datetime = (
        datetime.fromtimestamp(
            event[
                "end_time"
            ]
        ).astimezone()
    )

    start_text = (
        start_datetime.isoformat()
    )

    end_text = (
        end_datetime.isoformat()
    )

    species_code = (
        event[
            "species_code"
        ]
    )

    print()
    print(
        "##########################################"
    )
    print(
        "           FINALIZED EVENT"
    )
    print(
        "##########################################"
    )

    print(
        f"Node ID        : "
        f"{event['node_id']}"
    )

    print(
        f"Species        : "
        f"{event['species_name']}"
    )

    print(
        f"Scientific     : "
        f"{event['sci_name']}"
    )

    print(
        f"Common name    : "
        f"{event['common_name']}"
    )

    print(
        f"Species code   : "
        f"{species_code}"
    )

    print(
        f"Start          : "
        f"{start_text}"
    )

    print(
        f"End            : "
        f"{end_text}"
    )

    print(
        f"Duration       : "
        f"{duration:.1f} s"
    )

    print(
        f"First window   : "
        f"{event['first_window']}"
    )

    print(
        f"Last window    : "
        f"{event['last_window']}"
    )

    print(
        f"Detections     : "
        f"{event['detections']}"
    )

    print(
        f"Max confidence : "
        f"{event['max_confidence']:.4f}"
    )

    print(
        f"Avg confidence : "
        f"{average_confidence:.4f}"
    )

    # --------------------------------------------------------
    # Do not store an event if the official taxonomy code
    # could not be found.
    # --------------------------------------------------------

    if not species_code:

        print(
            "[SQLITE] NOT STORED: "
            "official species code "
            "was not found."
        )

        print(
            "##########################################"
        )

        print()

        return

    # --------------------------------------------------------
    # Preserve your existing event-ID format:
    #
    # birdnode2_speciescode_date_start_end
    # --------------------------------------------------------

    event_id = (
        build_event_id(
            event
        )
    )

    print(
        f"Event ID       : "
        f"{event_id}"
    )

    # --------------------------------------------------------
    # Store locally FIRST
    #
    # sent = 0 is automatically assigned by
    # birdnet_buffer.insert_event().
    # --------------------------------------------------------

    try:

        (
            detection_id,
            stored_event_id,
            inserted
        ) = insert_event(

            species_code=(
                species_code
            ),

            common_name=(
                event[
                    "common_name"
                ]
            ),

            sci_name=(
                event[
                    "sci_name"
                ]
            ),

            confidence=round(
                event[
                    "max_confidence"
                ],
                4
            ),

            detected_at=(
                start_text
            ),

            node_id=(
                event[
                    "node_id"
                ]
            ),

            lat=LAT,

            lon=LON,

            event_id=(
                event_id
            ),

            start_time=(
                start_text
            ),

            end_time=(
                end_text
            ),

            duration=round(
                duration,
                3
            )
        )

        if inserted:

            print(
                "[SQLITE] Event stored "
                "successfully."
            )

            print(
                f"[SQLITE] ID       : "
                f"{detection_id}"
            )

            print(
                f"[SQLITE] Event ID : "
                f"{stored_event_id}"
            )

            print(
                "[SQLITE] sent     : 0"
            )

        else:

            print(
                "[SQLITE] Duplicate event "
                "already exists."
            )

    except Exception as e:

        print(
            f"[SQLITE] ERROR: "
            f"{e}"
        )

    print(
        "##########################################"
    )

    print()


# ============================================================
# Event Manager
# ============================================================

def process_events(
    df,
    current_window,
    window_start,
    window_end
):

    detected_species = set()

    if not df.empty:

        for _, row in (
            df.iterrows()
        ):

            species_name = str(
                row[
                    "species_name"
                ]
            ).strip()

            confidence = float(
                row[
                    "confidence"
                ]
            )

            detected_species.add(
                species_name
            )

            # ================================================
            # Existing active event
            # ================================================

            if (
                species_name
                in active_events
            ):

                update_event(
                    active_events[
                        species_name
                    ],
                    confidence,
                    current_window,
                    window_end
                )

            # ================================================
            # New event
            # ================================================

            else:

                create_event(
                    species_name,
                    confidence,
                    current_window,
                    window_start,
                    window_end
                )

    # ========================================================
    # Species absent from current window
    # ========================================================

    for species_name in list(
        active_events.keys()
    ):

        if (
            species_name
            not in detected_species
        ):

            event = (
                active_events[
                    species_name
                ]
            )

            event[
                "missed_windows"
            ] += 1

            print(
                f"[EVENT] MISS "
                f"{event['missed_windows']}/"
                f"{MAX_MISSED_WINDOWS} "
                f"→ "
                f"{species_name}"
            )

            # One missed window is allowed.
            #
            # MISS 1 -> remain pending
            # MISS 2 -> finalize
            if (
                event[
                    "missed_windows"
                ]
                > MAX_MISSED_WINDOWS
            ):

                finalize_event(
                    species_name
                )


# ============================================================
# Finalize Remaining Events
# ============================================================

def finalize_all_events():

    for species_name in list(
        active_events.keys()
    ):

        finalize_event(
            species_name
        )


# ============================================================
# BirdNET Worker
# ============================================================

def birdnet_worker(
    session
):

    while not stop_event.is_set():

        try:

            (
                number,
                audio,
                window_start,
                window_end
            ) = birdnet_queue.get(
                timeout=0.5
            )

        except queue.Empty:

            continue

        try:

            print()

            print(
                "=========================================="
            )

            print(
                f"[WINDOW {number}] "
                f"BirdNET processing..."
            )

            # ================================================
            # RMS
            # ================================================

            rms = float(
                np.sqrt(
                    np.mean(
                        audio ** 2
                    )
                )
            )

            print(
                f"[WINDOW {number}] "
                f"RMS: "
                f"{rms:.6f}"
            )

            # ================================================
            # BirdNET RAM inference
            # ================================================

            inference_start = (
                time.perf_counter()
            )

            result = (
                session.run_arrays(
                    (
                        audio,
                        SAMPLE_RATE
                    )
                )
            )

            inference_time = (
                time.perf_counter()
                - inference_start
            )

            print(
                f"[WINDOW {number}] "
                f"Inference: "
                f"{inference_time:.2f} s"
            )

            # ================================================
            # Convert API result
            # ================================================

            df = (
                result.to_dataframe()
            )

            if df.empty:

                print(
                    f"[WINDOW {number}] "
                    "No bird detected."
                )

            else:

                print(
                    f"[WINDOW {number}] "
                    "DETECTION:"
                )

                print(
                    df.to_string(
                        index=False
                    )
                )

            # ================================================
            # Event Manager
            # ================================================

            process_events(
                df,
                number,
                window_start,
                window_end
            )

        except Exception as e:

            print(
                f"[WINDOW {number}] "
                f"ERROR: {e}"
            )

        finally:

            birdnet_queue.task_done()


# ============================================================
# Main
# ============================================================

def main():

    print()
    print(
        "=========================================="
    )
    print(
        "BirdNET V2.4 Continuous RAM Monitor"
    )
    print(
        "=========================================="
    )

    print(
        f"[CONFIG] Device: "
        f"{DEVICE}"
    )

    print(
        f"[CONFIG] Sample rate: "
        f"{SAMPLE_RATE} Hz"
    )

    print(
        f"[CONFIG] Window: "
        f"{WINDOW_SECONDS} s"
    )

    print(
        f"[CONFIG] Minimum confidence: "
        f"{MIN_CONF}"
    )

    print(
        f"[CONFIG] Node ID: "
        f"{NODE_ID}"
    )

    print(
        f"[CONFIG] Location: "
        f"{LAT}, {LON}"
    )

    print(
        "[CONFIG] Audio storage: "
        "RAM only"
    )

    print(
        "[CONFIG] Final events: "
        "SQLite"
    )

    print(
        "=========================================="
    )

    # ========================================================
    # Load BirdNET V2.4
    # ========================================================

    print(
        "[BIRDNET] Loading "
        "BirdNET V2.4..."
    )

    start = (
        time.perf_counter()
    )

    model = birdnet.load(
        "acoustic",
        "2.4",
        "tf",
        library="litert"
    )

    print(
        f"[BIRDNET] Model loaded in "
        f"{time.perf_counter() - start:.2f} s"
    )

    print(
        "[BIRDNET] Starting persistent "
        "prediction session..."
    )

    with model.predict_session(

        top_k=TOP_K,

        overlap_duration_s=(
            OVERLAP_SECONDS
        ),

        default_confidence_threshold=(
            MIN_CONF
        ),

        custom_species_list=(
            SPECIES_LIST
        ),

        device="CPU"

    ) as session:

        print(
            "[BIRDNET] Session ready."
        )

        # ====================================================
        # Audio assembler thread
        # ====================================================

        assembler_thread = (
            threading.Thread(
                target=audio_assembler,
                daemon=True
            )
        )

        assembler_thread.start()

        # ====================================================
        # BirdNET worker thread
        # ====================================================

        birdnet_thread = (
            threading.Thread(
                target=birdnet_worker,
                args=(session,),
                daemon=True
            )
        )

        birdnet_thread.start()

        # ====================================================
        # Start microphone
        # ====================================================

        print()
        print(
            "[SYSTEM] Starting continuous "
            "RAM stream..."
        )

        print(
            "[SYSTEM] Event manager enabled."
        )

        print(
            "[SYSTEM] Official eBird taxonomy "
            "lookup enabled."
        )

        print(
            "[SYSTEM] SQLite offline buffer "
            "enabled."
        )

        print(
            "[SYSTEM] No WAV or CSV files "
            "are created."
        )

        print(
            "[SYSTEM] Press Ctrl+C to stop."
        )

        try:

            with sd.InputStream(

                device=DEVICE,

                samplerate=(
                    SAMPLE_RATE
                ),

                channels=1,

                dtype="float32",

                blocksize=4800,

                callback=(
                    audio_callback
                )

            ):

                while True:

                    time.sleep(5)

                    print(
                        "[STATUS] "
                        f"Raw queue="
                        f"{raw_audio_queue.qsize()} | "
                        f"BirdNET queue="
                        f"{birdnet_queue.qsize()} | "
                        f"Dropped blocks="
                        f"{dropped_audio_blocks} | "
                        f"Active events="
                        f"{len(active_events)}"
                    )

        except KeyboardInterrupt:

            print()
            print(
                "[SYSTEM] Stop requested."
            )

        finally:

            stop_event.set()

            assembler_thread.join(
                timeout=2
            )

            birdnet_thread.join(
                timeout=2
            )

            # Store any event still active when the
            # application is manually stopped.
            finalize_all_events()

            print()
            print(
                "=========================================="
            )

            print(
                "[SYSTEM] Final statistics"
            )

            print(
                f"[SYSTEM] Windows assembled: "
                f"{window_number}"
            )

            print(
                f"[SYSTEM] Dropped audio blocks: "
                f"{dropped_audio_blocks}"
            )

            print(
                "=========================================="
            )

            print(
                "[SYSTEM] Streaming stopped."
            )


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":

    main()
