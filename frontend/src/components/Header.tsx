import React from 'react';
import { 
  Zap, 
  PauseCircle, 
  PlayCircle, 
  RefreshCw, 
  Sliders, 
  Radio,
  Lock,
  Users
} from 'lucide-react';
import type { BotStats } from '../types';

interface HeaderProps {
  stats: BotStats | null;
  isConnected: boolean;
  onTogglePause: () => void;
  onRefresh: () => void;
  onOpenSettings: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  stats,
  isConnected,
  onTogglePause,
  onRefresh,
  onOpenSettings,
}) => {
  const isPaused = stats?.is_paused ?? false;

  return (
    <header className="sticky top-0 z-40 glass-panel border-b border-slate-800/80 px-4 lg:px-8 py-3.5 mb-6">
      <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
        
        {/* Brand & Logo */}
        <div className="flex items-center space-x-3">
          <div className="relative">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-emerald-400 flex items-center justify-center shadow-[0_0_15px_rgba(6,182,212,0.4)]">
              <Zap className="w-5 h-5 text-slate-950 stroke-[2.5]" />
            </div>
            <span className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-slate-950 ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-rose-500'}`} />
          </div>

          <div>
            <div className="flex items-center space-x-2">
              <h1 className="font-bold text-lg tracking-tight text-white font-sans">
                Arcadia Slot Bot
              </h1>
              <span className="text-[10px] font-mono font-medium px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                v1.0.0 Multi-Strategy
              </span>
            </div>
            <p className="text-xs text-slate-400 font-mono">
              High-Frequency Parallel Auto-Lock Engine
            </p>
          </div>
        </div>

        {/* Center Live KPI Counters */}
        <div className="hidden md:flex items-center space-x-6 bg-slate-900/80 border border-slate-800 rounded-xl px-4 py-2">
          
          {/* Active Accounts */}
          <div className="flex items-center space-x-2.5">
            <Users className="w-4 h-4 text-cyan-400" />
            <div>
              <div className="text-[10px] uppercase font-mono text-slate-400">Accounts</div>
              <div className="text-sm font-semibold text-white font-mono">
                {stats ? `${stats.active_accounts}/${stats.total_accounts}` : '--'}
              </div>
            </div>
          </div>

          <div className="w-px h-6 bg-slate-800" />

          {/* Slots Locked Today */}
          <div className="flex items-center space-x-2.5">
            <Lock className="w-4 h-4 text-emerald-400" />
            <div>
              <div className="text-[10px] uppercase font-mono text-slate-400">Slots Locked</div>
              <div className="text-sm font-semibold text-emerald-400 font-mono">
                {stats?.slots_locked_today ?? 0}
              </div>
            </div>
          </div>

          <div className="w-px h-6 bg-slate-800" />

          {/* Live SSE Status */}
          <div className="flex items-center space-x-2">
            <Radio className={`w-4 h-4 ${isConnected ? 'text-emerald-400 animate-pulse' : 'text-slate-500'}`} />
            <span className="text-xs font-mono text-slate-300">
              {isConnected ? 'LIVE STREAM' : 'DISCONNECTED'}
            </span>
          </div>
        </div>

        {/* Right Action Controls */}
        <div className="flex items-center space-x-2.5">
          {/* Pause / Resume Toggle */}
          <button
            onClick={onTogglePause}
            className={`flex items-center space-x-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
              isPaused 
                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/20' 
                : 'bg-rose-500/10 text-rose-400 border border-rose-500/30 hover:bg-rose-500/20'
            }`}
          >
            {isPaused ? <PlayCircle className="w-4 h-4" /> : <PauseCircle className="w-4 h-4" />}
            <span>{isPaused ? 'Resume Bot' : 'Pause Bot'}</span>
          </button>

          {/* Manual Refresh */}
          <button
            onClick={onRefresh}
            className="p-2 rounded-lg bg-slate-900 text-slate-300 border border-slate-800 hover:border-slate-700 hover:text-white transition-all"
            title="Refresh Data"
          >
            <RefreshCw className="w-4 h-4" />
          </button>

          {/* Settings Modal Toggle */}
          <button
            onClick={onOpenSettings}
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 hover:bg-cyan-500/20 text-xs font-medium transition-all"
          >
            <Sliders className="w-4 h-4" />
            <span className="hidden sm:inline">Settings</span>
          </button>
        </div>

      </div>
    </header>
  );
};
