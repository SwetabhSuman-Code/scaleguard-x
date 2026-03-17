/**
 * ScaleGuard X Dashboard — Main App Component
 * Full real-time monitoring dashboard using Chart.js + react-chartjs-2
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, ArcElement, Tooltip, Legend, Filler,
} from 'chart.js'
import { Line, Bar } from 'react-chartjs-2'

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, ArcElement, Tooltip, Legend, Filler
)

// ── API Base (proxied through Vite dev server or Nginx in prod) ──
const API = '/api'

// ── Fetch helper ─────────────────────────────────────────────────
const apiFetch = async (path) => {
  try {
    const res = await fetch(`${API}${path}`)
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

// ── Chart defaults ────────────────────────────────────────────────
const chartDefaults = {
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 400 },
  plugins: {
    legend: {
      labels: {
        color: '#94a3b8',
        font: { size: 11, family: 'Inter' },
        boxWidth: 10,
        padding: 12,
      }
    },
    tooltip: {
      backgroundColor: '#0f1520',
      borderColor: 'rgba(255,255,255,0.1)',
      borderWidth: 1,
      titleColor: '#f1f5f9',
      bodyColor: '#94a3b8',
      padding: 10,
    }
  },
  scales: {
    x: {
      grid: { color: 'rgba(255,255,255,0.04)' },
      ticks: { color: '#475569', font: { size: 10, family: 'JetBrains Mono' }, maxTicksLimit: 8 },
    },
    y: {
      grid: { color: 'rgba(255,255,255,0.04)' },
      ticks: { color: '#475569', font: { size: 10, family: 'JetBrains Mono' } },
    }
  }
}

// ── Helpers ───────────────────────────────────────────────────────
const fmt  = (n, d = 1) => (n ?? 0).toFixed(d)
const tsLabel = (ts) => new Date(ts).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })

// ── KピCard ───────────────────────────────────────────────────────
function KpiCard({ label, value, sub, icon, gradient, color }) {
  return (
    <div className="kpi-card" style={{ '--kpi-gradient': gradient, '--kpi-color': color }}>
      <div className="kpi-icon">{icon}</div>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  )
}

// ── Chart Card wrapper ────────────────────────────────────────────
function ChartCard({ title, sub, badge, badgeClass, children }) {
  return (
    <div className="chart-card">
      <div className="chart-header">
        <div>
          <div className="chart-title">{title}</div>
          {sub && <div className="chart-sub">{sub}</div>}
        </div>
        {badge && <span className={`chart-badge ${badgeClass}`}>{badge}</span>}
      </div>
      <div className="chart-wrap">{children}</div>
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────────────
export default function App() {
  const [status,     setStatus]     = useState(null)
  const [metrics,    setMetrics]    = useState([])
  const [anomalies,  setAnomalies]  = useState([])
  const [predictions,setPredictions]= useState([])
  const [scaling,    setScaling]    = useState([])
  const [alerts,     setAlerts]     = useState([])
  const [workers,    setWorkers]    = useState([])
  const [loading,    setLoading]    = useState(true)
  const [lastUpdate, setLastUpdate] = useState(null)

  // Keep a rolling 50-point history per metric for charts
  const historyRef = useRef({ cpu: [], mem: [], rps: [], lat: [], labels: [] })

  const refresh = useCallback(async () => {
    const [st, mx, an, pr, sc, al, wk] = await Promise.all([
      apiFetch('/status'),
      apiFetch('/metrics?minutes=10&limit=300'),
      apiFetch('/anomalies?minutes=30&limit=20'),
      apiFetch('/predictions?limit=15'),
      apiFetch('/scaling?limit=15'),
      apiFetch('/alerts?minutes=60&limit=20'),
      apiFetch('/workers'),
    ])

    if (st) setStatus(st)
    if (an) setAnomalies(an)
    if (pr) setPredictions(pr)
    if (sc) setScaling(sc)
    if (al) setAlerts(al)
    if (wk) setWorkers(wk)

    if (mx && mx.length > 0) {
      // Group by minute-ish and take latest value per label
      const sorted = [...mx].reverse()
      const seen = new Set()
      const deduped = sorted.filter(m => {
        const key = tsLabel(m.timestamp)
        if (seen.has(key)) return false
        seen.add(key)
        return true
      }).slice(-50)

      const H = historyRef.current
      H.labels = deduped.map(m => tsLabel(m.timestamp))
      H.cpu    = deduped.map(m => m.cpu_usage)
      H.mem    = deduped.map(m => m.memory_usage)
      H.rps    = deduped.map(m => m.requests_per_sec)
      H.lat    = deduped.map(m => m.latency_ms)
      setMetrics([...deduped])
    }

    setLastUpdate(new Date().toLocaleTimeString())
    setLoading(false)
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 5000)
    return () => clearInterval(id)
  }, [refresh])

  // ── Chart data builders ───────────────────────────────────────
  const H = historyRef.current

  const lineDs = (label, data, color, fill = true) => ({
    label,
    data,
    borderColor: color,
    backgroundColor: fill ? color.replace(')', ', 0.12)').replace('rgb', 'rgba') : 'transparent',
    borderWidth: 2,
    pointRadius: 0,
    tension: 0.4,
    fill,
  })

  const cpuData = {
    labels: H.labels,
    datasets: [lineDs('CPU %', H.cpu, '#3b82f6')],
  }
  const memData = {
    labels: H.labels,
    datasets: [lineDs('Memory %', H.mem, '#a855f7')],
  }
  const rpsData = {
    labels: H.labels,
    datasets: [lineDs('Req/s', H.rps, '#06b6d4')],
  }
  const latData = {
    labels: H.labels,
    datasets: [lineDs('Latency ms', H.lat, '#f59e0b')],
  }

  // Scaling history bar chart
  const scalingChartData = {
    labels: [...scaling].reverse().map(s => tsLabel(s.triggered_at)),
    datasets: [{
      label: 'Worker Count',
      data: [...scaling].reverse().map(s => s.new_replicas),
      backgroundColor: [...scaling].reverse().map(s =>
        s.action === 'scale_up'   ? 'rgba(34,197,94,0.7)'  :
        s.action === 'scale_down' ? 'rgba(239,68,68,0.7)'  :
                                    'rgba(100,116,139,0.5)'
      ),
      borderRadius: 4,
    }]
  }

  // Anomaly score over time
  const anomalyChartData = {
    labels: [...anomalies].reverse().map(a => tsLabel(a.detected_at)),
    datasets: [lineDs('Anomaly Score', [...anomalies].reverse().map(a => a.anomaly_score), '#ef4444', false)],
  }

  const lineOpts = (yMax) => ({
    ...chartDefaults,
    scales: {
      ...chartDefaults.scales,
      y: { ...chartDefaults.scales.y, min: 0, max: yMax }
    }
  })

  const barOpts = {
    ...chartDefaults,
    plugins: { ...chartDefaults.plugins, legend: { display: false } },
    scales: { ...chartDefaults.scales, y: { ...chartDefaults.scales.y, min: 0 } }
  }

  return (
    <div className="dashboard">
      {/* ── Header ───────────────────────────────────────────────── */}
      <header className="header">
        <div className="header-brand">
          <div className="logo-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/>
              <path d="M2 17l10 5 10-5"/>
              <path d="M2 12l10 5 10-5"/>
            </svg>
          </div>
          <div>
            <div className="brand-name">ScaleGuard X</div>
            <div className="brand-sub">Infrastructure Monitoring &amp; Autoscaling</div>
          </div>
        </div>
        <div className="header-meta">
          <div className="status-pill">
            <span className="status-dot"/>
            OPERATIONAL
          </div>
          {lastUpdate && <span className="last-updated">Updated {lastUpdate}</span>}
          <button className="refresh-btn" onClick={refresh}>↺ Refresh</button>
        </div>
      </header>

      {/* ── Main ─────────────────────────────────────────────────── */}
      <div className="main-content">
        {loading ? (
          <div className="loading-state">
            <div className="spinner"/>
            Connecting to ScaleGuard X API…
          </div>
        ) : (
          <>
            {/* ── KPI Row ──────────────────────────────────────────── */}
            <p className="section-title">System Overview</p>
            <div className="kpi-row">
              <KpiCard
                label="Active Workers"
                value={status?.active_workers ?? '—'}
                sub={`${status?.nodes_reporting ?? 0} nodes reporting`}
                icon="⚙️"
                gradient="linear-gradient(90deg,#22c55e,#06b6d4)"
                color="var(--accent-green)"
              />
              <KpiCard
                label="Avg CPU"
                value={`${fmt(metrics[0]?.cpu_usage)}%`}
                sub="Across all nodes"
                icon="🖥️"
                gradient="linear-gradient(90deg,#3b82f6,#6366f1)"
                color="var(--accent-blue)"
              />
              <KpiCard
                label="Avg Memory"
                value={`${fmt(metrics[0]?.memory_usage)}%`}
                sub="RAM utilization"
                icon="💾"
                gradient="linear-gradient(90deg,#a855f7,#ec4899)"
                color="var(--accent-purple)"
              />
              <KpiCard
                label="Latency"
                value={`${fmt(metrics[0]?.latency_ms)} ms`}
                sub="p50 response time"
                icon="⚡"
                gradient="linear-gradient(90deg,#f59e0b,#ef4444)"
                color="var(--accent-amber)"
              />
              <KpiCard
                label="Req / sec"
                value={fmt(metrics[0]?.requests_per_sec)}
                sub="Current throughput"
                icon="📈"
                gradient="linear-gradient(90deg,#06b6d4,#3b82f6)"
                color="var(--accent-cyan)"
              />
              <KpiCard
                label="Predicted RPS"
                value={fmt(status?.predicted_rps)}
                sub={`Next ${10} min forecast`}
                icon="🔮"
                gradient="linear-gradient(90deg,#8b5cf6,#06b6d4)"
                color="#8b5cf6"
              />
              <KpiCard
                label="Anomaly Score"
                value={fmt(status?.latest_anomaly_score, 3)}
                sub="0 = normal, 1 = severe"
                icon="🚨"
                gradient="linear-gradient(90deg,#ef4444,#f59e0b)"
                color="var(--accent-red)"
              />
            </div>

            {/* ── Charts ───────────────────────────────────────────── */}
            <p className="section-title">Metrics Timeline</p>
            <div className="charts-grid">
              <ChartCard title="CPU Usage" sub="Percent utilization over time" badge="Real-time" badgeClass="badge-blue">
                <Line data={cpuData} options={lineOpts(100)} />
              </ChartCard>
              <ChartCard title="Memory Usage" sub="RAM consumption across nodes" badge="Real-time" badgeClass="badge-purple">
                <Line data={memData} options={lineOpts(100)} />
              </ChartCard>
              <ChartCard title="Request Throughput" sub="Requests per second" badge="RPS" badgeClass="badge-cyan">
                <Line data={rpsData} options={lineOpts(undefined)} />
              </ChartCard>
              <ChartCard title="Response Latency" sub="Milliseconds (p50)" badge="ms" badgeClass="badge-amber">
                <Line data={latData} options={lineOpts(undefined)} />
              </ChartCard>
            </div>

            {/* ── Analytics Charts ──────────────────────────────────── */}
            <p className="section-title">Analytics</p>
            <div className="charts-grid">
              <ChartCard title="Scaling History" sub="Worker replica changes" badge="Docker" badgeClass="badge-green">
                <Bar data={scalingChartData} options={barOpts} />
              </ChartCard>
              <ChartCard title="Anomaly Scores" sub="Detected anomalies over time" badge="ML+Rules" badgeClass="badge-red">
                <Line data={anomalyChartData} options={{
                  ...lineOpts(1),
                  scales: { ...lineOpts(1).scales, y: { ...lineOpts(1).scales.y, max: 1 } }
                }} />
              </ChartCard>
            </div>

            {/* ── Bottom row ────────────────────────────────────────── */}
            <p className="section-title">Infrastructure Status</p>
            <div className="bottom-row">

              {/* Workers */}
              <div className="table-card">
                <div className="table-card-header">
                  <span className="table-card-title">⚙️ Worker Nodes</span>
                  <span className="chart-badge badge-green">{workers.filter(w=>w.status==='active').length} active</span>
                </div>
                <div className="workers-grid">
                  {workers.length === 0 && <div className="empty-state">No workers registered</div>}
                  {workers.slice(0, 8).map(w => (
                    <div className="worker-row" key={w.worker_id}>
                      <span className={`worker-dot dot-${w.status}`}/>
                      <span className="worker-id">{w.worker_id}</span>
                      <span className={`worker-status status-${w.status}`}>{w.status}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Alerts */}
              <div className="table-card">
                <div className="table-card-header">
                  <span className="table-card-title">🚨 Recent Alerts</span>
                  <span className="chart-badge badge-red">{alerts.filter(a=>!a.resolved).length} open</span>
                </div>
                {alerts.length === 0 && <div className="empty-state">No recent alerts</div>}
                {alerts.slice(0, 8).map(a => (
                  <div className="alert-row" key={a.id}>
                    <span className={`alert-sev sev-${a.severity}`}>{a.severity}</span>
                    <span className="alert-msg">{a.message}</span>
                    <span className="alert-time">{tsLabel(a.raised_at)}</span>
                  </div>
                ))}
              </div>

              {/* Scaling events table */}
              <div className="table-card">
                <div className="table-card-header">
                  <span className="table-card-title">📊 Scaling Events</span>
                </div>
                <div className="table-inner">
                  <table>
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>Action</th>
                        <th>Workers</th>
                      </tr>
                    </thead>
                    <tbody>
                      {scaling.length === 0 && (
                        <tr><td colSpan="3" style={{textAlign:'center',color:'var(--text-muted)'}}>No events yet</td></tr>
                      )}
                      {scaling.slice(0, 10).map(ev => (
                        <tr key={ev.id}>
                          <td>{tsLabel(ev.triggered_at)}</td>
                          <td>
                            <span className={`chart-badge ${
                              ev.action === 'scale_up'   ? 'badge-green' :
                              ev.action === 'scale_down' ? 'badge-red'   :
                                                           'badge-cyan'
                            }`}>{ev.action.replace('_',' ')}</span>
                          </td>
                          <td>{ev.prev_replicas} → {ev.new_replicas}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            {/* ── Anomaly table ─────────────────────────────────────── */}
            <p className="section-title">Anomaly Log</p>
            <div className="table-card" style={{marginBottom:28}}>
              <div className="table-inner">
                <table>
                  <thead>
                    <tr>
                      <th>Time</th><th>Node</th><th>Type</th><th>Metric</th><th>Value</th><th>Score</th><th>Description</th>
                    </tr>
                  </thead>
                  <tbody>
                    {anomalies.length === 0 && (
                      <tr><td colSpan="7" style={{textAlign:'center',color:'var(--text-muted)'}}>No anomalies detected</td></tr>
                    )}
                    {anomalies.map(a => (
                      <tr key={a.id}>
                        <td>{tsLabel(a.detected_at)}</td>
                        <td>{a.node_id}</td>
                        <td><span className={`chart-badge ${a.anomaly_type==='rule_based'?'badge-amber':'badge-red'}`}>{a.anomaly_type}</span></td>
                        <td>{a.metric_name}</td>
                        <td>{fmt(a.metric_value, 2)}</td>
                        <td style={{color: a.anomaly_score > 0.7 ? 'var(--accent-red)' : 'var(--accent-amber)'}}>
                          {fmt(a.anomaly_score, 3)}
                        </td>
                        <td style={{color:'var(--text-muted)', fontSize:11}}>{a.description?.slice(0,80)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
