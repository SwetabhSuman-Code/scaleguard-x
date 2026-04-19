# Test Results Template — Copy This After Each Load Test

```markdown
# Load Test Results — [TEST NAME] — [DATE: YYYY-MM-DD HH:MM]

## Test Configuration
**Test Type:** ☐ Gradual Ramp  ☐ Spike  ☐ Sustained Load

**Duration:** _____ minutes

**Peak Concurrent Users:** _____ users

**Spawn Rate:** _____ users/second

**Target Endpoint:** POST /api/metrics

**Total Requests Sent:** _____ requests

**Unique Node IDs Simulated:** _____ nodes

**Command Used:**
\`\`\`bash
locust -f benchmarks/locustfile.py -u ____ -r ____ -t ____m --host http://localhost:8000 --web
\`\`\`

---

## Performance Metrics

### Request Handling
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Average Response Time | _____ ms | < 200ms | ☐ Pass ☐ Fail |
| P50 (Median) Latency | _____ ms | < 150ms | ☐ Pass ☐ Fail |
| P95 Latency | _____ ms | < 500ms | ☐ Pass ☐ Fail |
| P99 Latency | _____ ms | < 1000ms | ☐ Pass ☐ Fail |
| Max Latency | _____ ms | < 5000ms | ☐ Pass ☐ Fail |
| Min Latency | _____ ms | > 1ms | ☐ Pass ☐ Fail |

### Errors & Reliability
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Total Requests | _____ | — | — |
| Successful (2xx) | _____ | > 99% | ☐ Pass ☐ Fail |
| Client Errors (4xx) | _____ | < 1% | ☐ Pass ☐ Fail |
| Server Errors (5xx) | _____ | 0% | ☐ Pass ☐ Fail |
| Error Rate | _____ % | < 1% | ☐ Pass ☐ Fail |
| Failed Requests | _____ | 0 | ☐ Pass ☐ Fail |

### Throughput
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Peak Requests/sec | _____ req/sec | > 2000 | ☐ Pass ☐ Fail |
| Average Requests/sec | _____ req/sec | > 1500 | ☐ Pass ☐ Fail |
| Total Metrics Ingested | _____ | = Total Requests | ☐ Pass ☐ Fail |

---

## Resource Utilization

### CPU & Memory
| Resource | Peak | Baseline | Avg | Status |
|----------|------|----------|-----|--------|
| API Gateway CPU | _____ % | _____ % | _____ % | ☐ Healthy |
| API Gateway Memory | _____ MB | _____ MB | _____ MB | ☐ Healthy |
| PostgreSQL CPU | _____ % | _____ % | _____ % | ☐ Healthy |
| PostgreSQL Memory | _____ MB | _____ MB | _____ MB | ☐ Healthy |
| Redis Memory | _____ MB | _____ MB | _____ MB | ☐ Healthy |

### Connections & Queues
| Metric | Peak | Safe Limit | Status |
|--------|------|-----------|--------|
| Active DB Connections | _____ | < 50 | ☐ Healthy |
| Redis Connected Clients | _____ | < 100 | ☐ Healthy |
| Metrics Queue Depth | _____ | < 1000 | ☐ Healthy |

### Memory Leak Detection
- Baseline Memory (start): _____ MB
- Peak Memory (during): _____ MB
- Final Memory (end): _____ MB
- Memory Growth: _____ MB
- **Leak Detected?** ☐ No ☐ Yes (investigate)

---

## Database Performance

### Metrics Stored
| Metric | Value |
|--------|-------|
| Total Metrics in DB | _____ |
| Metrics Added During Test | _____ |
| Avg Insert Latency | _____ ms |
| Max Query Time | _____ ms |
| Query Timeout Errors | _____ |

### Sample Query Times
```sql
-- Count metrics ingested during test window
SELECT COUNT(*) FROM metrics WHERE created_at > NOW() - INTERVAL '15 minutes';
Result: _____

