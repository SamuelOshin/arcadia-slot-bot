import React, { useState } from 'react';
import { 
  UserCheck, 
  RotateCw, 
  Key, 
  Layers,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import type { AccountInfo } from '../types';

interface AccountCardProps {
  account: AccountInfo;
  onRefreshSession: (index: number) => Promise<void>;
}

export const AccountCard: React.FC<AccountCardProps> = ({ account, onRefreshSession }) => {
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await onRefreshSession(account.index);
    } finally {
      setIsRefreshing(false);
    }
  };

  const quotaPercent = Math.min(
    100,
    Math.round((account.daily_count / Math.max(1, account.max_slots_per_day)) * 100)
  );

  return (
    <div className="glass-card rounded-2xl p-5 relative overflow-hidden transition-all duration-300">
      
      {/* Background Subtle Accent Glow */}
      <div 
        className={`absolute top-0 left-0 right-0 h-1 ${
          account.is_valid ? 'bg-gradient-to-r from-emerald-500 to-cyan-500' : 'bg-rose-500'
        }`}
      />

      {/* Account Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center space-x-3">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center border ${
            account.is_valid 
              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' 
              : 'bg-rose-500/10 text-rose-400 border-rose-500/20'
          }`}>
            <UserCheck className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-semibold text-white text-base tracking-tight font-sans">
              {account.label || account.name}
            </h3>
            <div className="flex items-center space-x-2 mt-0.5">
              <span className={`inline-flex items-center space-x-1 text-[11px] font-mono px-2 py-0.5 rounded-md ${
                account.is_valid 
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' 
                  : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
              }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${account.is_valid ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}`} />
                <span>{account.is_valid ? 'Session Active' : 'Session Invalid'}</span>
              </span>

              {account.has_token && (
                <span className="text-[10px] font-mono text-cyan-400 flex items-center space-x-1" title="Auth Token Available">
                  <Key className="w-3 h-3" />
                  <span>Token</span>
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Refresh Session Button */}
        <button
          onClick={handleRefresh}
          disabled={isRefreshing}
          className="p-2 rounded-lg bg-slate-900/80 text-slate-400 border border-slate-800 hover:text-cyan-400 hover:border-cyan-500/30 transition-all disabled:opacity-50"
          title="Verify & Refresh Session"
        >
          <RotateCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin text-cyan-400' : ''}`} />
        </button>
      </div>

      {/* Quota Progress Bar */}
      <div className="mb-4 bg-slate-950/60 rounded-xl p-3 border border-slate-900">
        <div className="flex justify-between items-center text-xs font-mono mb-1.5">
          <span className="text-slate-400">Daily Slot Quota</span>
          <span className="text-white font-semibold">
            {account.daily_count} / {account.max_slots_per_day}
          </span>
        </div>
        <div className="w-full h-2 bg-slate-900 rounded-full overflow-hidden">
          <div 
            className="h-full bg-gradient-to-r from-cyan-500 to-emerald-400 transition-all duration-500 rounded-full"
            style={{ width: `${quotaPercent}%` }}
          />
        </div>
      </div>

      {/* Account Info Footer */}
      <div className="flex items-center justify-between text-xs text-slate-400 pt-2 border-t border-slate-900">
        <div className="flex items-center space-x-1.5 font-mono text-[11px]">
          <Layers className="w-3.5 h-3.5 text-cyan-400" />
          <span>{account.tracked_campaigns} Campaigns</span>
        </div>

        <button
          onClick={() => setShowDetails(!showDetails)}
          className="flex items-center space-x-1 text-[11px] font-mono text-slate-400 hover:text-cyan-400 transition-colors"
        >
          <span>{showDetails ? 'Hide' : 'Details'}</span>
          {showDetails ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* Expandable Details Drawer */}
      {showDetails && (
        <div className="mt-3 pt-3 border-t border-slate-900/80 text-xs font-mono space-y-1.5 text-slate-400 animate-fadeIn">
          <div className="flex justify-between">
            <span>Account ID:</span>
            <span className="text-slate-200">{account.name}</span>
          </div>
          <div className="flex justify-between">
            <span>Account Index:</span>
            <span className="text-slate-200">#{account.index}</span>
          </div>
          <div className="flex justify-between">
            <span>Last Status Check:</span>
            <span className="text-slate-200">{account.last_check ? new Date(account.last_check).toLocaleTimeString() : 'Pending'}</span>
          </div>
        </div>
      )}

    </div>
  );
};
