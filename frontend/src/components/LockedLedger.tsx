import React, { useState } from 'react';
import { 
  Lock, 
  CheckCircle2, 
  XCircle, 
  AlertCircle, 
  Clock, 
  Zap, 
  Search, 
  Copy, 
  Check, 
  RefreshCw, 
  UserCheck
} from 'lucide-react';
import type { LockedRecord } from '../types';

interface LockedLedgerProps {
  records: LockedRecord[];
  isLoading: boolean;
  onRefresh: () => void;
}

export const LockedLedger: React.FC<LockedLedgerProps> = ({
  records,
  isLoading,
  onRefresh,
}) => {
  const [filterTab, setFilterTab] = useState<'ALL' | 'SUCCESS' | 'FAILED'>('ALL');
  const [selectedAccount, setSelectedAccount] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Extract unique accounts from records
  const accountNames = Array.from(new Set(records.map((r) => r.account_name)));

  // Filter records
  const filteredRecords = records.filter((r) => {
    if (filterTab === 'SUCCESS' && !r.success) return false;
    if (filterTab === 'FAILED' && r.success) return false;
    if (selectedAccount !== 'ALL' && r.account_name !== selectedAccount) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return (
        r.campaign_title.toLowerCase().includes(q) ||
        r.account_name.toLowerCase().includes(q) ||
        (r.reason && r.reason.toLowerCase().includes(q))
      );
    }
    return true;
  });

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const getStatusBadge = (r: LockedRecord) => {
    if (r.success) {
      return (
        <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 text-xs font-mono font-semibold">
          <CheckCircle2 className="w-3.5 h-3.5" />
          <span>LOCKED</span>
        </span>
      );
    }

    const st = (r.status || '').toUpperCase();
    if (st === 'SLOT_TAKEN') {
      return (
        <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-rose-500/10 text-rose-400 border border-rose-500/30 text-xs font-mono font-semibold" title={r.reason || 'Slot taken by another bot'}>
          <XCircle className="w-3.5 h-3.5" />
          <span>SLOT TAKEN</span>
        </span>
      );
    }

    if (st === 'QUOTA_EXCEEDED') {
      return (
        <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/30 text-xs font-mono font-semibold" title={r.reason || 'Daily quota limit reached'}>
          <AlertCircle className="w-3.5 h-3.5" />
          <span>QUOTA EXCEEDED</span>
        </span>
      );
    }

    return (
      <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-rose-500/10 text-rose-400 border border-rose-500/30 text-xs font-mono font-semibold" title={r.reason || 'Attempt failed'}>
        <XCircle className="w-3.5 h-3.5" />
        <span>FAILED</span>
      </span>
    );
  };

  const getLatencyBadge = (ms: number) => {
    if (ms <= 100) {
      return (
        <span className="text-[11px] font-mono text-emerald-400 flex items-center space-x-1" title="Direct API Fast Lock">
          <Zap className="w-3 h-3 text-emerald-400" />
          <span>{ms}ms</span>
        </span>
      );
    }
    if (ms <= 1000) {
      return (
        <span className="text-[11px] font-mono text-cyan-400 flex items-center space-x-1">
          <Zap className="w-3 h-3 text-cyan-400" />
          <span>{ms}ms</span>
        </span>
      );
    }
    return (
      <span className="text-[11px] font-mono text-amber-400 flex items-center space-x-1">
        <Clock className="w-3 h-3 text-amber-400" />
        <span>{(ms / 1000).toFixed(1)}s</span>
      </span>
    );
  };

  const totalSuccess = records.filter((r) => r.success).length;
  const totalFailed = records.filter((r) => !r.success).length;

  return (
    <div className="space-y-4">
      
      {/* Top Filter & Toolbar Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900/90 border border-slate-800 rounded-2xl p-4 glass-panel">
        
        {/* Status Segment Controls */}
        <div className="flex items-center space-x-1 bg-slate-950/80 p-1 rounded-xl border border-slate-800">
          <button
            onClick={() => setFilterTab('ALL')}
            className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-all ${
              filterTab === 'ALL'
                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            All Attempts ({records.length})
          </button>

          <button
            onClick={() => setFilterTab('SUCCESS')}
            className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-all ${
              filterTab === 'SUCCESS'
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Locked ({totalSuccess})
          </button>

          <button
            onClick={() => setFilterTab('FAILED')}
            className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-all ${
              filterTab === 'FAILED'
                ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Missed ({totalFailed})
          </button>
        </div>

        {/* Search & Account Filter */}
        <div className="flex items-center space-x-2">
          
          {/* Account Filter */}
          <select
            value={selectedAccount}
            onChange={(e) => setSelectedAccount(e.target.value)}
            className="bg-slate-950/80 border border-slate-800 rounded-xl text-xs font-mono text-slate-200 px-3 py-2 focus:outline-none focus:border-cyan-500/50"
          >
            <option value="ALL">All Accounts</option>
            {accountNames.map((acc) => (
              <option key={acc} value={acc}>{acc}</option>
            ))}
          </select>

          {/* Search Box */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-3 text-slate-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search campaign..."
              className="bg-slate-950/80 border border-slate-800 rounded-xl text-xs text-slate-200 pl-8 pr-3 py-2 focus:outline-none focus:border-cyan-500/50 font-mono w-40 sm:w-52 placeholder:text-slate-600"
            />
          </div>

          {/* Refresh Button */}
          <button
            onClick={onRefresh}
            disabled={isLoading}
            className="p-2 rounded-xl bg-slate-950 text-slate-400 border border-slate-800 hover:text-cyan-400 hover:border-cyan-500/30 transition-all disabled:opacity-50"
            title="Refresh Ledger"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin text-cyan-400' : ''}`} />
          </button>

        </div>

      </div>

      {/* Ledger Records Table / Cards */}
      {filteredRecords.length === 0 ? (
        <div className="glass-card rounded-2xl p-12 text-center text-slate-500">
          <Lock className="w-8 h-8 mx-auto mb-3 text-slate-600 animate-pulse" />
          <p className="font-mono text-sm">No slot lock records match your current filter.</p>
          <p className="text-xs text-slate-600 mt-1">
            Lock attempts triggered automatically or manually will populate this audit ledger in real-time.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredRecords.map((r) => (
            <div key={r.id} className="glass-card rounded-xl p-4 border border-slate-800 flex flex-wrap items-center justify-between gap-4 hover:border-slate-700 transition-all">
              
              {/* Left Column: Account & Campaign Title */}
              <div className="flex items-center space-x-3.5 min-w-[260px]">
                <div className={`w-9 h-9 rounded-xl flex items-center justify-center border shrink-0 ${
                  r.success 
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' 
                    : 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                }`}>
                  <UserCheck className="w-4 h-4" />
                </div>

                <div>
                  <div className="flex items-center space-x-2">
                    <span className="text-xs font-mono font-semibold text-cyan-400">
                      {r.account_name}
                    </span>
                    {r.slot_number !== null && r.slot_number !== undefined && (
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-900 text-slate-300 border border-slate-800">
                        Slot #{r.slot_number}
                      </span>
                    )}
                  </div>
                  <h4 className="font-medium text-white text-sm font-sans tracking-tight mt-0.5">
                    {r.campaign_title}
                  </h4>
                </div>
              </div>

              {/* Center Column: Status, Latency, Timestamp */}
              <div className="flex items-center space-x-4 text-xs font-mono">
                
                {/* Status Badge */}
                {getStatusBadge(r)}

                {/* Latency Speed */}
                {getLatencyBadge(r.response_time_ms)}

                {/* Locked Time */}
                <span className="text-slate-400 text-[11px]">
                  {r.locked_at ? new Date(r.locked_at).toLocaleTimeString() : ''}
                </span>

              </div>

              {/* Right Column: Reason or Copy Action */}
              <div className="flex items-center space-x-2">
                
                {r.reason && !r.success && (
                  <span className="text-[11px] font-mono text-slate-400 max-w-[220px] truncate" title={r.reason}>
                    {r.reason}
                  </span>
                )}

                {(r.slot_id || r.campaign_id) && (
                  <button
                    onClick={() => handleCopy(r.id, r.slot_id || r.campaign_id)}
                    className="p-1.5 rounded-lg bg-slate-950 text-slate-400 border border-slate-800 hover:text-white hover:border-slate-700 transition-all text-xs font-mono flex items-center space-x-1"
                    title="Copy Lock ID"
                  >
                    {copiedId === r.id ? (
                      <Check className="w-3.5 h-3.5 text-emerald-400" />
                    ) : (
                      <Copy className="w-3.5 h-3.5" />
                    )}
                  </button>
                )}

              </div>

            </div>
          ))}
        </div>
      )}

    </div>
  );
};
