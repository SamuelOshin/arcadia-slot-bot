import React, { useState, useEffect, useRef } from 'react';
import { 
  Terminal, 
  Search, 
  Trash2, 
  Copy, 
  ArrowDownCircle, 
  Check, 
  Activity,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import type { LogTrace } from '../types';

interface LogConsoleProps {
  logs: LogTrace[];
  onClear: () => void;
}

export const LogConsole: React.FC<LogConsoleProps> = ({ logs, onClear }) => {
  const [filterLevel, setFilterLevel] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [isCollapsed, setIsCollapsed] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Scroll ONLY the inner terminal container, NOT the outer window
  useEffect(() => {
    if (autoScroll && containerRef.current && !isCollapsed) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs, autoScroll, isCollapsed]);

  const filteredLogs = logs.filter((log) => {
    if (filterLevel !== 'ALL' && log.level.toUpperCase() !== filterLevel) {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return log.line.toLowerCase().includes(q) || log.event.toLowerCase().includes(q);
    }
    return true;
  });

  const handleCopyLogs = () => {
    const text = filteredLogs.map((l) => l.line).join('\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getLevelBadgeClass = (level: string) => {
    switch (level.toUpperCase()) {
      case 'SUCCESS':
      case 'LOCK':
        return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
      case 'WARNING':
      case 'WARN':
        return 'bg-amber-500/20 text-amber-400 border-amber-500/30';
      case 'ERROR':
      case 'FAIL':
        return 'bg-rose-500/20 text-rose-400 border-rose-500/30';
      case 'DEBUG':
        return 'bg-purple-500/20 text-purple-400 border-purple-500/30';
      default:
        return 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30';
    }
  };

  return (
    <div className={`glass-panel rounded-2xl border border-slate-800 flex flex-col overflow-hidden transition-all duration-300 ${
      isCollapsed ? 'h-auto' : 'h-[520px]'
    }`}>
      
      {/* Console Header / Action Toolbar */}
      <div className="px-5 py-3.5 bg-slate-900/90 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center space-x-2.5">
          <Terminal className="w-5 h-5 text-cyan-400" />
          <h2 className="font-semibold text-white text-sm font-mono tracking-tight">
            Live Stream Log Terminal
          </h2>
          <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
            {filteredLogs.length} events
          </span>
        </div>

        <div className="flex items-center space-x-2">
          
          {!isCollapsed && (
            <>
              {/* Search Input */}
              <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-500" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search logs..."
                  className="bg-slate-950/80 border border-slate-800 rounded-lg text-xs text-slate-200 pl-8 pr-3 py-1.5 focus:outline-none focus:border-cyan-500/50 font-mono w-36 sm:w-48 placeholder:text-slate-600"
                />
              </div>

              {/* Level Filter Dropdown */}
              <select
                value={filterLevel}
                onChange={(e) => setFilterLevel(e.target.value)}
                className="bg-slate-950/80 border border-slate-800 rounded-lg text-xs text-slate-200 px-2.5 py-1.5 focus:outline-none focus:border-cyan-500/50 font-mono"
              >
                <option value="ALL">All Levels</option>
                <option value="INFO">INFO</option>
                <option value="SUCCESS">SUCCESS</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
              </select>

              {/* Auto Scroll Toggle */}
              <button
                onClick={() => setAutoScroll(!autoScroll)}
                className={`p-1.5 rounded-lg border text-xs transition-all ${
                  autoScroll 
                    ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40' 
                    : 'bg-slate-950 text-slate-500 border-slate-800'
                }`}
                title="Auto-scroll"
              >
                <ArrowDownCircle className="w-4 h-4" />
              </button>

              {/* Copy Logs */}
              <button
                onClick={handleCopyLogs}
                className="p-1.5 rounded-lg bg-slate-950 text-slate-400 border border-slate-800 hover:text-white hover:border-slate-700 transition-all"
                title="Copy Logs"
              >
                {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
              </button>

              {/* Clear Buffer */}
              <button
                onClick={onClear}
                className="p-1.5 rounded-lg bg-slate-950 text-slate-400 border border-slate-800 hover:text-rose-400 hover:border-rose-500/30 transition-all"
                title="Clear Log View"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </>
          )}

          {/* Collapse / Expand Toggle */}
          <button
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="flex items-center space-x-1 px-2.5 py-1.5 rounded-lg bg-slate-950 text-slate-400 border border-slate-800 hover:text-cyan-400 hover:border-cyan-500/30 text-xs font-mono transition-all"
            title={isCollapsed ? "Expand Terminal" : "Collapse Terminal"}
          >
            <span>{isCollapsed ? "Expand" : "Collapse"}</span>
            {isCollapsed ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
          </button>

        </div>
      </div>

      {/* Terminal View Body (Hidden when collapsed) */}
      {!isCollapsed && (
        <div 
          ref={containerRef}
          className="flex-1 bg-slate-950/95 p-4 overflow-y-auto font-mono text-xs space-y-1.5 leading-relaxed selection:bg-cyan-500/30"
        >
          {filteredLogs.length === 0 ? (
            <div className="h-full flex items-center justify-center text-slate-600 space-x-2">
              <Activity className="w-4 h-4 animate-pulse" />
              <span>Listening for live execution events...</span>
            </div>
          ) : (
            filteredLogs.map((log) => (
              <div key={log.id} className="flex items-start space-x-2 hover:bg-slate-900/60 p-1 rounded transition-colors group">
                
                {/* Level Badge */}
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border uppercase shrink-0 mt-0.5 ${getLevelBadgeClass(log.level)}`}>
                  {log.level}
                </span>

                {/* Timestamp */}
                <span className="text-slate-500 text-[11px] shrink-0 font-mono">
                  {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : ''}
                </span>

                {/* Log Line Text */}
                <span className="text-slate-300 break-all font-mono">
                  {log.line}
                </span>

              </div>
            ))
          )}
        </div>
      )}

    </div>
  );
};
