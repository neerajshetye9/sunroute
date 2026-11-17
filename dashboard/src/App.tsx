import React, { useState, useEffect, useRef } from 'react';
import {
  Send,
  Bot,
  User,
  Sun,
  Battery,
  Zap,
  Layers,
  MapPin,
  Database,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Cloud,
  Plus,
  Trash2,
  Paperclip,
  Image as ImageIcon,
  FileText,
  X,
  MessageSquare,
  Sparkles,
  Activity,
  Terminal,
  Cpu,
} from 'lucide-react';

const API_BASE = (import.meta as any).env?.VITE_API_URL || '';

// ── Types ──────────────────────────────────────────────────────────

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

interface ChatAttachment {
  name: string;
  size: number;
  mime_type: string;
  data_url?: string;
}

interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant' | 'system';
  text: string;
  timestamp: string;
  attachments?: ChatAttachment[];
  routing_metadata?: RoutingMetadata;
}

interface ConversationItem {
  conversation_id: string;
  title: string;
  message_count: number;
  updated_at: string;
}

interface UserProfile {
  user_id: string;
  username: string;
  display_name: string;
  role: string;
  default_city: string;
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
  { city_id: 'city-12', name: 'Jalgaon (Khandesh Solar Valley)', region: 'region-north', x_km: 180.0, y_km: 220.0, is_capital: false },
  { city_id: 'city-14', name: 'Latur (Marathwada Solar Park)', region: 'region-south', x_km: 167.5, y_km: 70.3, is_capital: false },
  { city_id: 'city-20', name: 'Jalna (Steel Industrial Edge)', region: 'region-east', x_km: 262.5, y_km: 119.7, is_capital: false },
  { city_id: 'city-29', name: 'Badlapur (Foothills Clean Edge)', region: 'region-west', x_km: 22.5, y_km: 119.7, is_capital: false },
];

const DEMO_PERSONAS: UserProfile[] = [
  { user_id: 'user-student-01', username: 'student', display_name: 'Aarav Sharma (COEP Pune Student)', role: 'student', default_city: 'city-02' },
  { user_id: 'user-researcher-02', username: 'researcher', display_name: 'Dr. Priya Patel (IIT Bombay Scholar)', role: 'researcher', default_city: 'city-01' },
  { user_id: 'user-citizen-03', username: 'citizen', display_name: 'Kavita Rao (Nashik Microgrid Member)', role: 'citizen', default_city: 'city-05' },
  { user_id: 'user-admin-04', username: 'admin', display_name: 'Fleet Admin (Microgrid Operations)', role: 'admin', default_city: 'city-01' },
];

