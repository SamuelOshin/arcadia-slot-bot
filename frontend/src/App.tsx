import React, { useState, useEffect, useCallback } from 'react';
import { Header } from './components/Header';
import { AccountCard } from './components/AccountCard';
import { LogConsole } from './components/LogConsole';
import { CampaignsBoard } from './components/CampaignsBoard';
import { LockedLedger } from './components/LockedLedger';
import { ConfigModal } from './components/ConfigModal';
import type { AccountInfo, BotStats, Campaign, LogTrace, LockedRecord } from './types';
import { LayoutDashboard, Flame, Terminal, Lock } from 'lucide-react';

export const App: React.FC = () => {
  const [stats, setStats] = useState<BotStats | null>(null);
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [lockedRecords, setLockedRecords] = useState<LockedRecord[]>([]);
  const [logs, setLogs] = useState<LogTrace[]>([]);
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [isLoadingCampaigns, setIsLoadingCampaigns] = useState<boolean>(false);
  const [isLoadingLedger, setIsLoadingLedger] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<'console' | 'campaigns' | 'ledger' | 'logs'>('console');
  const [isSettingsOpen, setIsSettingsOpen] = useState<boolean>(false);

  // Fetch Stats & Accounts
  const fetchDashboardData = useCallback(async () => {
    try {
      const [statsRes, accountsRes] = await Promise.all([
        fetch('/api/v1/dashboard/stats').then((r) => (r.ok ? r.json() : null)),
        fetch('/api/v1/dashboard/accounts').then((r) => (r.ok ? r.json() : null)),
      ]);

      if (statsRes) setStats(statsRes);
      if (accountsRes && accountsRes.accounts) setAccounts(accountsRes.accounts);
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err);
    }
  }, []);

  // Fetch Available Campaigns
  const fetchCampaigns = useCallback(async () => {
    setIsLoadingCampaigns(true);
    try {
      const res = await fetch('/api/v1/campaigns');
      if (res.ok) {
        const data = await res.json();
        setCampaigns(data);
      }
    } catch (err) {
      console.error('Failed to fetch campaigns:', err);
    } finally {
      setIsLoadingCampaigns(false);
    }
  }, []);

  // Fetch Locked Slot History Ledger
  const fetchLockedLedger = useCallback(async () => {
    setIsLoadingLedger(true);
    try {
      const res = await fetch('/api/v1/slots/locked');
      if (res.ok) {
        const data = await res.json();
        if (data && data.records) {
          setLockedRecords(data.records);
        }
      }
    } catch (err) {
      console.error('Failed to fetch lock ledger:', err);
    } finally {
      setIsLoadingLedger(false);
    }
  }, []);

  // Initialize SSE Live Stream
  useEffect(() => {
    fetchDashboardData();
    fetchCampaigns();
    fetchLockedLedger();

    const eventSource = new EventSource('/api/v1/events/stream');

    eventSource.onopen = () => {
      setIsConnected(true);
    };

    eventSource.onerror = () => {
      setIsConnected(false);
    };

    // Handle initial logs bulk push
    eventSource.addEventListener('initial_logs', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        if (data.logs && Array.isArray(data.logs)) {
          const initialTraces: LogTrace[] = data.logs.map((line: string, idx: number) => ({
            id: `init-${idx}-${Date.now()}`,
            timestamp: new Date().toISOString(),
            level: line.includes('ERROR') ? 'ERROR' : line.includes('WARNING') ? 'WARN' : 'INFO',
            event: 'initial_log',
            line,
          }));
          setLogs(initialTraces);
        }
      } catch (err) {
        console.error('Failed to parse initial logs:', err);
      }
    });

    // Handle live incoming log line
    eventSource.addEventListener('log', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        const newTrace: LogTrace = {
          id: `log-${Date.now()}-${Math.random()}`,
          timestamp: data.timestamp || new Date().toISOString(),
          level: data.level || 'INFO',
          event: data.event || '',
          line: data.line || '',
          extras: data.extras,
        };
        setLogs((prev) => [...prev.slice(-400), newTrace]);
      } catch (err) {
        console.error('Failed to parse SSE log:', err);
      }
    });

    // Polling fallback interval for stats & ledger
    const pollTimer = setInterval(() => {
      fetchDashboardData();
      fetchLockedLedger();
    }, 4000);

    return () => {
      eventSource.close();
      clearInterval(pollTimer);
    };
  }, [fetchDashboardData, fetchCampaigns, fetchLockedLedger]);

  // Toggle Bot Pause / Resume
  const handleTogglePause = async () => {
    const isPaused = stats?.is_paused ?? false;
    const endpoint = isPaused ? '/api/v1/dashboard/resume' : '/api/v1/dashboard/pause';
    try {
      const res = await fetch(endpoint, { method: 'POST' });
      if (res.ok) {
        fetchDashboardData();
      }
    } catch (err) {
      console.error('Failed to toggle pause:', err);
    }
  };

  // Refresh Account Session
  const handleRefreshAccountSession = async (index: number) => {
    try {
      const res = await fetch(`/api/v1/dashboard/accounts/${index}/refresh`, { method: 'POST' });
      if (res.ok) {
        fetchDashboardData();
      }
    } catch (err) {
      console.error('Failed to refresh session:', err);
    }
  };

  // Manual Lock Campaign
  const handleLockCampaign = async (campaignId: string) => {
    try {
      const res = await fetch(`/api/v1/slots/lock/${campaignId}`, { method: 'POST' });
      const data = await res.json();
      fetchDashboardData();
      fetchCampaigns();
      fetchLockedLedger();
      if (res.ok && data.success) {
        return { success: true, message: data.message || 'Slot claimed successfully!' };
      }
      return { success: false, message: data.message || 'Slot claim failed' };
    } catch (err: any) {
      return { success: false, message: err.message || 'Network request error' };
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 font-sans selection:bg-cyan-500/30">
      
      {/* Top Fixed Header */}
      <Header
        stats={stats}
        isConnected={isConnected}
        onTogglePause={handleTogglePause}
        onRefresh={() => {
          fetchDashboardData();
          fetchCampaigns();
          fetchLockedLedger();
        }}
        onOpenSettings={() => setIsSettingsOpen(true)}
      />

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 lg:px-8 pb-12 space-y-6">
        
        {/* Navigation Tabs */}
        <div className="flex items-center space-x-2 border-b border-slate-900 pb-3">
          
          <button
            onClick={() => setActiveTab('console')}
            className={`flex items-center space-x-2 px-4 py-2 rounded-xl text-xs font-mono font-medium transition-all ${
              activeTab === 'console'
                ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 shadow-[0_0_15px_rgba(6,182,212,0.15)]'
                : 'text-slate-400 hover:text-white hover:bg-slate-900'
            }`}
          >
            <LayoutDashboard className="w-4 h-4" />
            <span>Command Console</span>
          </button>

          <button
            onClick={() => setActiveTab('campaigns')}
            className={`flex items-center space-x-2 px-4 py-2 rounded-xl text-xs font-mono font-medium transition-all ${
              activeTab === 'campaigns'
                ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 shadow-[0_0_15px_rgba(6,182,212,0.15)]'
                : 'text-slate-400 hover:text-white hover:bg-slate-900'
            }`}
          >
            <Flame className="w-4 h-4" />
            <span>Campaign Drops ({campaigns.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('ledger')}
            className={`flex items-center space-x-2 px-4 py-2 rounded-xl text-xs font-mono font-medium transition-all ${
              activeTab === 'ledger'
                ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 shadow-[0_0_15px_rgba(6,182,212,0.15)]'
                : 'text-slate-400 hover:text-white hover:bg-slate-900'
            }`}
          >
            <Lock className="w-4 h-4" />
            <span>Locked Ledger ({lockedRecords.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('logs')}
            className={`flex items-center space-x-2 px-4 py-2 rounded-xl text-xs font-mono font-medium transition-all ${
              activeTab === 'logs'
                ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 shadow-[0_0_15px_rgba(6,182,212,0.15)]'
                : 'text-slate-400 hover:text-white hover:bg-slate-900'
            }`}
          >
            <Terminal className="w-4 h-4" />
            <span>Terminal Stream ({logs.length})</span>
          </button>

        </div>

        {/* Tab Content 1: Command Console (Accounts Grid + Live Terminal Split Pane) */}
        {activeTab === 'console' && (
          <div className="space-y-6">
            
            {/* Accounts Grid */}
            <div>
              <h2 className="text-sm font-mono font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Active Account Workers ({accounts.length})
              </h2>

              {accounts.length === 0 ? (
                <div className="glass-card p-6 rounded-2xl text-center font-mono text-xs text-slate-500">
                  Loading account monitors...
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {accounts.map((acc) => (
                    <AccountCard
                      key={acc.name}
                      account={acc}
                      onRefreshSession={handleRefreshAccountSession}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Live Terminal Log Stream */}
            <div>
              <h2 className="text-sm font-mono font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Live Execution Logs
              </h2>
              <LogConsole logs={logs} onClear={() => setLogs([])} />
            </div>

          </div>
        )}

        {/* Tab Content 2: Active Campaign Drops */}
        {activeTab === 'campaigns' && (
          <CampaignsBoard
            campaigns={campaigns}
            isLoading={isLoadingCampaigns}
            onRefresh={fetchCampaigns}
            onLockCampaign={handleLockCampaign}
          />
        )}

        {/* Tab Content 3: Locked Slots & Attempt Ledger */}
        {activeTab === 'ledger' && (
          <LockedLedger
            records={lockedRecords}
            isLoading={isLoadingLedger}
            onRefresh={fetchLockedLedger}
          />
        )}

        {/* Tab Content 4: Full Terminal Log View */}
        {activeTab === 'logs' && (
          <div>
            <LogConsole logs={logs} onClear={() => setLogs([])} />
          </div>
        )}

      </main>

      {/* Settings Modal */}
      <ConfigModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        stats={stats}
      />

    </div>
  );
};

export default App;
