#!/usr/bin/env python3
"""Generator for cache-ttl-stampede scenario telemetry (metrics.csv, logs.ndjson).

Timeline (UTC, 2026-07-11):
  12:00 - 13:12  baseline: cache_hit_ratio ~0.97, db_cpu ~24%, db_qps ~410, catalog p99 ~60ms
  13:12          catalogservice deploy ships the cache-TTL drop (15m -> 15s)
  13:12 - ~13:40 DELAYED decay: warm 15m entries expire over minutes; hit_ratio decays
                 0.97 -> ~0.28; db_qps & db_cpu & catalog p99 climb gradually
  ~13:40         onset: productdb db_cpu_utilization crosses 85% threshold
  13:46          monitor fires (the page is on productdb)
"""
import csv
import json
import random
import datetime as dt

random.seed(71113)

START = dt.datetime(2026, 7, 11, 12, 0, 0, tzinfo=dt.timezone.utc)
TTL_DEPLOY = dt.datetime(2026, 7, 11, 13, 12, 0, tzinfo=dt.timezone.utc)
END = dt.datetime(2026, 7, 11, 14, 5, 0, tzinfo=dt.timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def jit(base, frac):
    return base * (1 + random.uniform(-frac, frac))


# Decay model: warm cache entries were written with a 15m TTL before 13:12.
# After the TTL drop to 15s, no NEW entry survives long, but the existing warm
# set keeps serving hits until each entry's original 15m expiry elapses. So the
# effective hit ratio decays roughly linearly from full-warm to cold over ~15min
# of expiries plus churn, bottoming out around 13:35-13:40.
DECAY_START = TTL_DEPLOY
# Warm entries carry their original 15m TTL, so hits keep being served for a while
# after the change; the effective hit ratio bleeds down over ~28 minutes and
# settles cold around 13:40.
DECAY_END = dt.datetime(2026, 7, 11, 13, 40, 0, tzinfo=dt.timezone.utc)

BASE_HIT = 0.97
COLD_HIT = 0.55          # steady-state with a 15s TTL under this read pattern
BASE_CPU = 24.0          # productdb cpu %
BASE_CATALOG_P99 = 60.0  # catalogservice http p99 ms
BASE_FRONT_ERR = 0.004

# Read request rate hitting catalogservice (req/s) - roughly steady all window.
READ_RPS = 1300.0
QPS_FLOOR = 120.0        # writes + uncacheable traffic that always hit the DB
BASE_MISS = 1.0 - BASE_HIT


def hit_ratio_at(t):
    if t < DECAY_START:
        return jit(BASE_HIT, 0.01)
    if t >= DECAY_END:
        return jit(COLD_HIT, 0.03)
    frac = (t - DECAY_START).total_seconds() / (DECAY_END - DECAY_START).total_seconds()
    # near-linear bleed-down as the warm 15m entries expire in waves
    val = BASE_HIT + (COLD_HIT - BASE_HIT) * frac
    return jit(val, 0.012)


def derive(t):
    hr = hit_ratio_at(t)
    # DB QPS is proportional to cache MISS rate: misses fall through to productdb.
    miss = 1.0 - hr
    qps = QPS_FLOOR + READ_RPS * miss
    qps = jit(qps, 0.025)
    # CPU rises ~linearly with qps and only bends up near the top (IO/lock contention).
    base_qps = QPS_FLOOR + READ_RPS * BASE_MISS
    load = qps / base_qps  # ~1.0 at baseline
    cpu = BASE_CPU * (load ** 0.92)
    cpu = min(96.0, jit(cpu, 0.025))
    # productdb query latency p99 climbs, sharply once cpu pushes past ~82%.
    db_p99 = 5.0 + 0.03 * qps + (max(0.0, cpu - 82.0) ** 1.7) * 2.2
    db_p99 = jit(db_p99, 0.04)
    # catalogservice p99 = own overhead + read-through wait on db when miss.
    catalog_p99 = BASE_CATALOG_P99 + miss * 110.0 + max(0.0, db_p99 - 30.0) * 3.0
    catalog_p99 = jit(catalog_p99, 0.04)
    # frontend 5xx rises once catalog p99 blows past the 1500ms client timeout.
    if catalog_p99 > 1500:
        ferr = min(0.40, BASE_FRONT_ERR + (catalog_p99 - 1500) / 6000.0)
    else:
        ferr = jit(BASE_FRONT_ERR, 0.2)
    return hr, qps, cpu, db_p99, catalog_p99, ferr


rows = []
t = START
while t <= END:
    hr, qps, cpu, db_p99, catalog_p99, ferr = derive(t)
    ts = iso(t)
    rows.append((ts, "catalogservice", "cache_hit_ratio", round(hr, 4)))
    rows.append((ts, "productdb", "db_queries_per_second", round(qps, 1)))
    rows.append((ts, "productdb", "db_cpu_utilization", round(cpu, 1)))
    rows.append((ts, "productdb", "db_query_duration_p99_ms", round(db_p99, 1)))
    rows.append((ts, "catalogservice", "http_server_duration_p99_ms", round(catalog_p99, 1)))
    rows.append((ts, "frontend", "error_rate_5xx_ratio", round(ferr, 4)))
    t += dt.timedelta(minutes=1)

with open("environment/data/metrics.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["timestamp", "service", "metric", "value"])
    for r in rows:
        w.writerow(r)

# ---------------- logs.ndjson ----------------
# Baseline: catalogservice INFO "served catalog page" (cache hits), sparse.
# Post-decay: productdb WARN "slow query" + "high connection count", catalog WARN
# "cache miss fallthrough", upstream timeouts on frontend/searchservice late.
logs = []


def hexid(n=16):
    return "".join(random.choice("0123456789abcdef") for _ in range(n * 2))


# baseline heartbeat logs (INFO) across services, every ~1 min
t = START
svc_cycle = ["catalogservice", "frontend", "searchservice", "catalogservice"]
i = 0
while t < TTL_DEPLOY:
    s = svc_cycle[i % len(svc_cycle)]
    logs.append({"timestamp": iso(t), "service": s, "severity_text": "INFO",
                 "msg": "served catalog page", "http.route": "/api/catalog/item",
                 "trace_id": hexid()})
    i += 1
    t += dt.timedelta(minutes=1)

# during decay (13:13 - 13:39): increasing catalog cache-miss + db slow-query WARNs
t = dt.datetime(2026, 7, 11, 13, 16, 0, tzinfo=dt.timezone.utc)
while t < dt.datetime(2026, 7, 11, 13, 40, 0, tzinfo=dt.timezone.utc):
    hr = hit_ratio_at(t)
    n_warn = 1 + int((BASE_HIT - hr) * 8)  # more WARNs as hit ratio falls
    for k in range(n_warn):
        sec = random.randint(0, 59)
        tt = t.replace(second=sec)
        logs.append({"timestamp": iso(tt), "service": "catalogservice", "severity_text": "WARN",
                     "msg": "cache miss; read-through to productdb", "cache.key.kind": "catalog_item",
                     "http.route": "/api/catalog/item", "trace_id": hexid()})
    if hr < 0.7:
        tt = t.replace(second=random.randint(0, 59))
        logs.append({"timestamp": iso(tt), "service": "productdb", "severity_text": "WARN",
                     "msg": "slow query: SELECT * FROM catalog_items WHERE id=$1",
                     "db.rows": 1, "db.duration_ms": round(jit(derive(t)[3], 0.1), 1),
                     "trace_id": hexid()})
    t += dt.timedelta(minutes=2)

# onset+ (13:40 - 14:02): productdb high-cpu / connection saturation ERRORs,
# catalog slow, frontend & search upstream timeouts.
onset_events = []
t = dt.datetime(2026, 7, 11, 13, 40, 0, tzinfo=dt.timezone.utc)
while t < dt.datetime(2026, 7, 11, 14, 3, 0, tzinfo=dt.timezone.utc):
    cpu = derive(t)[2]
    # productdb slow-query / cpu saturation
    for k in range(random.randint(2, 4)):
        tt = t.replace(second=random.randint(0, 59))
        onset_events.append({"timestamp": iso(tt), "service": "productdb", "severity_text": "WARN",
                             "msg": "slow query: SELECT * FROM catalog_items WHERE id=$1",
                             "db.cpu_pct": round(cpu, 1), "db.duration_ms": round(jit(derive(t)[3], 0.1), 1),
                             "trace_id": hexid()})
    if cpu > 88:
        tt = t.replace(second=random.randint(0, 59))
        onset_events.append({"timestamp": iso(tt), "service": "productdb", "severity_text": "ERROR",
                             "msg": "statement timeout: query exceeded 3000ms under load",
                             "db.cpu_pct": round(cpu, 1), "trace_id": hexid()})
    # catalog read-through latency
    tt = t.replace(second=random.randint(0, 59))
    onset_events.append({"timestamp": iso(tt), "service": "catalogservice", "severity_text": "WARN",
                         "msg": "cache miss; read-through to productdb", "cache.key.kind": "catalog_item",
                         "http.route": "/api/catalog/item", "trace_id": hexid()})
    # upstream timeouts once catalog is slow
    if derive(t)[4] > 1200:
        for up in ("frontend", "searchservice"):
            if random.random() < 0.7:
                tt = t.replace(second=random.randint(0, 59))
                onset_events.append({"timestamp": iso(tt), "service": up, "severity_text": "ERROR",
                                     "msg": "upstream catalogservice timeout after 1500ms",
                                     "trace_id": hexid()})
    t += dt.timedelta(minutes=1)

logs.extend(onset_events)
logs.sort(key=lambda r: r["timestamp"])

with open("environment/data/logs.ndjson", "w") as f:
    for r in logs:
        f.write(json.dumps(r) + "\n")

# quick sanity dump
print("metrics rows:", len(rows), "logs:", len(logs))
for probe in ["12:00", "13:12", "13:20", "13:30", "13:40", "13:46", "14:00"]:
    hh, mm = probe.split(":")
    tt = dt.datetime(2026, 7, 11, int(hh), int(mm), 0, tzinfo=dt.timezone.utc)
    hr, qps, cpu, dbp, cp99, fe = derive(tt)
    print(f"{probe}  hit={hr:.2f} qps={qps:6.0f} cpu={cpu:5.1f} db_p99={dbp:7.1f} catalog_p99={cp99:7.1f} front_err={fe:.3f}")
