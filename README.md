# BirdNET Raspberry Pi IoT Monitoring System

A Raspberry Pi-based bird monitoring system using
BirdNET for local bird identification, SQLite for
offline buffering, MQTT for communication, and
Firebase Firestore for centralized storage.

## System Architecture

USB Microphone
    ↓
BirdNET Python API
    ↓
Event Grouping
    ↓
SQLite
    ↓
MQTT Publisher (QoS 1)
    ↓
Mosquitto Broker
    ↓
MQTT-to-Firestore Bridge
    ↓
Firebase Firestore
    ↓
Application-level ACK
    ↓
SQLite sent = 1

## Features

- Continuous bird identification on Raspberry Pi
- Local BirdNET inference
- SQLite offline event buffering
- MQTT QoS 1 communication
- Firestore delivery confirmation using ACK
- Multi-node MQTT topic structure
- Node heartbeat monitoring

## Main Technologies

- Python
- Raspberry Pi OS
- BirdNET
- SQLite
- MQTT / Mosquitto
- Firebase Firestore

## Project Status

Developed and tested on BirdNode2.
