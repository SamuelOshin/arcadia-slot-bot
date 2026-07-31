import React, { useState } from 'react';
import { 
  X, 
  Sliders, 
  Save, 
  ShieldCheck, 
  Clock, 
  DollarSign, 
  Layers
} from 'lucide-react';
import type { BotStats } from '../types';

interface ConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  stats: BotStats | null;
}

export const ConfigModal: React.FC<ConfigModalProps> = ({ isOpen, onClose, stats }) => {
  const [pollInterval, setPollInterval] = useState<number>(stats?.poll_interval ?? 3);
  const [minPayout, setMinPayout] = useState<number>(0);
  const [maxSlotsPerDay, setMaxSlotsPerDay] = useState<number>(3);
  const [autoLock, setAutoLock] = useState<boolean>(stats?.auto_lock_enabled ?? true);
  const [saved, setSaved] = useState<boolean>(false);

  if (!isOpen) return null;

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setSaved(true);
    setTimeout(() => {
      setSaved(false);
      onClose();
    }, 1500);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-fadeIn">
      <div className="glass-panel rounded-2xl max-w-lg w-full overflow-hidden border border-slate-800 shadow-2xl">
        
        {/* Header */}
        <div className="px-6 py-4 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <Sliders className="w-5 h-5 text-cyan-400" />
            <h2 className="font-semibold text-white text-base tracking-tight font-sans">
              Bot Engine Configuration
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSave} className="p-6 space-y-5 font-sans">
          
          {/* Auto Lock Toggle */}
          <div className="flex items-center justify-between p-3.5 rounded-xl bg-slate-950/60 border border-slate-900">
            <div>
              <div className="text-sm font-semibold text-white">Auto-Lock Engine</div>
              <div className="text-xs text-slate-400 font-mono">Automatically target and lock discovered slots</div>
            </div>
            <button
              type="button"
              onClick={() => setAutoLock(!autoLock)}
              className={`w-12 h-6 rounded-full transition-colors p-1 relative ${
                autoLock ? 'bg-emerald-500' : 'bg-slate-800'
              }`}
            >
              <div 
                className={`w-4 h-4 rounded-full bg-slate-950 transition-transform ${
                  autoLock ? 'translate-x-6' : 'translate-x-0'
                }`}
              />
            </button>
          </div>

          {/* Poll Interval Slider */}
          <div>
            <div className="flex justify-between items-center text-xs font-mono mb-2">
              <span className="text-slate-300 flex items-center space-x-1">
                <Clock className="w-3.5 h-3.5 text-cyan-400" />
                <span>Poll Interval (Seconds)</span>
              </span>
              <span className="text-cyan-400 font-bold">{pollInterval}s</span>
            </div>
            <input
              type="range"
              min="1"
              max="15"
              step="1"
              value={pollInterval}
              onChange={(e) => setPollInterval(Number(e.target.value))}
              className="w-full h-2 bg-slate-900 rounded-lg appearance-none cursor-pointer accent-cyan-500"
            />
          </div>

          {/* Minimum Payout Filter */}
          <div>
            <div className="flex justify-between items-center text-xs font-mono mb-2">
              <span className="text-slate-300 flex items-center space-x-1">
                <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
                <span>Minimum Payout Filter</span>
              </span>
              <span className="text-emerald-400 font-bold">${minPayout}</span>
            </div>
            <input
              type="number"
              min="0"
              step="0.5"
              value={minPayout}
              onChange={(e) => setMinPayout(Number(e.target.value))}
              className="w-full bg-slate-950/80 border border-slate-800 rounded-xl px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-cyan-500/50"
            />
          </div>

          {/* Max Slots Per Day */}
          <div>
            <div className="flex justify-between items-center text-xs font-mono mb-2">
              <span className="text-slate-300 flex items-center space-x-1">
                <Layers className="w-3.5 h-3.5 text-cyan-400" />
                <span>Daily Quota Cap Per Account</span>
              </span>
              <span className="text-cyan-400 font-bold">{maxSlotsPerDay} slots</span>
            </div>
            <input
              type="number"
              min="1"
              max="20"
              value={maxSlotsPerDay}
              onChange={(e) => setMaxSlotsPerDay(Number(e.target.value))}
              className="w-full bg-slate-950/80 border border-slate-800 rounded-xl px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-cyan-500/50"
            />
          </div>

          {/* Save Action */}
          <div className="pt-3 border-t border-slate-900 flex justify-end space-x-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-medium text-slate-400 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-5 py-2 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs transition-all shadow-[0_0_15px_rgba(6,182,212,0.3)] flex items-center space-x-1.5"
            >
              {saved ? <ShieldCheck className="w-4 h-4" /> : <Save className="w-4 h-4" />}
              <span>{saved ? 'Saved!' : 'Save Settings'}</span>
            </button>
          </div>

        </form>

      </div>
    </div>
  );
};