-- Check latest timestamp
SELECT MAX(created_at) FROM metrics;
Result: _____
```

---

## Autoscaler Behavior (If Applicable)

### Scaling Events
| Event | Count | Timing | Status |
|-------|-------|--------|--------|
| Scale-Up Triggered | _____ | After _____ seconds of spike | ☐ Good |
| Scale-Down Triggered | _____ | After _____ seconds of load drop | ☐ Good |
| Total Workers at Peak | _____ | (started at _____) | ☐ Expected |

### Latency Recovery
- Latency before spike: _____ ms
- Latency at spike peak: _____ ms
- Latency after scaling: _____ ms (time to recover: _____ seconds)
- **Scale-up response time:** ☐ < 1 minute ☐ 1-2 minutes ☐ > 2 minutes

---

## System Behavior Observations

### What Worked Well
- ☐ All requests completed successfully
- ☐ Latency remained stable under load
- ☐ Autoscaler responded quickly
- ☐ Database didn't hit connection limits
- ☐ No memory leaks detected
- ☐ Error rate stayed at 0%
- ☐ [Other] _________________________________

### Issues Encountered
- ☐ None detected ✅
- ☐ [Issue 1] _________________________________
- ☐ [Issue 2] _________________________________
- ☐ [Issue 3] _________________________________

### Error Details (If Any)
```
Error Type: _________________
Count: _____
First Seen: _____
Last Seen: _____
Likely Cause: _________________
Resolution: _________________
```

---

## Grafana Observations

### Dashboards Checked
- ☐ System Health Overview
- ☐ Resource Usage
- ☐ Autoscaler Activity
- ☐ Database Performance

### Notable Patterns
- CPU scaling: Linear ☐ Exponential ☐ Plateau ☐ Other: _____
- Memory trend: Stable ☐ Leaking ☐ Fluctuating ☐
- Latency under load: Steady ☐ Degrading ☐ Spiking ☐
- Auto-scaling response: Immediate ☐ Delayed ☐ Slow ☐

### Screenshots Saved
- [ ] Grafana dashboard during peak load
- [ ] Request rate chart
- [ ] Latency chart
- [ ] Resource usage chart
- [ ] Autoscaler scaling events

---

## Comparison to Previous Tests

### vs. Test #______ (Date: ________)
| Metric | Previous | This Test | Change | Trend |
|--------|----------|-----------|--------|-------|
| P95 Latency | _____ ms | _____ ms | _____ ms | ☐ Better ☐ Worse ☐ Same |
| Error Rate | _____ % | _____ % | _____ % | ☐ Better ☐ Worse ☐ Same |
| Throughput | _____ | _____ | _____ | ☐ Better ☐ Worse ☐ Same |
| Memory Used | _____ MB | _____ MB | _____ MB | ☐ Better ☐ Worse ☐ Same |

**Analysis:**
_________________________________________________________________
_________________________________________________________________

---

## Key Findings

### ✅ System Capabilities
- Maximum sustained throughput: **_____ req/sec**
- Maximum burst throughput: **_____ req/sec**
- Max concurrent users before degradation: **_____ users**
- Acceptable latency ceiling: **_____ ms (P95)**

### ⚠️ Bottlenecks Identified
1. _________________________________
2. _________________________________
3. _________________________________

### 📈 Scaling Characteristics
- **Horizontal:** ☐ Good ☐ Needs Work
- **Vertical:** ☐ Good ☐ Needs Work
- **Response Time:** Linear ☐ Exponential ☐ Other: _____

---

## Recommendations

### Immediate Actions
- [ ] _________________________________ (Priority: High ☐ Medium ☐ Low)
- [ ] _________________________________ (Priority: High ☐ Medium ☐ Low)
- [ ] _________________________________ (Priority: High ☐ Medium ☐ Low)

### Optimizations for Next Cycle
1. **Cache layer:** ☐ Implement ☐ Already done ☐ Not needed
2. **Database indexing:** ☐ Optimize ☐ Already done ☐ Not needed
3. **Connection pooling:** ☐ Increase pool size ☐ Already optimal
4. **Batch processing:** ☐ Implement ☐ Already done ☐ Not needed

### Production Readiness
- Handles peak expected load: ☐ Yes ☐ No ☐ Marginal
- Auto-scaling works reliably: ☐ Yes ☐ No ☐ Needs testing
- Error handling adequate: ☐ Yes ☐ No ☐ Partial
- Monitoring coverage: ☐ Complete ☐ Partial ☐ Needs work

---

## Files & Artifacts

### Saved Results
- Locust stats CSV: `benchmarks/results/load_test_[TIMESTAMP]_stats.csv`
- Locust history CSV: `benchmarks/results/load_test_[TIMESTAMP]_stats_history.csv`
- Failures log: `benchmarks/results/load_test_[TIMESTAMP]_failures.csv`

### Grafana Snapshots
- Dashboard snapshot URL: ___________________
- Screenshot files: [List files saved]

### Prometheus Export
- Query results: [Where stored or attached]
- Raw metrics file: [Location]

---

## Sign-off

**Test Conducted By:** ___________________
**Date:** _____________________
**Time Spent:** _____ hours
**Overall Result:** ☐ PASS ☐ FAIL ☐ CONDITIONAL PASS

**Notes & Follow-up:**
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________

```

---

## How to Use This Template

1. **Copy this entire template** into a new file after each test
2. **Fill in values** as you observe them during the test
3. **Save as:** `TEST_RESULTS_[TYPE]_[DATE].md` (e.g., `TEST_RESULTS_SPIKE_2026-04-19.md`)
4. **Store in:** `benchmarks/results/`
5. **Create GitHub issue** linking results if issues found
6. **Use for resume** — screenshots + summary of results

## Example Filled Test Result

```markdown
# Load Test Results — Gradual Ramp — 2026-04-19 14:30

## Test Configuration
**Test Type:** ☐ Gradual Ramp  ☒ Spike  ☐ Sustained Load
**Duration:** 10 minutes
**Peak Concurrent Users:** 300 users
**Spawn Rate:** 10 users/second
**Total Requests Sent:** 145,287 requests

## Performance Metrics
### Request Handling
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Average Response Time | 147 ms | < 200ms | ✅ Pass |
| P95 Latency | 289 ms | < 500ms | ✅ Pass |
| P99 Latency | 418 ms | < 1000ms | ✅ Pass |
| Error Rate | 0.03% | < 1% | ✅ Pass |

... [continue filling in]
```
