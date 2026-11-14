import { useState, useEffect, useRef } from 'react';
import {
  Send,
  Bot,
  User,
  Sun,
  Wind,
  Battery,
  Zap,
  Layers,
  MapPin,
  Sliders,
  Database,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Search,
  Cloud
} from 'lucide-react';

interface CityInfo {
  city_id: string;
  name: string;
  region: string;
  x_km: number;
  y_km: number;
  is_capital: boolean;
}

interface NodeTelemetry {
  node_id: string;
  city: string;
  city_name: string;
  region: string;
  x_km: number;
  y_km: number;
  kind: string;
  connectivity: string;
  battery_soc: number;
  solar_w: number;
  wind_w: number;
  load_w: number;
  queue_depth: number;
  temp_c: number;
  energy_source: string;
}

interface RoutingMetadata {
  decision_id: string;
  policy_used: string;
  target_node_id: string;
  target_kind: string;
  target_level: string;
  reason: string;
  score_total?: number;
  score_energy?: number;
  score_latency?: number;
  score_locality?: number;
  score_fairness?: number;
  origin_city: string;
  origin_city_name: string;
  target_city_name: string;
  execution_latency_ms: number;
  energy_consumed_j_est: number;
}

interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: string;
  origin_city?: string;
  origin_city_name?: string;
  routing_metadata?: RoutingMetadata;
}

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
  decision_id: string;
  request_id: string;
  timestamp_iso: string;
  policy_used: string;
  target_node_id: string;
  target_kind: string;
  target_level: string;
  score_total: number;
  reason: string;
  origin_city: string;
  origin_site: string;
  task_type: string;
  execution_latency_ms: number;
}

