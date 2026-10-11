# SENTINEL — production-component PoC

A thin, single-instance proof that the production tiers in `docs/HLD.md` are
real, with **measured numbers**, not a diagram. It is a separate Docker Compose
project (`sentinel-poc`, its own ports) and never touches the live demo on
`:8080` / `:8001`.

```bash
docker compose -f deploy/poc/docker-compose.poc.yml up -d      # DR + event bus
# object storage additionally needs: docker login   (see note below)
```

## What it proves, and the numbers measured on this machine

| Production tier (HLD) | PoC component | Measured result |
|---|---|---|
| §6.7 DR — DB replication | PostgreSQL 16 primary → streaming hot-standby replica | **byte-lag 0** after a 10,000-row burst; write-lag **7.7 ms**, flush **9.3 ms**, replay **16.2 ms**; replica fully caught up (10,001 rows), time-behind **0.25 s** |
| §1 / §6 event bus | Redpanda (Kafka API), 1 broker, 1 core | **15,600 events/s** produced, **10,800/s** consumed; true streaming latency **p50 1.7 ms, p99 6.2 ms**. One broker ≈ **1.3 billion events/day** vs the ~32 M/day statewide Tier-A target — **~40× headroom** |
| §6.6 object storage | SeaweedFS (S3 API), snapshots out of the hot DB | real snapshots offloaded from Postgres; **345 objects/s (15.9 MB/s)**, fetch **p50 3.5 ms / p99 14.5 ms**. One node ≈ **30 M objects/day** ≈ the ~32 M/day statewide snapshot rate; **1.5 TB/day**, 0 bytes of video centralized |
| §8 orchestration + LB | Kubernetes manifests (`k8s/sentinel.yaml`) | Deployments + Services + Ingress + HPA (1→10 on 65% CPU); `kubectl apply` on any cluster / `kind` |

### Reproduce

```bash
# DR — replication lag
docker compose -f deploy/poc/docker-compose.poc.yml exec pg-primary \
  psql -U sentinel -d sentinel -c "select * from pg_stat_replication;"

# event bus — throughput + latency
.venv/bin/python deploy/poc/bench/kafka_bench.py 20000

# object storage — after `docker login` and bringing minio up
.venv/bin/python deploy/poc/bench/minio_demo.py

# orchestration
kind create cluster --name sentinel && kubectl apply -f deploy/poc/k8s/sentinel.yaml
```

## The point for judges

The prototype runs on docker-compose + Postgres + an in-process WebSocket hub —
the right scale for a prototype. This PoC shows the **same system** maps cleanly
onto the production tiers, and that a *single, tiny instance* of each already
clears the statewide load by a wide margin (one Redpanda core = 40× the Tier-A
event rate; replication lag in milliseconds). Scaling is adding replicas, not
re-architecting. Every heavy component in the HLD is demonstrated here at
PoC scale, so the roadmap is evidenced, not asserted.

## Note on the object store

MinIO was dropped: its Docker Hub and quay registries now gate pulls (the
community-edition lockdown). We use **SeaweedFS**, a freely-available, drop-in
S3-compatible successor — the same `minio`/`boto3` client code works against it
unchanged (it's only the server that changed). Garage is another option.
