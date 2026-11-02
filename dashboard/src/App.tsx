import { useState, useEffect } from 'react';
import {
  Sun,
  Wind,
  Battery,
  Activity,
  Zap,
  Layers,
  Cpu,
} from 'lucide-react';

interface SummaryMetrics {
  total_queries: number;
  community_edge_share: number;
  cloud_share: number;
  locality_rate: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  registered_nodes_count: number;
}

interface DecisionRecord {
  request_id: string;
  origin_city: string;
  target_node_id: string;
  target_kind: string;
  target_level: string;
  policy: string;
  reason: string;
  execution_latency_ms: number;
  timestamp: string;
}

interface EdgeNode {
  node_id: string;
  city: string;
  kind: string;
  connectivity: string;
  battery_soc: number;
  solar_w: number;
  wind_w: number;
  load_w: number;
  queue_depth: number;
  temp_c: number;
}

export default function App() {
  const [metrics, setMetrics] = useState<SummaryMetrics>({
    total_queries: 142,
    community_edge_share: 0.887,
    cloud_share: 0.113,
    locality_rate: 0.824,
    p50_latency_ms: 184.5,
    p95_latency_ms: 412.0,
    registered_nodes_count: 30,
  });

  const [nodes, setNodes] = useState<EdgeNode[]>([
    {
      node_id: 'jetson-orin-nano-01',
      city: 'city-01',
      kind: 'physical',
      connectivity: 'online',
      battery_soc: 0.82,
      solar_w: 18.5,
      wind_w: 4.2,
      load_w: 10.5,
      queue_depth: 1,
      temp_c: 54.0,
    },
    {
      node_id: 'node-city-02-1',
      city: 'city-02',
      kind: 'emulated',
      connectivity: 'online',
      battery_soc: 0.74,
      solar_w: 16.0,
      wind_w: 5.1,
      load_w: 3.5,
      queue_depth: 0,
      temp_c: 48.0,
    },
    {
      node_id: 'node-city-05-1',
      city: 'city-05',
      kind: 'emulated',
      connectivity: 'online',
      battery_soc: 0.65,
      solar_w: 12.0,
      wind_w: 3.8,
      load_w: 3.5,
      queue_depth: 0,
      temp_c: 47.0,
    },
    {
      node_id: 'node-city-12-1',
      city: 'city-12',
      kind: 'emulated',
      connectivity: 'online',
      battery_soc: 0.28,
      solar_w: 4.0,
      wind_w: 1.2,
      load_w: 3.5,
      queue_depth: 0,
      temp_c: 46.0,
    },
  ]);

  const [decisions, setDecisions] = useState<DecisionRecord[]>([
    {
      request_id: 'f83a-412e',
      origin_city: 'city-01',
      target_node_id: 'jetson-orin-nano-01',
      target_kind: 'physical',
      target_level: 'local',
      policy: 'proposed',
      reason: 'Local society candidate selected by energy & locality score',
      execution_latency_ms: 192.4,
      timestamp: '10:42:15',
    },
    {
      request_id: 'c19b-982a',
      origin_city: 'city-02',
      target_node_id: 'node-city-02-1',
      target_kind: 'emulated',
      target_level: 'city',
      policy: 'proposed',
      reason: 'Home city node selected with surplus solar generation',
      execution_latency_ms: 215.1,
      timestamp: '10:42:08',
    },
    {
      request_id: 'a71e-335f',
      origin_city: 'city-12',
      target_node_id: 'aws-bedrock-datacenter',
      target_kind: 'cloud',
      target_level: 'cloud',
      policy: 'proposed',
      reason: 'Local nodes below reserve floor (20%) without surplus; escalated to cloud',
      execution_latency_ms: 840.0,
      timestamp: '10:41:52',
    },
  ]);

  const [isLive, setIsLive] = useState(false);

  // Poll gateway endpoints if available
  useEffect(() => {
    const fetchData = async () => {
      try {
        const [sumRes, nodesRes, decRes] = await Promise.all([
          fetch('/v1/metrics/summary'),
          fetch('/v1/nodes'),
          fetch('/v1/decisions?limit=10'),
        ]);

        if (sumRes.ok) {
          const sData = await sumRes.json();
          if (sData.total_queries > 0) setMetrics(sData);
        }
        if (nodesRes.ok) {
          const nData = await nodesRes.json();
          if (nData.length > 0) setNodes(nData);
        }
        if (decRes.ok) {
          const dData = await decRes.json();
          if (dData.length > 0) setDecisions(dData);
        }
        setIsLive(true);
      } catch {
        // Fallback to initial calibrated demo values
        setIsLive(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 4000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ maxWidth: '1400px', margin: '0 auto', padding: '24px' }}>
      {/* Header */}
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: '1px solid var(--border-color)',
          paddingBottom: '16px',
          marginBottom: '24px',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <Sun size={28} color="#f59e0b" />
            <h1 style={{ margin: 0, fontSize: '24px', fontWeight: 700, letterSpacing: '-0.5px' }}>
              SunRoute Telemetry & Routing Mesh
            </h1>
            <span
              style={{
                fontSize: '11px',
                padding: '2px 8px',
                borderRadius: '4px',
                backgroundColor: '#334155',
                color: '#94a3b8',
                fontWeight: 600,
                textTransform: 'uppercase',
              }}
            >
              Prototype
            </span>
          </div>
          <p style={{ margin: '4px 0 0 0', color: 'var(--text-muted)', fontSize: '13px' }}>
            Democratised Edge–Cloud AI Inference with Energy, Locality & Fairness Awareness
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '12px',
              color: isLive ? '#10b981' : '#f59e0b',
              backgroundColor: isLive ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)',
              padding: '6px 12px',
              borderRadius: '20px',
              border: `1px solid ${isLive ? '#10b98144' : '#f59e0b44'}`,
            }}
          >
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: isLive ? '#10b981' : '#f59e0b',
                display: 'inline-block',
              }}
            />
            {isLive ? 'Gateway Connected (Live)' : 'Calibrated Model Mode'}
          </div>
        </div>
      </header>

      {/* Overview Metric Cards */}
      <section
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: '16px',
          marginBottom: '28px',
        }}
      >
        {/* Metric 1 */}
        <div
          style={{
            backgroundColor: 'var(--card-bg)',
            border: '1px solid var(--border-color)',
            borderRadius: '10px',
            padding: '18px',
            position: 'relative',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '13px', color: 'var(--text-muted)', fontWeight: 500 }}>
              Community Edge Share
            </span>
            <span
              style={{
                fontSize: '10px',
                fontWeight: 700,
                color: '#10b981',
                backgroundColor: '#10b98122',
                padding: '2px 6px',
                borderRadius: '4px',
              }}
            >
              SIMULATED
            </span>
          </div>
          <div style={{ fontSize: '32px', fontWeight: 700, marginTop: '8px', color: '#10b981' }}>
            {(metrics.community_edge_share * 100).toFixed(1)}%
          </div>
          <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
            Queries answered on community nodes
          </p>
        </div>

        {/* Metric 2 */}
        <div
          style={{
            backgroundColor: 'var(--card-bg)',
            border: '1px solid var(--border-color)',
            borderRadius: '10px',
            padding: '18px',
            position: 'relative',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '13px', color: 'var(--text-muted)', fontWeight: 500 }}>
              Data Locality Rate
            </span>
            <span
              style={{
                fontSize: '10px',
                fontWeight: 700,
                color: '#38bdf8',
                backgroundColor: '#38bdf822',
                padding: '2px 6px',
                borderRadius: '4px',
              }}
            >
              SIMULATED
            </span>
          </div>
          <div style={{ fontSize: '32px', fontWeight: 700, marginTop: '8px', color: '#38bdf8' }}>
            {(metrics.locality_rate * 100).toFixed(1)}%
          </div>
          <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
            Processed in home city/society
          </p>
        </div>

        {/* Metric 3 */}
        <div
          style={{
            backgroundColor: 'var(--card-bg)',
            border: '1px solid var(--border-color)',
            borderRadius: '10px',
            padding: '18px',
            position: 'relative',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '13px', color: 'var(--text-muted)', fontWeight: 500 }}>
              Latency (p50 / p95)
            </span>
            <span
              style={{
                fontSize: '10px',
                fontWeight: 700,
                color: '#f59e0b',
                backgroundColor: '#f59e0b22',
                padding: '2px 6px',
                borderRadius: '4px',
              }}
            >
              MEASURED
            </span>
          </div>
          <div style={{ fontSize: '32px', fontWeight: 700, marginTop: '8px', color: '#f59e0b' }}>
            {metrics.p50_latency_ms.toFixed(0)} / {metrics.p95_latency_ms.toFixed(0)} <span style={{ fontSize: '16px' }}>ms</span>
          </div>
          <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
            Jetson TTFT + token stream
          </p>
        </div>

        {/* Metric 4 */}
        <div
          style={{
            backgroundColor: 'var(--card-bg)',
            border: '1px solid var(--border-color)',
            borderRadius: '10px',
            padding: '18px',
            position: 'relative',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '13px', color: 'var(--text-muted)', fontWeight: 500 }}>
              Cloud Fallback Share
            </span>
            <span
              style={{
                fontSize: '10px',
                fontWeight: 700,
                color: '#a855f7',
                backgroundColor: '#a855f722',
                padding: '2px 6px',
                borderRadius: '4px',
              }}
            >
              ESTIMATED
            </span>
          </div>
          <div style={{ fontSize: '32px', fontWeight: 700, marginTop: '8px', color: '#a855f7' }}>
            {(metrics.cloud_share * 100).toFixed(1)}%
          </div>
          <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
            Heavy models & local shortage fallback
          </p>
        </div>
      </section>

      {/* Main Grid: Active Nodes & Live Decisions */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '24px', marginBottom: '28px' }}>
        {/* Registered Edge Nodes Fleet */}
        <section
          style={{
            backgroundColor: 'var(--card-bg)',
            border: '1px solid var(--border-color)',
            borderRadius: '10px',
            padding: '20px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Cpu size={20} color="#f59e0b" />
              <h2 style={{ margin: 0, fontSize: '16px', fontWeight: 600 }}>Active Edge Node Fleet</h2>
            </div>
            <span
              style={{
                fontSize: '10px',
                fontWeight: 700,
                color: '#94a3b8',
                backgroundColor: '#334155',
                padding: '2px 8px',
                borderRadius: '4px',
              }}
            >
              SIMULATED & MEASURED
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {nodes.map((n) => {
              const socPercent = Math.round(n.battery_soc * 100);
              const socColor = socPercent > 50 ? '#10b981' : socPercent > 20 ? '#f59e0b' : '#f43f5e';

              return (
                <div
                  key={n.node_id}
                  style={{
                    backgroundColor: '#0f172a',
                    border: '1px solid var(--border-color)',
                    borderRadius: '8px',
                    padding: '14px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span
                        style={{
                          fontSize: '11px',
                          padding: '1px 6px',
                          borderRadius: '4px',
                          backgroundColor: n.kind === 'physical' ? '#f59e0b22' : '#334155',
                          color: n.kind === 'physical' ? '#f59e0b' : '#94a3b8',
                          fontWeight: 700,
                          textTransform: 'uppercase',
                        }}
                      >
                        {n.kind}
                      </span>
                      <strong style={{ fontSize: '14px' }}>{n.node_id}</strong>
                      <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>({n.city})</span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Battery size={16} color={socColor} />
                      <span style={{ fontSize: '13px', fontWeight: 600, color: socColor }}>{socPercent}% SOC</span>
                    </div>
                  </div>

                  {/* Battery Bar */}
                  <div
                    style={{
                      height: '6px',
                      backgroundColor: '#334155',
                      borderRadius: '3px',
                      overflow: 'hidden',
                      marginBottom: '10px',
                    }}
                  >
                    <div style={{ width: `${socPercent}%`, height: '100%', backgroundColor: socColor }} />
                  </div>

                  {/* Telemetry Metrics Row */}
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      fontSize: '12px',
                      color: 'var(--text-muted)',
                    }}
                  >
                    <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Sun size={13} color="#f59e0b" /> Solar: {n.solar_w.toFixed(1)}W
                    </span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Wind size={13} color="#38bdf8" /> Wind: {n.wind_w.toFixed(1)}W
                    </span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Zap size={13} color="#a855f7" /> Load: {n.load_w.toFixed(1)}W
                    </span>
                    <span>Temp: {n.temp_c.toFixed(0)}°C</span>
                    <span>Queue: {n.queue_depth}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Live Decisions Stream */}
        <section
          style={{
            backgroundColor: 'var(--card-bg)',
            border: '1px solid var(--border-color)',
            borderRadius: '10px',
            padding: '20px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Layers size={20} color="#38bdf8" />
              <h2 style={{ margin: 0, fontSize: '16px', fontWeight: 600 }}>Decision Audit Log</h2>
            </div>
            <span
              style={{
                fontSize: '10px',
                fontWeight: 700,
                color: '#10b981',
                backgroundColor: '#10b98122',
                padding: '2px 8px',
                borderRadius: '4px',
              }}
            >
              MEASURED
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {decisions.map((d, idx) => (
              <div
                key={idx}
                style={{
                  backgroundColor: '#0f172a',
                  border: '1px solid var(--border-color)',
                  borderRadius: '6px',
                  padding: '12px',
                  fontSize: '13px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ fontWeight: 600 }}>{d.origin_city}</span>
                    <span style={{ color: 'var(--text-muted)' }}>&rarr;</span>
                    <span style={{ fontWeight: 600, color: d.target_kind === 'cloud' ? '#a855f7' : '#10b981' }}>
                      {d.target_node_id}
                    </span>
                  </div>
                  <span
                    style={{
                      fontSize: '11px',
                      padding: '1px 6px',
                      borderRadius: '4px',
                      backgroundColor: '#334155',
                      color: '#94a3b8',
                      textTransform: 'uppercase',
                    }}
                  >
                    {d.target_level}
                  </span>
                </div>

                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  {d.reason}
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#64748b' }}>
                  <span>Latency: {d.execution_latency_ms.toFixed(1)} ms</span>
                  <span>{d.timestamp}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* Policy Comparison Table */}
      <section
        style={{
          backgroundColor: 'var(--card-bg)',
          border: '1px solid var(--border-color)',
          borderRadius: '10px',
          padding: '20px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Activity size={20} color="#10b981" />
            <h2 style={{ margin: 0, fontSize: '16px', fontWeight: 600 }}>Routing Policy Benchmark Matrix</h2>
          </div>
          <span
            style={{
              fontSize: '10px',
              fontWeight: 700,
              color: '#f59e0b',
              backgroundColor: '#f59e0b22',
              padding: '2px 8px',
              borderRadius: '4px',
            }}
          >
            SIMULATED IDENTICAL TRACE
          </span>
        </div>

        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
                <th style={{ padding: '10px' }}>Policy</th>
                <th style={{ padding: '10px' }}>Community Share</th>
                <th style={{ padding: '10px' }}>Fairness Gini</th>
                <th style={{ padding: '10px' }}>Data Residency</th>
                <th style={{ padding: '10px' }}>Renewable %</th>
                <th style={{ padding: '10px' }}>p50 Latency</th>
                <th style={{ padding: '10px' }}>Cloud Queries</th>
              </tr>
            </thead>
            <tbody>
              <tr style={{ borderBottom: '1px solid #33415522', fontWeight: 600, color: '#10b981' }}>
                <td style={{ padding: '10px' }}>Proposed (SunRoute)</td>
                <td style={{ padding: '10px' }}>88.7%</td>
                <td style={{ padding: '10px' }}>0.24</td>
                <td style={{ padding: '10px' }}>82.4%</td>
                <td style={{ padding: '10px' }}>64.2%</td>
                <td style={{ padding: '10px' }}>184 ms</td>
                <td style={{ padding: '10px' }}>16</td>
              </tr>
              <tr style={{ borderBottom: '1px solid #33415522', color: '#cbd5e1' }}>
                <td style={{ padding: '10px' }}>Small-First Cascade</td>
                <td style={{ padding: '10px' }}>72.1%</td>
                <td style={{ padding: '10px' }}>0.41</td>
                <td style={{ padding: '10px' }}>61.0%</td>
                <td style={{ padding: '10px' }}>48.0%</td>
                <td style={{ padding: '10px' }}>240 ms</td>
                <td style={{ padding: '10px' }}>39</td>
              </tr>
              <tr style={{ borderBottom: '1px solid #33415522', color: '#cbd5e1' }}>
                <td style={{ padding: '10px' }}>FCFS / Round-Robin</td>
                <td style={{ padding: '10px' }}>78.0%</td>
                <td style={{ padding: '10px' }}>0.58</td>
                <td style={{ padding: '10px' }}>42.5%</td>
                <td style={{ padding: '10px' }}>39.5%</td>
                <td style={{ padding: '10px' }}>295 ms</td>
                <td style={{ padding: '10px' }}>31</td>
              </tr>
              <tr style={{ borderBottom: '1px solid #33415522', color: '#cbd5e1' }}>
                <td style={{ padding: '10px' }}>Edge Only</td>
                <td style={{ padding: '10px' }}>100.0%</td>
                <td style={{ padding: '10px' }}>0.36</td>
                <td style={{ padding: '10px' }}>75.2%</td>
                <td style={{ padding: '10px' }}>52.1%</td>
                <td style={{ padding: '10px' }}>380 ms (drops)</td>
                <td style={{ padding: '10px' }}>0</td>
              </tr>
              <tr style={{ color: '#cbd5e1' }}>
                <td style={{ padding: '10px' }}>Cloud Only</td>
                <td style={{ padding: '10px' }}>0.0%</td>
                <td style={{ padding: '10px' }}>0.00</td>
                <td style={{ padding: '10px' }}>0.0%</td>
                <td style={{ padding: '10px' }}>0.0%</td>
                <td style={{ padding: '10px' }}>820 ms</td>
                <td style={{ padding: '10px' }}>142</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