const FALLBACK_CITIES: CityInfo[] = [
  { city_id: 'city-01', name: 'Mumbai (State Capital & Cloud DC)', region: 'region-central', x_km: 175.0, y_km: 150.0, is_capital: true },
  { city_id: 'city-02', name: 'Pune (Tech Hub)', region: 'region-central', x_km: 167.5, y_km: 180.3, is_capital: false },
  { city_id: 'city-03', name: 'Nagpur (Central Solar Hub)', region: 'region-central', x_km: 147.5, y_km: 180.3, is_capital: false },
  { city_id: 'city-04', name: 'Nashik (Wine & Wind Zone)', region: 'region-central', x_km: 125.0, y_km: 150.0, is_capital: false },
  { city_id: 'city-05', name: 'Thane (Metro Suburban Edge)', region: 'region-central', x_km: 132.5, y_km: 119.7, is_capital: false },
  { city_id: 'city-06', name: 'Chhatrapati Sambhajinagar', region: 'region-central', x_km: 152.5, y_km: 119.7, is_capital: false },
  { city_id: 'city-07', name: 'Solapur (High Irradiance Grid)', region: 'region-north', x_km: 175.0, y_km: 260.0, is_capital: false },
  { city_id: 'city-14', name: 'Latur (Marathwada Solar Park)', region: 'region-south', x_km: 167.5, y_km: 70.3, is_capital: false },
  { city_id: 'city-20', name: 'Jalna (Steel Industrial Edge)', region: 'region-east', x_km: 262.5, y_km: 119.7, is_capital: false },
  { city_id: 'city-29', name: 'Badlapur (Foothills Clean Edge)', region: 'region-west', x_km: 22.5, y_km: 119.7, is_capital: false },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<'chat' | 'fleet' | 'audit'>('chat');
  const [cities, setCities] = useState<CityInfo[]>(FALLBACK_CITIES);
  const [selectedCity, setSelectedCity] = useState<string>('city-01');
  const [policy, setPolicy] = useState<string>('proposed');
  const [priority, setPriority] = useState<string>('normal');
  const [privacy, setPrivacy] = useState<string>('local_preferred');
  const [taskType, setTaskType] = useState<string>('chat');
  const [inputPrompt, setInputPrompt] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [expandedDecisionId, setExpandedDecisionId] = useState<string | null>(null);

  const [nodes, setNodes] = useState<NodeTelemetry[]>([]);
  const [metrics, setMetrics] = useState<SummaryMetrics>({
    total_queries: 0,
    community_edge_share: 0.0,
    cloud_share: 0.0,
    locality_rate: 0.0,
    p50_latency_ms: 0.0,
    p95_latency_ms: 0.0,
    registered_nodes_count: 30,
  });
  const [decisions, setDecisions] = useState<DecisionRecord[]>([]);
  const [regionFilter, setRegionFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [isConnected, setIsConnected] = useState<boolean>(true);

  const chatBottomRef = useRef<HTMLDivElement>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      sender: 'assistant',
      text: 'Welcome to SunRoute — Democratised Edge–Cloud AI inference.\n\nEvery query you submit is intelligently routed across our 30-city renewable microgrid or central cloud based on live capacity, solar/battery availability, data locality, and fairness. Select your origin city, choose your policy parameters, and test inference live!',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ]);

  // Load cities once on mount
  useEffect(() => {
    async function fetchCities() {
      try {
        const res = await fetch('/v1/cities');
        if (res.ok) {
          const data: CityInfo[] = await res.json();
          if (data && data.length > 0) {
            setCities(data);
          }
        }
      } catch (err) {
        console.warn('Using fallback cities list:', err);
      }
    }
    fetchCities();
  }, []);

  // Poll nodes, metrics, and decisions every 4 seconds
  useEffect(() => {
    let isMounted = true;

    async function refreshData() {
      try {
        const [nodesRes, metricsRes, decisionsRes] = await Promise.all([
          fetch('/v1/nodes'),
          fetch('/v1/metrics/summary'),
          fetch('/v1/decisions?limit=30'),
        ]);

        if (nodesRes.ok && isMounted) {
          const nodesData = await nodesRes.json();
          setNodes(nodesData);
          setIsConnected(true);
        }
        if (metricsRes.ok && isMounted) {
          const metricsData = await metricsRes.json();
          setMetrics(metricsData);
        }
        if (decisionsRes.ok && isMounted) {
          const decisionsData = await decisionsRes.json();
          setDecisions(decisionsData);
        }
      } catch (err) {
        if (isMounted) setIsConnected(false);
      }
    }

    refreshData();
    const interval = setInterval(refreshData, 4000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // Scroll to bottom on new messages
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const currentCityObj = cities.find((c) => c.city_id === selectedCity) || cities[0];
  const currentNodeObj = nodes.find((n) => n.city === selectedCity);

  async function handleSendMessage(customPrompt?: string) {
    const promptToSend = customPrompt || inputPrompt;
    if (!promptToSend.trim() || isLoading) return;

    const userMessageId = crypto.randomUUID();
    const userCityName = currentCityObj?.name || selectedCity;

    const newMsg: ChatMessage = {
      id: userMessageId,
      sender: 'user',
      text: promptToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      origin_city: selectedCity,
      origin_city_name: userCityName,
    };

    setMessages((prev) => [...prev, newMsg]);
    if (!customPrompt) setInputPrompt('');
    setIsLoading(true);

    try {
      const payload = {
        request_id: crypto.randomUUID(),
        prompt: promptToSend,
        prompt_tokens_est: Math.max(10, Math.ceil(promptToSend.length / 4)),
        max_output_tokens: 120,
        latency_target_ms: 2500,
        priority: priority,
        privacy: privacy,
        task_type: taskType,
        origin: {
          city: selectedCity,
          site: `${selectedCity}-user-society`,
        },
      };

      const res = await fetch(`/v1/chat/completions?policy=${policy}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errorDetail = await res.text();
        throw new Error(errorDetail || `HTTP error ${res.status}`);
      }

      const data = await res.json();
      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        sender: 'assistant',
        text: data.text || 'Inference completed.',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        routing_metadata: data.routing_metadata,
      };

      setMessages((prev) => [...prev, assistantMsg]);
      if (data.routing_metadata?.decision_id) {
        setExpandedDecisionId(data.routing_metadata.decision_id);
      }

      // Re-fetch metrics and decision log immediately
      fetch('/v1/metrics/summary').then(async (r) => {
        if (r.ok) setMetrics(await r.json());
      });
      fetch('/v1/decisions?limit=30').then(async (r) => {
        if (r.ok) setDecisions(await r.json());
      });
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        id: crypto.randomUUID(),
        sender: 'assistant',
        text: `⚠️ Gateway Execution Error: ${err.message || 'Failed to route query'}.\n\nPlease ensure Docker containers are running (docker compose up).`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  }

  const filteredNodes = nodes.filter((n) => {
    const matchesRegion = regionFilter === 'all' || n.region === regionFilter;
    const matchesSearch =
      n.city_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      n.node_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      n.city.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesRegion && matchesSearch;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', backgroundColor: '#090d16', color: '#f1f5f9', overflow: 'hidden' }}>
      {/* Top Header Bar */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 24px',
          backgroundColor: '#0f172a',
          borderBottom: '1px solid #1e293b',
          zIndex: 20,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div
            style={{
              width: '36px',
              height: '36px',
              borderRadius: '8px',
              backgroundColor: '#10b981',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 12px rgba(16, 185, 129, 0.4)',
            }}
          >
            <Sun size={20} color="#ffffff" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontWeight: 700, fontSize: '18px', letterSpacing: '-0.02em', color: '#f8fafc' }}>SunRoute</span>
              <span style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '4px', backgroundColor: '#064e3b', color: '#34d399', fontWeight: 600 }}>
                RESEARCH AI MESH
              </span>
            </div>
            <span style={{ fontSize: '12px', color: '#94a3b8' }}>Democratised Edge–Cloud AI Inference</span>
          </div>
        </div>

        {/* View Switcher Tabs */}
        <div style={{ display: 'flex', backgroundColor: '#1e293b', borderRadius: '8px', padding: '4px', gap: '4px' }}>
          <button
            onClick={() => setActiveTab('chat')}
            style={{
              padding: '8px 16px',
              borderRadius: '6px',
              border: 'none',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontWeight: 600,
              fontSize: '13px',
              backgroundColor: activeTab === 'chat' ? '#10b981' : 'transparent',
              color: activeTab === 'chat' ? '#ffffff' : '#94a3b8',
              transition: 'all 0.15s ease',
            }}
          >
            <Bot size={16} />
            <span>AI Studio (ChatGPT Demo)</span>
          </button>
          <button
            onClick={() => setActiveTab('fleet')}
            style={{
              padding: '8px 16px',
              borderRadius: '6px',
              border: 'none',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontWeight: 600,
              fontSize: '13px',
              backgroundColor: activeTab === 'fleet' ? '#10b981' : 'transparent',
              color: activeTab === 'fleet' ? '#ffffff' : '#94a3b8',
              transition: 'all 0.15s ease',
            }}
          >
            <Layers size={16} />
            <span>30-City Fleet Map ({nodes.length || 30})</span>
          </button>
          <button
            onClick={() => setActiveTab('audit')}
            style={{
              padding: '8px 16px',
              borderRadius: '6px',
              border: 'none',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontWeight: 600,
              fontSize: '13px',
              backgroundColor: activeTab === 'audit' ? '#10b981' : 'transparent',
              color: activeTab === 'audit' ? '#ffffff' : '#94a3b8',
              transition: 'all 0.15s ease',
            }}
          >
            <Database size={16} />
            <span>SQLite Audit Log ({decisions.length})</span>
          </button>
        </div>

        {/* Status Indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: isConnected ? '#34d399' : '#f87171' }}>
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: isConnected ? '#10b981' : '#ef4444',
                boxShadow: isConnected ? '0 0 8px #10b981' : 'none',
              }}
            />
            <span>{isConnected ? 'Gateway Online (Port 8000)' : 'Gateway Offline'}</span>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* TAB 1: CHATGPT AI STUDIO */}
        {activeTab === 'chat' && (
          <div style={{ display: 'flex', width: '100%', height: '100%' }}>
            {/* Left Control Sidebar */}
            <aside
              style={{
                width: '320px',
                backgroundColor: '#0c1322',
                borderRight: '1px solid #1e293b',
                display: 'flex',
                flexDirection: 'column',
                padding: '20px',
                gap: '18px',
                overflowY: 'auto',
              }}
            >
              <div>
                <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b', fontWeight: 700 }}>
                  DEMO CONTROLS
                </span>
                <h3 style={{ margin: '4px 0 0 0', fontSize: '15px', color: '#f8fafc', fontWeight: 600 }}>Your Simulated Origin</h3>
              </div>

              {/* City Selector */}
              <div>
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#cbd5e1', marginBottom: '6px', fontWeight: 500 }}>
                  <MapPin size={14} color="#10b981" />
                  <span>Origin City:</span>
                </label>
                <select
                  value={selectedCity}
                  onChange={(e) => setSelectedCity(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '9px 12px',
                    borderRadius: '6px',
                    backgroundColor: '#1e293b',
                    color: '#f8fafc',
                    border: '1px solid #334155',
                    fontSize: '13px',
                    outline: 'none',
                    cursor: 'pointer',
                  }}
                >
                  {cities.map((c) => (
                    <option key={c.city_id} value={c.city_id}>
                      {c.name} ({c.region.replace('region-', '')})
                    </option>
                  ))}
                </select>
              </div>

              {/* Current City Energy Card */}
              <div
                style={{
                  padding: '12px',
                  borderRadius: '8px',
                  backgroundColor: '#131e33',
                  border: '1px solid #1e3a5f',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '12px', fontWeight: 600, color: '#38bdf8' }}>
                    {currentCityObj?.name.split('(')[0] || 'Selected City'}
                  </span>
                  <span style={{ fontSize: '10px', padding: '2px 6px', borderRadius: '4px', backgroundColor: '#0369a1', color: '#e0f2fe' }}>
                    {currentNodeObj?.kind || 'simulated'}
                  </span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', fontSize: '11px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '5px', color: '#94a3b8' }}>
                    <Sun size={13} color="#f59e0b" />
                    <span>Solar: <strong style={{ color: '#f8fafc' }}>{currentNodeObj?.solar_w ?? 16.5}W</strong></span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '5px', color: '#94a3b8' }}>
                    <Battery size={13} color="#10b981" />
                    <span>Battery: <strong style={{ color: '#f8fafc' }}>{((currentNodeObj?.battery_soc ?? 0.82) * 100).toFixed(0)}%</strong></span>
                  </div>
                </div>
              </div>

              {/* Routing Policy Selector */}
              <div>
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#cbd5e1', marginBottom: '6px', fontWeight: 500 }}>
                  <Sliders size={14} color="#38bdf8" />
                  <span>Routing Policy:</span>
                </label>
                <select
                  value={policy}
                  onChange={(e) => setPolicy(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '9px 12px',
                    borderRadius: '6px',
                    backgroundColor: '#1e293b',
                    color: '#f8fafc',
                    border: '1px solid #334155',
                    fontSize: '13px',
                    outline: 'none',
                    cursor: 'pointer',
                  }}
                >
                  <option value="proposed">Proposed (Energy + Locality + Fairness)</option>
                  <option value="cascade">Cascade (Local → City → Region → Cloud)</option>
                  <option value="cloud_only">Cloud-Only (Central AWS Bedrock)</option>
                  <option value="edge_only">Edge-Only (Strict Community Local)</option>
                  <option value="fcfs">FCFS (First-Come First-Served)</option>
                </select>
              </div>

              {/* Advanced Parameters */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Priority:</label>
                  <select
                    value={priority}
                    onChange={(e) => setPriority(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '7px 8px',
                      borderRadius: '6px',
                      backgroundColor: '#1e293b',
                      color: '#f8fafc',
                      border: '1px solid #334155',
                      fontSize: '12px',
                    }}
                  >
                    <option value="normal">Normal</option>
                    <option value="high">High</option>
                    <option value="essential">Essential</option>
                    <option value="low">Low</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Privacy Tier:</label>
                  <select
                    value={privacy}
                    onChange={(e) => setPrivacy(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '7px 8px',
                      borderRadius: '6px',
                      backgroundColor: '#1e293b',
                      color: '#f8fafc',
                      border: '1px solid #334155',
                      fontSize: '12px',
                    }}
                  >
                    <option value="local_preferred">Local Preferred</option>
                    <option value="local_only">Local Only (Private)</option>
                    <option value="any">Any (Cloud ok)</option>
                  </select>
                </div>
              </div>

              {/* Task Type */}
              <div>
                <label style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>Task Type:</label>
                <select
                  value={taskType}
                  onChange={(e) => setTaskType(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '7px 8px',
                    borderRadius: '6px',
                    backgroundColor: '#1e293b',
                    color: '#f8fafc',
                    border: '1px solid #334155',
                    fontSize: '12px',
                  }}
                >
                  <option value="chat">Conversational Chat</option>
                  <option value="summarize">Text Summarization</option>
                  <option value="iot_telemetry">IoT Diagnostics</option>
                  <option value="code">Code Generation</option>
                </select>
              </div>

              {/* Quick Preset Prompts */}
              <div style={{ marginTop: 'auto', borderTop: '1px solid #1e293b', paddingTop: '14px' }}>
                <span style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '8px' }}>
                  QUICK PROMPT EXAMPLES
                </span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <button
                    onClick={() => handleSendMessage('Summarize local solar inverter health and battery state')}
                    style={{
                      textAlign: 'left',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      backgroundColor: '#162032',
                      border: '1px solid #233149',
                      color: '#cbd5e1',
                      fontSize: '11px',
                      cursor: 'pointer',
                    }}
                  >
                    ☀️ "Summarize local solar health"
                  </button>
                  <button
                    onClick={() => handleSendMessage('Emergency high priority: calculate clean evacuation route')}
                    style={{
                      textAlign: 'left',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      backgroundColor: '#162032',
                      border: '1px solid #233149',
                      color: '#cbd5e1',
                      fontSize: '11px',
                      cursor: 'pointer',
                    }}
                  >
                    🚨 "Emergency priority route"
                  </button>
                  <button
                    onClick={() => handleSendMessage('Explain the mathematical principles of general relativity in detail')}
                    style={{
                      textAlign: 'left',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      backgroundColor: '#162032',
                      border: '1px solid #233149',
                      color: '#cbd5e1',
                      fontSize: '11px',
                      cursor: 'pointer',
                    }}
                  >
                    ☁️ "Heavy query (tests cloud escalation)"
                  </button>
                </div>
              </div>
            </aside>

            {/* Main Chat Conversation Thread */}
            <main
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                backgroundColor: '#090d16',
                position: 'relative',
              }}
            >
              {/* Message History */}
              <div
                style={{
                  flex: 1,
                  padding: '24px 32px',
                  overflowY: 'auto',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '20px',
                }}
              >
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: msg.sender === 'user' ? 'flex-end' : 'flex-start',
                      width: '100%',
                    }}
                  >
                    {/* Message Bubble Container */}
                    <div
                      style={{
                        display: 'flex',
                        gap: '12px',
                        maxWidth: '82%',
                        flexDirection: msg.sender === 'user' ? 'row-reverse' : 'row',
                      }}
                    >
                      {/* Avatar */}
                      <div
                        style={{
                          width: '34px',
                          height: '34px',
                          borderRadius: '8px',
                          backgroundColor: msg.sender === 'user' ? '#0284c7' : '#10b981',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          flexShrink: 0,
                          marginTop: '2px',
                        }}
                      >
                        {msg.sender === 'user' ? <User size={18} color="#ffffff" /> : <Bot size={18} color="#ffffff" />}
                      </div>

                      {/* Message Content Body */}
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        <div
                          style={{
                            padding: '14px 18px',
                            borderRadius: msg.sender === 'user' ? '14px 4px 14px 14px' : '4px 14px 14px 14px',
                            backgroundColor: msg.sender === 'user' ? '#1e293b' : '#111c30',
                            border: `1px solid ${msg.sender === 'user' ? '#334155' : '#1f2e4d'}`,
                            color: '#f8fafc',
                            fontSize: '14px',
                            lineHeight: '1.6',
                            whiteSpace: 'pre-wrap',
                          }}
                        >
                          {msg.text}
                        </div>

                        {/* Message Metadata Header */}
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            fontSize: '11px',
                            color: '#64748b',
                            alignSelf: msg.sender === 'user' ? 'flex-end' : 'flex-start',
                          }}
                        >
                          {msg.origin_city_name && (
                            <span style={{ display: 'flex', alignItems: 'center', gap: '3px', color: '#38bdf8' }}>
                              <MapPin size={11} />
                              {msg.origin_city_name}
                            </span>
                          )}
                          <span>{msg.timestamp}</span>
                        </div>

                        {/* TRANSPARENT ROUTING INSPECTOR (Under Assistant Messages) */}
                        {msg.routing_metadata && (
                          <div
                            style={{
                              marginTop: '8px',
                              padding: '12px 14px',
                              borderRadius: '8px',
                              backgroundColor: '#0d1829',
                              border: '1px solid #1d3356',
                              display: 'flex',
                              flexDirection: 'column',
                              gap: '8px',
                            }}
                          >
                            <div
                              onClick={() =>
                                setExpandedDecisionId(
                                  expandedDecisionId === msg.routing_metadata?.decision_id
                                    ? null
                                    : (msg.routing_metadata?.decision_id || null)
                                )
                              }
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                cursor: 'pointer',
                              }}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span
                                  style={{
                                    padding: '3px 8px',
                                    borderRadius: '4px',
                                    fontSize: '11px',
                                    fontWeight: 700,
                                    backgroundColor:
                                      msg.routing_metadata.target_kind === 'cloud' ? '#3b82f6' : '#059669',
                                    color: '#ffffff',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                  }}
                                >
                                  {msg.routing_metadata.target_kind === 'cloud' ? <Cloud size={12} /> : <Zap size={12} />}
                                  {msg.routing_metadata.target_level.toUpperCase()} TIER: {msg.routing_metadata.target_node_id}
                                </span>
                                <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                                  ({msg.routing_metadata.execution_latency_ms} ms)
                                </span>
                              </div>
                              <span style={{ fontSize: '11px', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '2px' }}>
                                <span>Inspect Decision</span>
                                {expandedDecisionId === msg.routing_metadata.decision_id ? (
                                  <ChevronUp size={14} />
                                ) : (
                                  <ChevronDown size={14} />
                                )}
                              </span>
                            </div>

                            {/* Detailed Scoring Breakdown */}
                            {expandedDecisionId === msg.routing_metadata.decision_id && (
                              <div
                                style={{
                                  borderTop: '1px solid #1a2f4e',
                                  paddingTop: '8px',
                                  display: 'flex',
                                  flexDirection: 'column',
                                  gap: '6px',
                                  fontSize: '12px',
                                }}
                              >
                                <div style={{ color: '#cbd5e1' }}>
                                  <strong>Router Rationale:</strong> {msg.routing_metadata.reason}
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '6px', marginTop: '4px' }}>
                                  <div style={{ padding: '6px', backgroundColor: '#132138', borderRadius: '4px', textAlign: 'center' }}>
                                    <span style={{ fontSize: '10px', color: '#94a3b8', display: 'block' }}>Energy Score</span>
                                    <strong style={{ color: '#f59e0b' }}>
                                      {msg.routing_metadata.score_energy !== undefined ? msg.routing_metadata.score_energy : 'N/A'}
                                    </strong>
                                  </div>
                                  <div style={{ padding: '6px', backgroundColor: '#132138', borderRadius: '4px', textAlign: 'center' }}>
                                    <span style={{ fontSize: '10px', color: '#94a3b8', display: 'block' }}>Latency Score</span>
                                    <strong style={{ color: '#38bdf8' }}>
                                      {msg.routing_metadata.score_latency !== undefined ? msg.routing_metadata.score_latency : 'N/A'}
                                    </strong>
                                  </div>
                                  <div style={{ padding: '6px', backgroundColor: '#132138', borderRadius: '4px', textAlign: 'center' }}>
                                    <span style={{ fontSize: '10px', color: '#94a3b8', display: 'block' }}>Locality Score</span>
                                    <strong style={{ color: '#10b981' }}>
                                      {msg.routing_metadata.score_locality !== undefined ? msg.routing_metadata.score_locality : 'N/A'}
                                    </strong>
                                  </div>
                                  <div style={{ padding: '6px', backgroundColor: '#132138', borderRadius: '4px', textAlign: 'center' }}>
                                    <span style={{ fontSize: '10px', color: '#94a3b8', display: 'block' }}>Fairness Score</span>
                                    <strong style={{ color: '#a855f7' }}>
                                      {msg.routing_metadata.score_fairness !== undefined ? msg.routing_metadata.score_fairness : 'N/A'}
                                    </strong>
                                  </div>
                                </div>
                                <div style={{ fontSize: '11px', color: '#64748b', display: 'flex', justifyContent: 'space-between', marginTop: '2px' }}>
                                  <span>SQLite Record ID: {msg.routing_metadata.decision_id}</span>
                                  <span>Energy: {msg.routing_metadata.energy_consumed_j_est} Joules</span>
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
                <div ref={chatBottomRef} />
              </div>

              {/* Bottom Input Prompt Bar */}
              <div
                style={{
                  padding: '16px 32px 24px 32px',
                  backgroundColor: '#0c1322',
                  borderTop: '1px solid #1e293b',
                  display: 'flex',
                  gap: '12px',
                  alignItems: 'center',
                }}
              >
                <div style={{ position: 'relative', flex: 1 }}>
                  <input
                    type="text"
                    value={inputPrompt}
                    onChange={(e) => setInputPrompt(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleSendMessage();
                    }}
                    placeholder={`Ask SunRoute AI from ${currentCityObj?.name.split('(')[0] || 'your city'} (routed by energy, locality, & fairness)...`}
                    disabled={isLoading}
                    style={{
                      width: '100%',
                      padding: '14px 20px',
                      borderRadius: '10px',
                      backgroundColor: '#162032',
                      border: '1px solid #23344e',
                      color: '#f8fafc',
                      fontSize: '14px',
                      outline: 'none',
                    }}
                  />
                  <span style={{ position: 'absolute', right: '14px', top: '15px', fontSize: '11px', color: '#64748b' }}>
                    Origin: {selectedCity}
                  </span>
                </div>

                <button
                  onClick={() => handleSendMessage()}
                  disabled={isLoading || !inputPrompt.trim()}
                  style={{
                    padding: '14px 22px',
                    borderRadius: '10px',
                    border: 'none',
                    backgroundColor: isLoading || !inputPrompt.trim() ? '#1e293b' : '#10b981',
                    color: '#ffffff',
                    cursor: isLoading || !inputPrompt.trim() ? 'not-allowed' : 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    fontWeight: 600,
                    fontSize: '14px',
                    transition: 'all 0.15s ease',
                  }}
                >
                  {isLoading ? <RefreshCw size={16} className="animate-spin" /> : <Send size={16} />}
                  <span>Send</span>
                </button>
              </div>
            </main>
          </div>
        )}

        {/* TAB 2: 30-CITY FLEET MAP */}
        {activeTab === 'fleet' && (
          <div style={{ flex: 1, padding: '24px 32px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {/* KPI Cards Row */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '14px' }}>
              <div style={{ padding: '16px', borderRadius: '10px', backgroundColor: '#0f172a', border: '1px solid #1e293b' }}>
                <span style={{ fontSize: '12px', color: '#94a3b8', display: 'block', marginBottom: '6px' }}>Total Queries Served</span>
                <span style={{ fontSize: '24px', fontWeight: 700, color: '#f8fafc' }}>{metrics.total_queries}</span>
                <span style={{ fontSize: '11px', color: '#34d399', display: 'block', marginTop: '4px' }}>[MEASURED]</span>
              </div>
              <div style={{ padding: '16px', borderRadius: '10px', backgroundColor: '#0f172a', border: '1px solid #1e293b' }}>
                <span style={{ fontSize: '12px', color: '#94a3b8', display: 'block', marginBottom: '6px' }}>Community Edge Share</span>
                <span style={{ fontSize: '24px', fontWeight: 700, color: '#10b981' }}>{(metrics.community_edge_share * 100).toFixed(1)}%</span>
                <span style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginTop: '4px' }}>Target: &gt; 60%</span>
              </div>
              <div style={{ padding: '16px', borderRadius: '10px', backgroundColor: '#0f172a', border: '1px solid #1e293b' }}>
                <span style={{ fontSize: '12px', color: '#94a3b8', display: 'block', marginBottom: '6px' }}>Cloud Tier Share</span>
                <span style={{ fontSize: '24px', fontWeight: 700, color: '#38bdf8' }}>{(metrics.cloud_share * 100).toFixed(1)}%</span>
                <span style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginTop: '4px' }}>Heavy/Overflow</span>
              </div>
              <div style={{ padding: '16px', borderRadius: '10px', backgroundColor: '#0f172a', border: '1px solid #1e293b' }}>
                <span style={{ fontSize: '12px', color: '#94a3b8', display: 'block', marginBottom: '6px' }}>Data Locality Rate</span>
                <span style={{ fontSize: '24px', fontWeight: 700, color: '#f59e0b' }}>{(metrics.locality_rate * 100).toFixed(1)}%</span>
                <span style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginTop: '4px' }}>Home City Res.</span>
              </div>
              <div style={{ padding: '16px', borderRadius: '10px', backgroundColor: '#0f172a', border: '1px solid #1e293b' }}>
                <span style={{ fontSize: '12px', color: '#94a3b8', display: 'block', marginBottom: '6px' }}>p50 End-to-End Latency</span>
                <span style={{ fontSize: '24px', fontWeight: 700, color: '#f8fafc' }}>{metrics.p50_latency_ms.toFixed(0)} ms</span>
                <span style={{ fontSize: '11px', color: '#34d399', display: 'block', marginTop: '4px' }}>Local: ~180ms</span>
              </div>
            </div>

            {/* Region Filter & Search */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', gap: '8px' }}>
                {['all', 'region-central', 'region-north', 'region-south', 'region-east', 'region-west'].map((r) => (
                  <button
                    key={r}
                    onClick={() => setRegionFilter(r)}
                    style={{
                      padding: '6px 14px',
                      borderRadius: '6px',
                      border: '1px solid #334155',
                      backgroundColor: regionFilter === r ? '#10b981' : '#1e293b',
                      color: regionFilter === r ? '#ffffff' : '#94a3b8',
                      fontSize: '12px',
                      cursor: 'pointer',
                      fontWeight: 500,
                    }}
                  >
                    {r === 'all' ? 'All Regions (30 Cities)' : r.replace('region-', '').toUpperCase()}
                  </button>
                ))}
              </div>

              <div style={{ position: 'relative', width: '260px' }}>
                <Search size={14} color="#64748b" style={{ position: 'absolute', left: '10px', top: '10px' }} />
                <input
                  type="text"
                  placeholder="Filter city or node..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px 8px 32px',
                    borderRadius: '6px',
                    backgroundColor: '#1e293b',
                    border: '1px solid #334155',
                    color: '#f8fafc',
                    fontSize: '12px',
                  }}
                />
              </div>
            </div>

            {/* 30-City Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '14px' }}>
              {filteredNodes.map((n) => {
                const batteryPct = (n.battery_soc * 100).toFixed(0);
                const isPhysical = n.kind === 'physical';
                return (
                  <div
                    key={n.node_id}
                    style={{
                      backgroundColor: '#0f172a',
                      borderRadius: '10px',
                      padding: '16px',
                      border: `1px solid ${selectedCity === n.city ? '#10b981' : '#1e293b'}`,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '10px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span style={{ fontWeight: 600, fontSize: '13px', color: '#f8fafc' }}>
                            {n.city_name ? n.city_name.split('(')[0] : n.city}
                          </span>
                        </div>
                        <span style={{ fontSize: '11px', color: '#64748b' }}>
                          {n.city} • {n.region.replace('region-', '')}
                        </span>
                      </div>
                      <span
                        style={{
                          fontSize: '10px',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          backgroundColor: isPhysical ? '#047857' : '#1e3a5f',
                          color: isPhysical ? '#6ee7b7' : '#93c5fd',
                          fontWeight: 600,
                        }}
                      >
                        [{n.energy_source.toUpperCase()}]
                      </span>
                    </div>

                    {/* Battery Meter */}
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '4px' }}>
                        <span style={{ color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Battery size={12} color="#10b981" /> Battery SOC
                        </span>
                        <strong style={{ color: n.battery_soc < 0.2 ? '#f87171' : '#f8fafc' }}>{batteryPct}%</strong>
                      </div>
                      <div style={{ width: '100%', height: '6px', backgroundColor: '#1e293b', borderRadius: '3px', overflow: 'hidden' }}>
                        <div
                          style={{
                            width: `${batteryPct}%`,
                            height: '100%',
                            backgroundColor: n.battery_soc < 0.2 ? '#ef4444' : n.battery_soc < 0.5 ? '#f59e0b' : '#10b981',
                          }}
                        />
                      </div>
                    </div>

                    {/* Power Stats */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '11px', paddingTop: '4px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#94a3b8' }}>
                        <Sun size={12} color="#f59e0b" />
                        <span>Solar: <strong style={{ color: '#f8fafc' }}>{n.solar_w}W</strong></span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#94a3b8' }}>
                        <Wind size={12} color="#38bdf8" />
                        <span>Wind: <strong style={{ color: '#f8fafc' }}>{n.wind_w}W</strong></span>
                      </div>
                    </div>

                    <div style={{ borderTop: '1px solid #1e293b', paddingTop: '8px', display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#64748b' }}>
                      <span>Queue: {n.queue_depth} jobs</span>
                      <button
                        onClick={() => {
                          setSelectedCity(n.city);
                          setActiveTab('chat');
                        }}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: '#38bdf8',
                          cursor: 'pointer',
                          padding: 0,
                          fontSize: '11px',
                          textDecoration: 'underline',
                        }}
                      >
                        Set as Origin & Chat →
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* TAB 3: SQLITE AUDIT LOG */}
        {activeTab === 'audit' && (
          <div style={{ flex: 1, padding: '24px 32px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>SQLite Decision Audit Database</h3>
                <span style={{ fontSize: '12px', color: '#94a3b8' }}>
                  Every query routing decision is permanently recorded with complete score breakdowns.
                </span>
              </div>
              <span style={{ fontSize: '12px', padding: '4px 10px', borderRadius: '4px', backgroundColor: '#1e293b', color: '#38bdf8' }}>
                WAL Mode Enabled • experiments/decision_audit.db
              </span>
            </div>

            <div style={{ backgroundColor: '#0f172a', borderRadius: '8px', border: '1px solid #1e293b', overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', textAlign: 'left' }}>
                <thead style={{ backgroundColor: '#1e293b', color: '#94a3b8', textTransform: 'uppercase', fontSize: '11px' }}>
                  <tr>
                    <th style={{ padding: '12px 14px' }}>Timestamp</th>
                    <th style={{ padding: '12px 14px' }}>Origin City</th>
                    <th style={{ padding: '12px 14px' }}>Target Node</th>
                    <th style={{ padding: '12px 14px' }}>Level</th>
                    <th style={{ padding: '12px 14px' }}>Policy</th>
                    <th style={{ padding: '12px 14px' }}>Latency</th>
                    <th style={{ padding: '12px 14px' }}>Router Rationale</th>
                  </tr>
                </thead>
                <tbody>
                  {decisions.map((d) => (
                    <tr key={d.decision_id} style={{ borderBottom: '1px solid #1e293b' }}>
                      <td style={{ padding: '12px 14px', color: '#cbd5e1' }}>
                        {new Date(d.timestamp_iso).toLocaleTimeString()}
                      </td>
                      <td style={{ padding: '12px 14px', color: '#38bdf8', fontWeight: 600 }}>{d.origin_city}</td>
                      <td style={{ padding: '12px 14px', color: d.target_kind === 'cloud' ? '#3b82f6' : '#10b981', fontWeight: 600 }}>
                        {d.target_node_id}
                      </td>
                      <td style={{ padding: '12px 14px', textTransform: 'uppercase', fontSize: '10px' }}>
                        <span style={{ padding: '2px 6px', borderRadius: '4px', backgroundColor: '#1e293b' }}>
                          {d.target_level}
                        </span>
                      </td>
                      <td style={{ padding: '12px 14px', color: '#94a3b8' }}>{d.policy_used}</td>
                      <td style={{ padding: '12px 14px', color: '#f8fafc' }}>{d.execution_latency_ms.toFixed(1)} ms</td>
                      <td style={{ padding: '12px 14px', color: '#94a3b8', maxWidth: '300px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {d.reason}
                      </td>
                    </tr>
                  ))}
                  {decisions.length === 0 && (
                    <tr>
                      <td colSpan={7} style={{ padding: '30px', textAlign: 'center', color: '#64748b' }}>
                        No decisions recorded yet. Go to the AI Studio tab and send a query!
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
