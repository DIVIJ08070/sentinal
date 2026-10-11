#!/usr/bin/env python
"""Event-bus PoC: push detection-shaped events through the Kafka API (Redpanda)
and measure throughput and end-to-end latency. Proves the ingest fan-out tier
the HLD describes (worker -> Kafka -> consumers), at single-broker scale.

    .venv/bin/python deploy/poc/bench/kafka_bench.py [N]
"""
import json
import sys
import time
import uuid

from kafka import KafkaConsumer, KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic

BROKER = "localhost:19092"
TOPIC = "detections"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 20000


def ensure_topic():
    admin = KafkaAdminClient(bootstrap_servers=BROKER)
    try:
        admin.create_topics([NewTopic(name=TOPIC, num_partitions=1, replication_factor=1)])
    except Exception:
        pass  # already exists
    admin.close()


def detection(i):
    # a realistic plate-event payload (~300 bytes)
    return {
        "id": str(uuid.uuid4()),
        "camera_id": 6 + (i % 30),
        "plate": "GJ%02d%s%04d" % (i % 40, "ABZ"[i % 3], i % 10000),
        "plate_confidence": 0.70 + (i % 30) / 100.0,
        "vehicle_type": ["car", "motorcycle", "bus", "truck"][i % 4],
        "pts_ms": i * 80.0,
        "captured_at": "2026-10-11T07:30:%02d.%03dZ" % (i % 60, i % 1000),
        "sent_ns": time.time_ns(),
    }


def main():
    ensure_topic()
    producer = KafkaProducer(
        bootstrap_servers=BROKER,
        value_serializer=lambda v: json.dumps(v).encode(),
        linger_ms=5, acks=1,
    )

    # --- produce ---
    t0 = time.perf_counter()
    for i in range(N):
        producer.send(TOPIC, detection(i))
    producer.flush()
    produce_s = time.perf_counter() - t0
    size = len(json.dumps(detection(0)).encode())

    # --- consume + end-to-end latency ---
    consumer = KafkaConsumer(
        TOPIC, bootstrap_servers=BROKER, auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode()),
        consumer_timeout_ms=8000, group_id="poc-" + uuid.uuid4().hex[:6],
    )
    got = 0
    lat_ns = []
    t1 = time.perf_counter()
    for msg in consumer:
        got += 1
        lat_ns.append(time.time_ns() - msg.value["sent_ns"])
        if got >= N:
            break
    consume_s = time.perf_counter() - t1
    consumer.close()

    lat_ms = sorted(l / 1e6 for l in lat_ns)
    p50 = lat_ms[len(lat_ms) // 2] if lat_ms else 0
    p99 = lat_ms[int(len(lat_ms) * 0.99)] if lat_ms else 0

    print("=== Kafka-API event bus (Redpanda, 1 broker) ===")
    print(f"  events                : {N:,}  (~{size} B each)")
    print(f"  produce throughput    : {N/produce_s:,.0f} events/s ({produce_s:.2f}s)")
    print(f"  consume throughput    : {got/consume_s:,.0f} events/s ({consume_s:.2f}s)")
    print(f"  end-to-end latency    : p50 {p50:.2f} ms   p99 {p99:.2f} ms")
    print(f"  delivered             : {got:,}/{N:,}")
    # contextualize against statewide load
    daily = 32_000_000  # HLD §6.4: Tier-A detections/day
    print(f"  statewide check       : {N/produce_s:,.0f} ev/s · one broker handles "
          f"~{(N/produce_s)*86400/1e6:,.0f}M/day vs the ~{daily/1e6:.0f}M/day Tier-A target")


if __name__ == "__main__":
    main()