export default function App() {
  // Navigation: 'studio' (ChatGPT consumer app) vs 'ops' (System Monitor & Fleet Copilot)
  const [currentView, setCurrentView] = useState<'studio' | 'ops'>('studio');

  // Authentication & Persona state
  const [currentUser, setCurrentUser] = useState<UserProfile>(DEMO_PERSONAS[0]);
  const [showAuthModal, setShowAuthModal] = useState<boolean>(false);
  const [authUsername, setAuthUsername] = useState<string>('');
  const [authPassword, setAuthPassword] = useState<string>('');

  // Location state
  const [cities, setCities] = useState<CityInfo[]>(FALLBACK_CITIES);
  const [selectedCity, setSelectedCity] = useState<string>('city-02');
  const [locationSource, setLocationSource] = useState<'auto' | 'manual'>('auto');
  const [showLocationPicker, setShowLocationPicker] = useState<boolean>(false);

  // Studio Chat State
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [promptInput, setPromptInput] = useState<string>('');
  const [isInferring, setIsInferring] = useState<boolean>(false);
  const [attachedFiles, setAttachedFiles] = useState<ChatAttachment[]>([]);
  const [policy, setPolicy] = useState<string>('proposed');
  const [expandedDecisionId, setExpandedDecisionId] = useState<string | null>(null);

  // Ops Console & Copilot State
  const [nodes, setNodes] = useState<NodeTelemetry[]>([]);
  const [metrics, setMetrics] = useState<SummaryMetrics | null>(null);
  const [decisions, setDecisions] = useState<DecisionRecord[]>([]);
  const [regionFilter, setRegionFilter] = useState<string>('all');
  const [opsPrompt, setOpsPrompt] = useState<string>('');
  const [opsMessages, setOpsMessages] = useState<{ sender: 'user' | 'assistant'; text: string; time: string }[]>([
    {
      sender: 'assistant',
      text: '👋 **SunRoute Fleet AI Copilot Initialized**.\n\nI monitor all 30 microgrid nodes across Maharashtra and analyze real-time routing decisions.\n\nYou can ask: *"Which nodes have low battery?"*, *"Show solar generation in Khandesh"*, or *"Why was the last query routed to AWS Bedrock?"*.',
      time: 'Ready',
    },
  ]);
  const [isOpsLoading, setIsOpsLoading] = useState<boolean>(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const chatBottomRef = useRef<HTMLDivElement | null>(null);
  const opsBottomRef = useRef<HTMLDivElement | null>(null);

  // ── Initial Setup & Polling ──────────────────────────────────────

  useEffect(() => {
    // 1. Fetch cities
    fetch(`${API_BASE}/v1/cities`)
      .then((r) => r.ok ? r.json() : FALLBACK_CITIES)
      .then((data: CityInfo[]) => {
        if (data && data.length > 0) setCities(data);
      })
      .catch(() => setCities(FALLBACK_CITIES));

    // 2. Auto-detect browser location
    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        (_pos) => {
          // Approx city matching: default to Pune (city-02) or nearest
          setSelectedCity('city-02');
          setLocationSource('auto');
        },
        () => {
          setSelectedCity(currentUser.default_city || 'city-02');
        },
        { timeout: 2500 }
      );
    }

    // 3. Load user's conversations
    loadConversations(currentUser.user_id);

    // 4. Poll telemetry & metrics
    refreshTelemetry();
    const timer = setInterval(refreshTelemetry, 5000);
    return () => clearInterval(timer);
  }, [currentUser]);

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, isInferring]);

  useEffect(() => {
    opsBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [opsMessages, isOpsLoading]);

  const refreshTelemetry = () => {
    fetch(`${API_BASE}/v1/telemetry/nodes`)
      .then(async (r) => {
        if (r.ok) {
          const rawNodes = await r.json();
          const enriched = rawNodes.map((n: any) => {
            const cityMatch = cities.find((c) => c.city_id === n.city);
            return {
              ...n,
              city_name: cityMatch?.name || n.city,
              region: cityMatch?.region || 'region-central',
              x_km: cityMatch?.x_km || 175.0,
              y_km: cityMatch?.y_km || 150.0,
            };
          });
          setNodes(enriched);
        }
      })
      .catch((e) => console.debug('Telemetry poll:', e));

    fetch(`${API_BASE}/v1/metrics/summary`)
      .then(async (r) => {
        if (r.ok) setMetrics(await r.json());
      })
      .catch(() => {});

    fetch(`${API_BASE}/v1/decisions?limit=25`)
      .then(async (r) => {
        if (r.ok) setDecisions(await r.json());
      })
      .catch(() => {});
  };

  const loadConversations = async (userId: string) => {
    try {
      const res = await fetch(`${API_BASE}/v1/chat/conversations?user_id=${userId}`);
      if (res.ok) {
        const list = await res.json();
        setConversations(list);
        if (list.length > 0 && !currentConversationId) {
          selectConversation(list[0].conversation_id);
        } else if (list.length === 0) {
          startNewChat();
        }
      }
    } catch (e) {
      console.debug('Failed loading conversations:', e);
    }
  };

  const selectConversation = async (convId: string) => {
    setCurrentConversationId(convId);
    try {
      const res = await fetch(`${API_BASE}/v1/chat/conversations/${convId}`);
      if (res.ok) {
        const data = await res.json();
        const mapped: ChatMessage[] = (data.messages || []).map((m: any) => ({
          id: m.message_id,
          sender: m.sender,
          text: m.text,
          timestamp: new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          attachments: m.attachments,
          routing_metadata: m.routing_metadata,
        }));
        setChatMessages(mapped);
      }
    } catch (e) {
      console.error('Error fetching conversation messages:', e);
    }
  };

  const startNewChat = () => {
    setCurrentConversationId(null);
    setChatMessages([]);
    setAttachedFiles([]);
    setExpandedDecisionId(null);
  };

  const deleteConversation = async (convId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await fetch(`${API_BASE}/v1/chat/conversations/${convId}`, { method: 'DELETE' });
      setConversations((prev) => prev.filter((c) => c.conversation_id !== convId));
      if (currentConversationId === convId) {
        startNewChat();
      }
    } catch (err) {
      console.error('Delete failed:', err);
    }
  };

  // ── Send Message in Studio ───────────────────────────────────────

  const handleSendStudioMessage = async (overridePrompt?: string) => {
    const textToSend = overridePrompt || promptInput;
    if (!textToSend.trim() && attachedFiles.length === 0) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      sender: 'user',
      text: textToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      attachments: [...attachedFiles],
    };

    setChatMessages((prev) => [...prev, userMsg]);
    setPromptInput('');
    setAttachedFiles([]);
    setIsInferring(true);

    try {
      let maxTokens = 250;
      const lower = textToSend.toLowerCase();
      if (lower.includes('1000 word') || lower.includes('1000 words')) {
        maxTokens = 850;
      } else if (
        lower.includes('500 words') ||
        lower.includes('400 words') ||
        lower.includes('300 words') ||
        lower.includes('essay')
      ) {
        maxTokens = 600;
      }

      const payload = {
        conversation_id: currentConversationId || 'new',
        user_id: currentUser.user_id,
        prompt: textToSend,
        origin_city: selectedCity,
        policy: policy,
        attachments: userMsg.attachments || [],
        max_output_tokens: maxTokens,
      };

      const res = await fetch(`${API_BASE}/v1/chat/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(errorText || `HTTP ${res.status}`);
      }

      const data = await res.json();
      const asstRec = data.assistant_message;
      const asstMsg: ChatMessage = {
        id: asstRec.message_id || crypto.randomUUID(),
        sender: 'assistant',
        text: asstRec.text,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        routing_metadata: asstRec.routing_metadata,
      };

      setChatMessages((prev) => [...prev, asstMsg]);
      if (asstRec.routing_metadata?.decision_id) {
        setExpandedDecisionId(asstRec.routing_metadata.decision_id);
      }

      // Update current conversation id if it was newly created
      if (data.conversation_id) {
        setCurrentConversationId(data.conversation_id);
        loadConversations(currentUser.user_id);
      }

      refreshTelemetry();
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        id: crypto.randomUUID(),
        sender: 'assistant',
        text: `⚠️ Gateway Routing Error: ${err.message || 'Execution failed'}.\n\nEnsure backend gateway and Jetson edge node are running.`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };
      setChatMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsInferring(false);
    }
  };

  // ── Ops Copilot Assistant ────────────────────────────────────────

  const handleSendOpsCopilot = async (customPrompt?: string) => {
    const query = customPrompt || opsPrompt;
    if (!query.trim()) return;

    setOpsMessages((prev) => [
      ...prev,
      { sender: 'user', text: query, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) },
    ]);
    setOpsPrompt('');
    setIsOpsLoading(true);

    try {
      const res = await fetch(`${API_BASE}/v1/ops/copilot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: query }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      setOpsMessages((prev) => [
        ...prev,
        {
          sender: 'assistant',
          text: data.response,
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } catch (err: any) {
      setOpsMessages((prev) => [
        ...prev,
        {
          sender: 'assistant',
          text: `⚠️ Ops Copilot connection error: ${err.message}. Please verify SunRoute Gateway is active on port 8000.`,
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } finally {
      setIsOpsLoading(false);
    }
  };

  // ── Attachment handling ──────────────────────────────────────────

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    const file = files[0];
    const reader = new FileReader();
    reader.onload = () => {
      const attachment: ChatAttachment = {
        name: file.name,
        size: file.size,
        mime_type: file.type || 'application/octet-stream',
        data_url: reader.result as string,
      };
      setAttachedFiles((prev) => [...prev, attachment]);
    };
    reader.readAsDataURL(file);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const removeAttachment = (index: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  // ── Authentication switcher ──────────────────────────────────────

  const handlePersonaSelect = (persona: UserProfile) => {
    setCurrentUser(persona);
    setSelectedCity(persona.default_city);
    setShowAuthModal(false);
    loadConversations(persona.user_id);
  };

  const handleCustomLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!authUsername.trim()) return;

    try {
      const res = await fetch(`${API_BASE}/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: authUsername.trim(),
          password: authPassword || 'demo',
          display_name: `${authUsername.trim()} (Custom User)`,
          role: 'student',
          default_city: selectedCity,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setCurrentUser(data.user);
        setShowAuthModal(false);
        loadConversations(data.user.user_id);
      }
    } catch (err) {
      console.error('Login error:', err);
    }
  };

  const activeCityName = cities.find((c) => c.city_id === selectedCity)?.name || selectedCity;
  const filteredNodes = nodes.filter((n) => regionFilter === 'all' || n.region === regionFilter);

  // Aggregate stats
  const totalFleetSolarW = nodes.reduce((sum, n) => sum + (n.solar_w || 0), 0);
  const totalFleetWindW = nodes.reduce((sum, n) => sum + (n.wind_w || 0), 0);
  const avgBatterySOC = nodes.length > 0 ? (nodes.reduce((sum, n) => sum + n.battery_soc, 0) / nodes.length) : 0.85;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100vw', overflow: 'hidden', backgroundColor: '#090d16', color: '#f8fafc' }}>

      {/* ── Top Header Navigation Bar ─────────────────────────────── */}
      <header style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 20px',
        backgroundColor: '#0f172a',
        borderBottom: '1px solid #1e293b',
        zIndex: 50,
      }}>
        {/* Brand & Microgrid pulse */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '32px',
            height: '32px',
            borderRadius: '8px',
            backgroundColor: 'rgba(245, 158, 11, 0.15)',
            border: '1px solid #f59e0b',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#f59e0b',
          }}>
            <Sun size={20} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '18px', fontWeight: 700, letterSpacing: '-0.3px', color: '#f8fafc' }}>SunRoute</span>
              <span style={{
                fontSize: '10px',
                fontWeight: 600,
                padding: '2px 6px',
                borderRadius: '10px',
                backgroundColor: 'rgba(16, 185, 129, 0.2)',
                color: '#10b981',
                border: '1px solid rgba(16, 185, 129, 0.4)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
              }}>
                <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#10b981' }} />
                ORIN NANO ACTIVE
              </span>
            </div>
            <div style={{ fontSize: '11px', color: '#94a3b8' }}>Community Edge AI Microgrid Network</div>
          </div>
        </div>

        {/* View Switcher: Studio vs Ops Console */}
        <div style={{
          display: 'flex',
          backgroundColor: '#090d16',
          padding: '4px',
          borderRadius: '10px',
          border: '1px solid #334155',
          gap: '4px',
        }}>
          <button
            onClick={() => setCurrentView('studio')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 16px',
              borderRadius: '7px',
              fontSize: '13px',
              fontWeight: 600,
              border: 'none',
              cursor: 'pointer',
              backgroundColor: currentView === 'studio' ? '#1e293b' : 'transparent',
              color: currentView === 'studio' ? '#38bdf8' : '#94a3b8',
              boxShadow: currentView === 'studio' ? '0 2px 4px rgba(0,0,0,0.4)' : 'none',
              transition: 'all 0.15s',
            }}
          >
            <MessageSquare size={16} />
            <span>AI Studio (ChatGPT)</span>
          </button>

          <button
            onClick={() => setCurrentView('ops')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 16px',
              borderRadius: '7px',
              fontSize: '13px',
              fontWeight: 600,
              border: 'none',
              cursor: 'pointer',
              backgroundColor: currentView === 'ops' ? '#1e293b' : 'transparent',
              color: currentView === 'ops' ? '#10b981' : '#94a3b8',
              boxShadow: currentView === 'ops' ? '0 2px 4px rgba(0,0,0,0.4)' : 'none',
              transition: 'all 0.15s',
            }}
          >
            <Activity size={16} />
            <span>Fleet Ops & Copilot</span>
          </button>
        </div>

        {/* User Persona & Location Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {/* Location Picker Pill */}
          <div style={{ position: 'relative' }}>
            <button
              onClick={() => setShowLocationPicker(!showLocationPicker)}
              title="Click to change your simulated origin city location"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 12px',
                borderRadius: '8px',
                backgroundColor: '#1e293b',
                border: '1px solid #334155',
                color: '#e2e8f0',
                fontSize: '12px',
                cursor: 'pointer',
              }}
            >
              <MapPin size={14} color="#f59e0b" />
              <span style={{ maxWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {activeCityName.split('(')[0]}
              </span>
              <span style={{ fontSize: '10px', color: '#10b981', fontWeight: 600 }}>
                [{locationSource === 'auto' ? 'GPS' : 'Manual'}]
              </span>
              <ChevronDown size={12} />
            </button>

            {/* Location dropdown */}
            {showLocationPicker && (
              <div style={{
                position: 'absolute',
                top: '40px',
                right: 0,
                width: '280px',
                maxHeight: '360px',
                overflowY: 'auto',
                backgroundColor: '#0f172a',
                border: '1px solid #334155',
                borderRadius: '8px',
                boxShadow: '0 10px 25px rgba(0,0,0,0.6)',
                zIndex: 100,
                padding: '6px',
              }}>
                <div style={{ padding: '6px 10px', fontSize: '11px', color: '#94a3b8', fontWeight: 600, borderBottom: '1px solid #1e293b' }}>
                  DETECTED ORIGIN LOCATION (30 CITIES)
                </div>
                {cities.map((c) => (
                  <button
                    key={c.city_id}
                    onClick={() => {
                      setSelectedCity(c.city_id);
                      setLocationSource('manual');
                      setShowLocationPicker(false);
                    }}
                    style={{
                      width: '100%',
                      textAlign: 'left',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      backgroundColor: selectedCity === c.city_id ? '#1e293b' : 'transparent',
                      color: selectedCity === c.city_id ? '#38bdf8' : '#cbd5e1',
                      border: 'none',
                      cursor: 'pointer',
                      fontSize: '12px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                    }}
                  >
                    <span>{c.name}</span>
                    {selectedCity === c.city_id && <span style={{ color: '#38bdf8' }}>✓</span>}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* User Persona Pill */}
          <button
            onClick={() => setShowAuthModal(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '6px 12px',
              borderRadius: '8px',
              backgroundColor: '#1e293b',
              border: '1px solid #334155',
              color: '#f8fafc',
              fontSize: '12px',
              cursor: 'pointer',
            }}
          >
            <div style={{
              width: '20px',
              height: '20px',
              borderRadius: '50%',
              backgroundColor: '#0284c7',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '10px',
              fontWeight: 700,
            }}>
              {currentUser.username[0].toUpperCase()}
            </div>
            <span style={{ maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {currentUser.display_name.split(' ')[0]}
            </span>
            <span style={{ fontSize: '10px', color: '#94a3b8' }}>({currentUser.role})</span>
          </button>
        </div>
      </header>

      {/* ── Main View Switcher ─────────────────────────────────────── */}
      {currentView === 'studio' ? (
        /* ════════════════════════════════════════════════════════════
           PAGE 2: CONSUMER-FACING CHATGPT STUDIO APP
           ════════════════════════════════════════════════════════════ */
        <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
          {/* Left Conversation Sidebar */}
          <aside style={{
            width: '260px',
            backgroundColor: '#0a0f1d',
            borderRight: '1px solid #1e293b',
            display: 'flex',
            flexDirection: 'column',
          }}>
            {/* New Chat Button */}
            <div style={{ padding: '12px' }}>
              <button
                onClick={startNewChat}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  backgroundColor: '#1e293b',
                  color: '#f8fafc',
                  border: '1px solid #334155',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  transition: 'background-color 0.15s',
                }}
                onMouseOver={(e) => (e.currentTarget.style.backgroundColor = '#2d3748')}
                onMouseOut={(e) => (e.currentTarget.style.backgroundColor = '#1e293b')}
              >
                <Plus size={16} color="#38bdf8" />
                <span>New Chat</span>
              </button>
            </div>

            {/* Conversation Threads List */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 12px' }}>
              <div style={{ fontSize: '11px', color: '#64748b', fontWeight: 600, padding: '8px 10px 4px', textTransform: 'uppercase' }}>
                Recent Conversations
              </div>
              {conversations.length === 0 ? (
                <div style={{ padding: '16px 10px', fontSize: '12px', color: '#64748b', textAlign: 'center' }}>
                  No past conversations. Click "+ New Chat" to start.
                </div>
              ) : (
                conversations.map((c) => (
                  <div
                    key={c.conversation_id}
                    onClick={() => selectConversation(c.conversation_id)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      marginBottom: '2px',
                      cursor: 'pointer',
                      backgroundColor: currentConversationId === c.conversation_id ? '#1e293b' : 'transparent',
                      color: currentConversationId === c.conversation_id ? '#f8fafc' : '#94a3b8',
                      fontSize: '13px',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                      <MessageSquare size={14} color={currentConversationId === c.conversation_id ? '#38bdf8' : '#64748b'} />
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {c.title}
                      </span>
                    </div>
                    <button
                      onClick={(e) => deleteConversation(c.conversation_id, e)}
                      title="Delete chat"
                      style={{
                        background: 'none',
                        border: 'none',
                        color: '#64748b',
                        cursor: 'pointer',
                        padding: '2px',
                        display: 'flex',
                        alignItems: 'center',
                      }}
                      onMouseOver={(e) => (e.currentTarget.style.color = '#f43f5e')}
                      onMouseOut={(e) => (e.currentTarget.style.color = '#64748b')}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))
              )}
            </div>

            {/* Sidebar Footer: Microgrid Green Stats */}
            <div style={{
              padding: '12px',
              borderTop: '1px solid #1e293b',
              backgroundColor: '#090d16',
              fontSize: '11px',
              color: '#94a3b8',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#10b981', fontWeight: 600 }}>
                  <Zap size={13} /> Microgrid Green Tier
                </span>
                <span style={{ color: '#f59e0b', fontWeight: 600 }}>0.339 J/token</span>
              </div>
              <div style={{ color: '#64748b' }}>
                Inference locally executed on NVIDIA Jetson or AWS Bedrock fallback.
              </div>
            </div>
          </aside>

          {/* Main Chat Conversation Canvas */}
          <main style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', backgroundColor: '#090d16' }}>

            {/* Messages Scroll Area */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '24px 32px' }}>
              {chatMessages.length === 0 ? (
                /* Empty State / Welcome Screen */
                <div style={{ maxWidth: '680px', margin: '40px auto', textAlign: 'center' }}>
                  <div style={{
                    width: '56px',
                    height: '56px',
                    borderRadius: '16px',
                    backgroundColor: 'rgba(56, 189, 248, 0.1)',
                    border: '1px solid rgba(56, 189, 248, 0.3)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#38bdf8',
                    margin: '0 auto 16px',
                  }}>
                    <Sparkles size={28} />
                  </div>
                  <h1 style={{ fontSize: '24px', fontWeight: 700, margin: '0 0 8px', color: '#f8fafc' }}>
                    What would you like to explore today?
                  </h1>
                  <p style={{ fontSize: '14px', color: '#94a3b8', margin: '0 0 28px' }}>
                    SunRoute coordinates community edge solar nodes across Maharashtra with AWS Bedrock data center fallback.
                  </p>

                  {/* Suggestion prompt cards */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '12px', textAlign: 'left' }}>
                    {[
                      { title: 'Explain solar battery microgrids', desc: 'How localized batteries maintain continuous off-grid AI compute.' },
                      { title: 'What about electricity?', desc: 'Discover how clean energy flows dynamically to edge nodes.' },
                      { title: 'Jetson Orin Nano Super vs AWS Bedrock', desc: 'Compare 0.339 J/token edge compute against 7.2 J/token cloud.' },
                      { title: 'How does SunRoute routing work?', desc: 'Learn the 4-factor score: Energy, Latency, Locality, Fairness.' },
                    ].map((card, i) => (
                      <button
                        key={i}
                        onClick={() => handleSendStudioMessage(card.title)}
                        style={{
                          padding: '14px',
                          borderRadius: '10px',
                          backgroundColor: '#0f172a',
                          border: '1px solid #1e293b',
                          cursor: 'pointer',
                          textAlign: 'left',
                          transition: 'border-color 0.15s, background-color 0.15s',
                        }}
                        onMouseOver={(e) => {
                          e.currentTarget.style.borderColor = '#38bdf8';
                          e.currentTarget.style.backgroundColor = '#1e293b';
                        }}
                        onMouseOut={(e) => {
                          e.currentTarget.style.borderColor = '#1e293b';
                          e.currentTarget.style.backgroundColor = '#0f172a';
                        }}
                      >
                        <div style={{ fontSize: '13px', fontWeight: 600, color: '#f8fafc', marginBottom: '4px' }}>
                          {card.title}
                        </div>
                        <div style={{ fontSize: '12px', color: '#94a3b8' }}>
                          {card.desc}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                /* Chat Messages List */
                <div style={{ maxWidth: '820px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '20px' }}>
                  {chatMessages.map((msg) => (
                    <div
                      key={msg.id}
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: msg.sender === 'user' ? 'flex-end' : 'flex-start',
                      }}
                    >
                      {/* Avatar & Message Header */}
                      <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        marginBottom: '6px',
                        fontSize: '11px',
                        color: '#64748b',
                      }}>
                        {msg.sender === 'user' ? (
                          <>
                            <span>{currentUser.display_name}</span>
                            <User size={13} color="#38bdf8" />
                          </>
                        ) : (
                          <>
                            <Bot size={13} color="#10b981" />
                            <span>SunRoute Assistant</span>
                          </>
                        )}
                        <span>•</span>
                        <span>{msg.timestamp}</span>
                      </div>

                      {/* Message Content Bubble */}
                      <div style={{
                        maxWidth: '85%',
                        padding: '14px 18px',
                        borderRadius: msg.sender === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                        backgroundColor: msg.sender === 'user' ? '#1e293b' : '#0f172a',
                        border: `1px solid ${msg.sender === 'user' ? '#334155' : '#1e293b'}`,
                        color: '#f8fafc',
                        fontSize: '14px',
                        lineHeight: '1.6',
                        whiteSpace: 'pre-wrap',
                      }}>
                        {/* Attachments preview if user attached files */}
                        {msg.attachments && msg.attachments.length > 0 && (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '10px' }}>
                            {msg.attachments.map((att, idx) => (
                              <div
                                key={idx}
                                style={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '6px',
                                  padding: '4px 10px',
                                  borderRadius: '6px',
                                  backgroundColor: '#090d16',
                                  border: '1px solid #334155',
                                  fontSize: '12px',
                                  color: '#38bdf8',
                                }}
                              >
                                {att.mime_type.includes('image') ? <ImageIcon size={14} /> : <FileText size={14} />}
                                <span>{att.name}</span>
                                <span style={{ color: '#64748b', fontSize: '10px' }}>({Math.round(att.size / 1024)} KB)</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {msg.text}
                      </div>

                      {/* Transparent Microgrid Routing Badge */}
                      {msg.routing_metadata && (
                        <div style={{
                          marginTop: '8px',
                          maxWidth: '85%',
                          backgroundColor: '#0f172a',
                          border: '1px solid #1e293b',
                          borderRadius: '8px',
                          padding: '8px 12px',
                          fontSize: '12px',
                        }}>
                          <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            gap: '8px',
                          }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              {msg.routing_metadata.target_kind === 'cloud' ? (
                                <span style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '4px',
                                  padding: '2px 8px',
                                  borderRadius: '12px',
                                  backgroundColor: 'rgba(2, 132, 199, 0.2)',
                                  color: '#38bdf8',
                                  fontWeight: 600,
                                  fontSize: '11px',
                                }}>
                                  <Cloud size={12} /> AWS Bedrock Central Tier
                                </span>
                              ) : (
                                <span style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '4px',
                                  padding: '2px 8px',
                                  borderRadius: '12px',
                                  backgroundColor: 'rgba(16, 185, 129, 0.2)',
                                  color: '#10b981',
                                  fontWeight: 600,
                                  fontSize: '11px',
                                }}>
                                  <Zap size={12} /> {msg.routing_metadata.target_city_name || msg.routing_metadata.target_node_id}
                                </span>
                              )}
                              <span style={{ color: '#64748b' }}>({msg.routing_metadata.execution_latency_ms} ms)</span>
                              <span style={{ color: '#64748b' }}>•</span>
                              <span style={{ color: '#f59e0b' }}>{msg.routing_metadata.energy_consumed_j_est} J</span>
                            </div>

                            <button
                              onClick={() => setExpandedDecisionId(
                                expandedDecisionId === msg.routing_metadata?.decision_id ? null : (msg.routing_metadata?.decision_id || null)
                              )}
                              style={{
                                background: 'none',
                                border: 'none',
                                color: '#94a3b8',
                                cursor: 'pointer',
                                fontSize: '11px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '3px',
                              }}
                            >
                              <span>Router Rationale</span>
                              {expandedDecisionId === msg.routing_metadata.decision_id ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                            </button>
                          </div>

                          {/* Expandable 4-factor scoring breakdown */}
                          {expandedDecisionId === msg.routing_metadata.decision_id && (
                            <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid #1e293b' }}>
                              <div style={{ color: '#94a3b8', marginBottom: '6px' }}>
                                <strong>Decision Reason:</strong> {msg.routing_metadata.reason}
                              </div>
                              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '6px', textAlign: 'center' }}>
                                <div style={{ backgroundColor: '#090d16', padding: '6px', borderRadius: '4px' }}>
                                  <div style={{ fontSize: '10px', color: '#64748b' }}>Energy</div>
                                  <div style={{ fontWeight: 700, color: '#f59e0b' }}>{msg.routing_metadata.score_energy ?? 'N/A'}</div>
                                </div>
                                <div style={{ backgroundColor: '#090d16', padding: '6px', borderRadius: '4px' }}>
                                  <div style={{ fontSize: '10px', color: '#64748b' }}>Latency</div>
                                  <div style={{ fontWeight: 700, color: '#38bdf8' }}>{msg.routing_metadata.score_latency ?? 'N/A'}</div>
                                </div>
                                <div style={{ backgroundColor: '#090d16', padding: '6px', borderRadius: '4px' }}>
                                  <div style={{ fontSize: '10px', color: '#64748b' }}>Locality</div>
                                  <div style={{ fontWeight: 700, color: '#10b981' }}>{msg.routing_metadata.score_locality ?? 'N/A'}</div>
                                </div>
                                <div style={{ backgroundColor: '#090d16', padding: '6px', borderRadius: '4px' }}>
                                  <div style={{ fontSize: '10px', color: '#64748b' }}>Fairness</div>
                                  <div style={{ fontWeight: 700, color: '#a855f7' }}>{msg.routing_metadata.score_fairness ?? 'N/A'}</div>
                                </div>
                              </div>
                              <div style={{ fontSize: '10px', color: '#475569', marginTop: '6px' }}>
                                SQLite Decision Audit Record: {msg.routing_metadata.decision_id}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}

                  {/* Loading indicator */}
                  {isInferring && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#94a3b8', fontSize: '13px' }}>
                      <div style={{
                        width: '20px',
                        height: '20px',
                        borderRadius: '50%',
                        border: '2px solid #10b981',
                        borderTopColor: 'transparent',
                        animation: 'spin 1s linear infinite',
                      }} />
                      <span>Dispatching inference across solar microgrid mesh...</span>
                    </div>
                  )}

                  <div ref={chatBottomRef} />
                </div>
              )}
            </div>

            {/* Bottom Input Area */}
            <div style={{
              padding: '16px 24px 20px',
              borderTop: '1px solid #1e293b',
              backgroundColor: '#0a0f1d',
            }}>
              <div style={{ maxWidth: '820px', margin: '0 auto' }}>

                {/* File Attachment preview chips */}
                {attachedFiles.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '8px' }}>
                    {attachedFiles.map((file, i) => (
                      <div
                        key={i}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          padding: '4px 10px',
                          borderRadius: '6px',
                          backgroundColor: '#1e293b',
                          border: '1px solid #334155',
                          fontSize: '12px',
                          color: '#f8fafc',
                        }}
                      >
                        {file.mime_type.includes('image') ? <ImageIcon size={14} color="#38bdf8" /> : <FileText size={14} color="#f59e0b" />}
                        <span>{file.name}</span>
                        <button
                          onClick={() => removeAttachment(i)}
                          style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', padding: 0 }}
                        >
                          <X size={13} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {/* Main Input Box */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  backgroundColor: '#0f172a',
                  border: '1px solid #334155',
                  borderRadius: '12px',
                  padding: '8px 12px',
                  gap: '8px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
                }}>
                  {/* File attach button */}
                  <input
                    type="file"
                    ref={fileInputRef}
                    onChange={handleFileUpload}
                    style={{ display: 'none' }}
                  />
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    title="Attach file or image"
                    style={{
                      background: 'none',
                      border: 'none',
                      color: '#94a3b8',
                      cursor: 'pointer',
                      padding: '6px',
                      display: 'flex',
                      alignItems: 'center',
                      borderRadius: '6px',
                    }}
                    onMouseOver={(e) => (e.currentTarget.style.color = '#38bdf8')}
                    onMouseOut={(e) => (e.currentTarget.style.color = '#94a3b8')}
                  >
                    <Paperclip size={18} />
                  </button>

                  {/* Textarea */}
                  <textarea
                    rows={1}
                    value={promptInput}
                    onChange={(e) => setPromptInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleSendStudioMessage();
                      }
                    }}
                    placeholder={`Ask SunRoute AI (routed from ${activeCityName.split('(')[0]})...`}
                    style={{
                      flex: 1,
                      backgroundColor: 'transparent',
                      border: 'none',
                      color: '#f8fafc',
                      fontSize: '14px',
                      outline: 'none',
                      resize: 'none',
                      fontFamily: 'inherit',
                      maxHeight: '120px',
                    }}
                  />

                  {/* Send Button */}
                  <button
                    disabled={(!promptInput.trim() && attachedFiles.length === 0) || isInferring}
                    onClick={() => handleSendStudioMessage()}
                    style={{
                      width: '34px',
                      height: '34px',
                      borderRadius: '8px',
                      backgroundColor: (promptInput.trim() || attachedFiles.length > 0) && !isInferring ? '#38bdf8' : '#1e293b',
                      color: (promptInput.trim() || attachedFiles.length > 0) && !isInferring ? '#0f172a' : '#64748b',
                      border: 'none',
                      cursor: (promptInput.trim() || attachedFiles.length > 0) && !isInferring ? 'pointer' : 'default',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      transition: 'all 0.15s',
                    }}
                  >
                    <Send size={16} />
                  </button>
                </div>

                {/* Sub-bar policy and disclaimer */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginTop: '8px',
                  fontSize: '11px',
                  color: '#64748b',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span>Routing Policy:</span>
                    <select
                      value={policy}
                      onChange={(e) => setPolicy(e.target.value)}
                      style={{
                        backgroundColor: '#1e293b',
                        color: '#38bdf8',
                        border: '1px solid #334155',
                        borderRadius: '4px',
                        padding: '2px 6px',
                        fontSize: '11px',
                        cursor: 'pointer',
                      }}
                    >
                      <option value="proposed">Proposed Microgrid Policy</option>
                      <option value="cloud_only">AWS Bedrock Cloud Only</option>
                      <option value="edge_only">Local Edge Only</option>
                      <option value="cascade">Cascade Fallback</option>
                    </select>
                  </div>
                  <div>
                    SunRoute Edge AI may produce concise responses calibrated to clean energy limits.
                  </div>
                </div>

              </div>
            </div>

          </main>
        </div>
      ) : (
        /* ════════════════════════════════════════════════════════════
           PAGE 1: SYSTEM MONITOR & FLEET OPS COPILOT
           ════════════════════════════════════════════════════════════ */
        <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

          {/* Main Monitor Panels (Telemetry Grid & Audit Log) */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflowY: 'auto', padding: '20px 24px' }}>

            {/* KPI Metrics Row */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '14px', marginBottom: '20px' }}>
              <div style={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', borderRadius: '10px', padding: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: '#94a3b8', fontSize: '12px' }}>
                  <span>FLEET RENEWABLE GENERATION</span>
                  <Sun size={16} color="#f59e0b" />
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700, color: '#f59e0b', marginTop: '6px' }}>
                  {(totalFleetSolarW + totalFleetWindW).toFixed(1)} W
                </div>
                <div style={{ fontSize: '11px', color: '#64748b', marginTop: '4px' }}>
                  {totalFleetSolarW.toFixed(1)}W Solar | {totalFleetWindW.toFixed(1)}W Wind [SIMULATED]
                </div>
              </div>

              <div style={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', borderRadius: '10px', padding: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: '#94a3b8', fontSize: '12px' }}>
                  <span>FLEET BATTERY RESERVE</span>
                  <Battery size={16} color="#10b981" />
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700, color: '#10b981', marginTop: '6px' }}>
                  {(avgBatterySOC * 100).toFixed(1)}%
                </div>
                <div style={{ fontSize: '11px', color: '#64748b', marginTop: '4px' }}>
                  Average SOC across 30 microgrids
                </div>
              </div>

              <div style={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', borderRadius: '10px', padding: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: '#94a3b8', fontSize: '12px' }}>
                  <span>COMMUNITY EDGE SHARE</span>
                  <Zap size={16} color="#38bdf8" />
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700, color: '#38bdf8', marginTop: '6px' }}>
                  {metrics ? `${(metrics.community_edge_share * 100).toFixed(1)}%` : '93.4%'}
                </div>
                <div style={{ fontSize: '11px', color: '#64748b', marginTop: '4px' }}>
                  Cloud offload rate: {metrics ? `${(metrics.cloud_share * 100).toFixed(1)}%` : '6.6%'}
                </div>
              </div>

              <div style={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', borderRadius: '10px', padding: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: '#94a3b8', fontSize: '12px' }}>
                  <span>PHYSICAL JETSON ORIN NANO</span>
                  <Cpu size={16} color="#a855f7" />
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700, color: '#a855f7', marginTop: '6px' }}>
                  0.339 J/token
                </div>
                <div style={{ fontSize: '11px', color: '#10b981', marginTop: '4px' }}>
                  28.13 t/s • 9.557W Active [MEASURED]
                </div>
              </div>
            </div>

            {/* Region Filter Bar & Section Title */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <div style={{ fontSize: '16px', fontWeight: 700, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Layers size={18} color="#38bdf8" />
                <span>30-City Fleet Microgrid Telemetry</span>
                <span style={{ fontSize: '12px', fontWeight: 500, color: '#94a3b8' }}>
                  ({nodes.length} nodes active)
                </span>
              </div>

              {/* Region Selector Pills */}
              <div style={{ display: 'flex', gap: '6px' }}>
                {['all', 'region-central', 'region-north', 'region-south', 'region-east', 'region-west'].map((r) => (
                  <button
                    key={r}
                    onClick={() => setRegionFilter(r)}
                    style={{
                      padding: '4px 10px',
                      borderRadius: '6px',
                      fontSize: '11px',
                      fontWeight: 600,
                      border: '1px solid #334155',
                      cursor: 'pointer',
                      backgroundColor: regionFilter === r ? '#38bdf8' : '#1e293b',
                      color: regionFilter === r ? '#0f172a' : '#94a3b8',
                    }}
                  >
                    {r.replace('region-', '').toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            {/* Nodes Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '12px', marginBottom: '24px' }}>
              {filteredNodes.map((n) => {
                const isJetson = n.node_id === 'jetson-01';
                const isCloud = n.kind === 'cloud';
                return (
                  <div
                    key={n.node_id}
                    style={{
                      backgroundColor: '#0f172a',
                      border: `1px solid ${isJetson ? '#a855f7' : isCloud ? '#0284c7' : '#1e293b'}`,
                      borderRadius: '8px',
                      padding: '12px',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                      <span style={{ fontSize: '13px', fontWeight: 600, color: '#f8fafc' }}>
                        {n.city_name}
                      </span>
                      <span style={{
                        fontSize: '9px',
                        fontWeight: 700,
                        padding: '2px 6px',
                        borderRadius: '4px',
                        backgroundColor: isJetson ? 'rgba(168, 85, 247, 0.2)' : isCloud ? 'rgba(2, 132, 199, 0.2)' : 'rgba(16, 185, 129, 0.2)',
                        color: isJetson ? '#c084fc' : isCloud ? '#38bdf8' : '#34d399',
                      }}>
                        {isJetson ? 'PHYSICAL JETSON' : isCloud ? 'AWS BEDROCK' : 'DIGITAL TWIN'}
                      </span>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px', fontSize: '11px', marginBottom: '8px' }}>
                      <div>
                        <div style={{ color: '#64748b' }}>Battery</div>
                        <div style={{ fontWeight: 600, color: n.battery_soc > 0.6 ? '#10b981' : '#f59e0b' }}>
                          {(n.battery_soc * 100).toFixed(0)}%
                        </div>
                      </div>
                      <div>
                        <div style={{ color: '#64748b' }}>Solar</div>
                        <div style={{ fontWeight: 600, color: '#f59e0b' }}>{n.solar_w?.toFixed(1) || 0} W</div>
                      </div>
                      <div>
                        <div style={{ color: '#64748b' }}>Load</div>
                        <div style={{ fontWeight: 600, color: '#38bdf8' }}>{n.load_w?.toFixed(1) || 0} W</div>
                      </div>
                    </div>

                    <div style={{ fontSize: '10px', color: '#64748b', display: 'flex', justifyContent: 'space-between' }}>
                      <span>Temp: {n.temp_c?.toFixed(1)}°C</span>
                      <span>Queue: {n.queue_depth}</span>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Recent Decisions Audit Log Table */}
            <div style={{ marginTop: 'auto' }}>
              <div style={{ fontSize: '14px', fontWeight: 700, color: '#f8fafc', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Database size={16} color="#10b981" />
                <span>Append-Only SQLite Decision Audit Log</span>
              </div>
              <div style={{
                backgroundColor: '#0f172a',
                border: '1px solid #1e293b',
                borderRadius: '8px',
                overflow: 'hidden',
                maxHeight: '220px',
                overflowY: 'auto',
              }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', textAlign: 'left' }}>
                  <thead>
                    <tr style={{ backgroundColor: '#1e293b', color: '#94a3b8' }}>
                      <th style={{ padding: '8px 12px' }}>Timestamp</th>
                      <th style={{ padding: '8px 12px' }}>Origin</th>
                      <th style={{ padding: '8px 12px' }}>Target Node</th>
                      <th style={{ padding: '8px 12px' }}>Tier</th>
                      <th style={{ padding: '8px 12px' }}>Latency</th>
                      <th style={{ padding: '8px 12px' }}>Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {decisions.slice(0, 10).map((d) => (
                      <tr key={d.decision_id} style={{ borderBottom: '1px solid #1e293b', color: '#cbd5e1' }}>
                        <td style={{ padding: '6px 12px', color: '#64748b' }}>
                          {d.timestamp_iso ? new Date(d.timestamp_iso).toLocaleTimeString() : 'Just now'}
                        </td>
                        <td style={{ padding: '6px 12px' }}>{d.origin_city}</td>
                        <td style={{ padding: '6px 12px', fontWeight: 600 }}>{d.target_node_id}</td>
                        <td style={{ padding: '6px 12px' }}>
                          <span style={{
                            fontSize: '10px',
                            padding: '2px 6px',
                            borderRadius: '4px',
                            backgroundColor: d.target_kind === 'cloud' ? 'rgba(2,132,199,0.2)' : 'rgba(16,185,129,0.2)',
                            color: d.target_kind === 'cloud' ? '#38bdf8' : '#10b981',
                          }}>
                            {d.target_level}
                          </span>
                        </td>
                        <td style={{ padding: '6px 12px' }}>{d.execution_latency_ms} ms</td>
                        <td style={{ padding: '6px 12px', color: '#f59e0b' }}>{d.score_total?.toFixed(3) || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

          </div>

          {/* Right Panel: Integrated Ops AI Copilot Chat */}
          <aside style={{
            width: '380px',
            backgroundColor: '#0a0f1d',
            borderLeft: '1px solid #1e293b',
            display: 'flex',
            flexDirection: 'column',
          }}>
            {/* Copilot Header */}
            <div style={{
              padding: '14px 16px',
              borderBottom: '1px solid #1e293b',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              backgroundColor: '#0f172a',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div style={{
                  width: '28px',
                  height: '28px',
                  borderRadius: '6px',
                  backgroundColor: 'rgba(16, 185, 129, 0.15)',
                  border: '1px solid #10b981',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#10b981',
                }}>
                  <Terminal size={16} />
                </div>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>Fleet Ops AI Copilot</div>
                  <div style={{ fontSize: '10px', color: '#94a3b8' }}>Live Fleet Diagnostic Assistant</div>
                </div>
              </div>
              <span style={{ fontSize: '10px', color: '#10b981', fontWeight: 600 }}>ONLINE</span>
            </div>

            {/* Quick Diagnostic Chips */}
            <div style={{
              display: 'flex',
              gap: '6px',
              padding: '10px 14px',
              borderBottom: '1px solid #1e293b',
              overflowX: 'auto',
              backgroundColor: '#090d16',
            }}>
              {[
                { label: '🔋 Low Battery', q: 'Which nodes have low battery right now?' },
                { label: '☀️ Solar Stats', q: 'Show solar generation across all regions' },
                { label: '☁️ Cloud Rationale', q: 'Why was the last query routed to AWS Bedrock?' },
                { label: '📊 Health Summary', q: 'Summarize cluster health and carbon savings' },
              ].map((chip, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSendOpsCopilot(chip.q)}
                  style={{
                    padding: '4px 10px',
                    borderRadius: '12px',
                    backgroundColor: '#1e293b',
                    color: '#38bdf8',
                    border: '1px solid #334155',
                    fontSize: '11px',
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {chip.label}
                </button>
              ))}
            </div>

            {/* Copilot Messages Area */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {opsMessages.map((m, idx) => (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: m.sender === 'user' ? 'flex-end' : 'flex-start',
                  }}
                >
                  <div style={{ fontSize: '10px', color: '#64748b', marginBottom: '3px' }}>
                    {m.sender === 'user' ? 'Operator' : 'Ops Copilot'} • {m.time}
                  </div>
                  <div style={{
                    maxWidth: '92%',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    backgroundColor: m.sender === 'user' ? '#1e293b' : '#0f172a',
                    border: `1px solid ${m.sender === 'user' ? '#334155' : '#1e293b'}`,
                    color: '#f8fafc',
                    fontSize: '12px',
                    lineHeight: '1.5',
                    whiteSpace: 'pre-wrap',
                  }}>
                    {m.text}
                  </div>
                </div>
              ))}

              {isOpsLoading && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#94a3b8', fontSize: '11px' }}>
                  <RefreshCw size={12} className="spin" />
                  <span>Synthesizing live node telemetry...</span>
                </div>
              )}
              <div ref={opsBottomRef} />
            </div>

            {/* Copilot Input Box */}
            <div style={{ padding: '12px', borderTop: '1px solid #1e293b', backgroundColor: '#0f172a' }}>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                backgroundColor: '#090d16',
                border: '1px solid #334155',
                borderRadius: '8px',
                padding: '6px 10px',
                gap: '6px',
              }}>
                <input
                  type="text"
                  value={opsPrompt}
                  onChange={(e) => setOpsPrompt(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSendOpsCopilot()}
                  placeholder="Ask Ops Copilot about nodes, solar, battery..."
                  style={{
                    flex: 1,
                    backgroundColor: 'transparent',
                    border: 'none',
                    color: '#f8fafc',
                    fontSize: '12px',
                    outline: 'none',
                  }}
                />
                <button
                  onClick={() => handleSendOpsCopilot()}
                  disabled={!opsPrompt.trim() || isOpsLoading}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: opsPrompt.trim() ? '#10b981' : '#64748b',
                    cursor: opsPrompt.trim() ? 'pointer' : 'default',
                    padding: '4px',
                    display: 'flex',
                    alignItems: 'center',
                  }}
                >
                  <Send size={14} />
                </button>
              </div>
            </div>

          </aside>
        </div>
      )}

      {/* ── Demo Persona & Login Modal ─────────────────────────────── */}
      {showAuthModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.7)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 200,
        }}>
          <div style={{
            width: '420px',
            backgroundColor: '#0f172a',
            border: '1px solid #334155',
            borderRadius: '12px',
            padding: '24px',
            boxShadow: '0 20px 40px rgba(0,0,0,0.8)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
              <div style={{ fontSize: '18px', fontWeight: 700, color: '#f8fafc' }}>Demo Login & Personas</div>
              <button
                onClick={() => setShowAuthModal(false)}
                style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}
              >
                <X size={18} />
              </button>
            </div>

            <p style={{ fontSize: '13px', color: '#94a3b8', margin: '0 0 16px' }}>
              Select a pre-configured demo user persona or enter custom credentials:
            </p>

            {/* Quick Persona Buttons */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '20px' }}>
              {DEMO_PERSONAS.map((p) => (
                <button
                  key={p.user_id}
                  onClick={() => handlePersonaSelect(p)}
                  style={{
                    padding: '10px 14px',
                    borderRadius: '8px',
                    backgroundColor: currentUser.user_id === p.user_id ? '#1e293b' : '#090d16',
                    border: `1px solid ${currentUser.user_id === p.user_id ? '#38bdf8' : '#334155'}`,
                    color: '#f8fafc',
                    textAlign: 'left',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 600 }}>{p.display_name}</div>
                    <div style={{ fontSize: '11px', color: '#64748b' }}>Username: {p.username} • Default: {p.default_city}</div>
                  </div>
                  {currentUser.user_id === p.user_id && <span style={{ color: '#38bdf8', fontWeight: 700 }}>Active</span>}
                </button>
              ))}
            </div>

            {/* Custom Login Form */}
            <form onSubmit={handleCustomLogin} style={{ borderTop: '1px solid #1e293b', paddingTop: '16px' }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', marginBottom: '8px' }}>
                OR ENTER CUSTOM CREDENTIALS
              </div>
              <input
                type="text"
                value={authUsername}
                onChange={(e) => setAuthUsername(e.target.value)}
                placeholder="User ID / Username (e.g. roll_no_12)"
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  backgroundColor: '#090d16',
                  border: '1px solid #334155',
                  color: '#f8fafc',
                  fontSize: '13px',
                  marginBottom: '10px',
                  outline: 'none',
                }}
              />
              <input
                type="password"
                value={authPassword}
                onChange={(e) => setAuthPassword(e.target.value)}
                placeholder="Password (demo default: demo)"
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  backgroundColor: '#090d16',
                  border: '1px solid #334155',
                  color: '#f8fafc',
                  fontSize: '13px',
                  marginBottom: '14px',
                  outline: 'none',
                }}
              />
              <button
                type="submit"
                style={{
                  width: '100%',
                  padding: '10px',
                  borderRadius: '6px',
                  backgroundColor: '#38bdf8',
                  color: '#0f172a',
                  border: 'none',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Sign In to Studio
              </button>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
