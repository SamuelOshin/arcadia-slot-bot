import React, { useState } from 'react';
import { 
  Lock, 
  DollarSign, 
  Layers, 
  Sparkles, 
  CheckCircle2, 
  XCircle,
  RefreshCw,
  Tag
} from 'lucide-react';
import type { Campaign } from '../types';

interface CampaignsBoardProps {
  campaigns: Campaign[];
  isLoading: boolean;
  onRefresh: () => void;
  onLockCampaign: (campaignId: string) => Promise<{ success: boolean; message: string }>;
}

export const CampaignsBoard: React.FC<CampaignsBoardProps> = ({
  campaigns,
  isLoading,
  onRefresh,
  onLockCampaign,
}) => {
  const [lockingMap, setLockingMap] = useState<Record<string, boolean>>({});
  const [feedbackMap, setFeedbackMap] = useState<Record<string, { success: boolean; message: string }>>({});

  const handleLock = async (campaignId: string) => {
    setLockingMap((prev) => ({ ...prev, [campaignId]: true }));
    setFeedbackMap((prev) => ({ ...prev, [campaignId]: undefined as any }));

    try {
      const res = await onLockCampaign(campaignId);
      setFeedbackMap((prev) => ({ ...prev, [campaignId]: res }));
    } catch (err: any) {
      setFeedbackMap((prev) => ({
        ...prev,
        [campaignId]: { success: false, message: err.message || 'Lock request failed' },
      }));
    } finally {
      setLockingMap((prev) => ({ ...prev, [campaignId]: false }));
    }
  };

  const formatPayout = (c: Campaign) => {
    if (c.kind === 'ugc' && c.postPrice) {
      return `$${c.postPrice}/post`;
    }
    if (c.cpmRules && c.cpmRules.length > 0) {
      const bronze = c.cpmRules.find((r) => r.tier === 'bronze');
      const rate = bronze ? bronze.ratePerThousand : c.cpmRules[0].ratePerThousand;
      return `$${rate}/1K`;
    }
    return 'Dynamic';
  };

  return (
    <div className="space-y-4">
      
      {/* Board Top Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Sparkles className="w-5 h-5 text-cyan-400" />
          <h2 className="font-semibold text-white text-lg tracking-tight font-sans">
            Active Campaign Drops
          </h2>
          <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            {campaigns.length} available
          </span>
        </div>

        <button
          onClick={onRefresh}
          disabled={isLoading}
          className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-slate-900 text-slate-300 border border-slate-800 hover:text-cyan-400 hover:border-cyan-500/30 text-xs font-mono transition-all disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin text-cyan-400' : ''}`} />
          <span>Refresh Drops</span>
        </button>
      </div>

      {/* Campaigns Grid */}
      {campaigns.length === 0 ? (
        <div className="glass-card rounded-2xl p-12 text-center text-slate-500">
          <Layers className="w-8 h-8 mx-auto mb-3 text-slate-600 animate-pulse" />
          <p className="font-mono text-sm">No active campaigns discovered yet.</p>
          <p className="text-xs text-slate-600 mt-1">
            The background scheduler will automatically broadcast new drops as soon as they appear.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {campaigns.map((c) => {
            const isLocking = lockingMap[c.id] || false;
            const feedback = feedbackMap[c.id];
            const remaining = c.slotsRemaining ?? (c.scheduledSlots ? c.scheduledSlots.length : 0);

            return (
              <div key={c.id} className="glass-card rounded-2xl p-5 flex flex-col justify-between relative group">
                
                {/* Header */}
                <div>
                  <div className="flex items-start justify-between gap-2 mb-3">
                    <h3 className="font-semibold text-white text-sm tracking-tight font-sans group-hover:text-cyan-300 transition-colors line-clamp-2">
                      {c.title}
                    </h3>

                    {/* Payout Badge */}
                    <span className="shrink-0 px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 text-xs font-mono font-bold flex items-center space-x-1">
                      <DollarSign className="w-3.5 h-3.5" />
                      <span>{formatPayout(c)}</span>
                    </span>
                  </div>

                  {/* Campaign Attributes */}
                  <div className="flex flex-wrap items-center gap-2 mb-4 text-xs font-mono text-slate-400">
                    
                    <span className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-300 flex items-center space-x-1">
                      <Tag className="w-3 h-3 text-cyan-400" />
                      <span className="uppercase">{c.kind}</span>
                    </span>

                    <span className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-300">
                      {remaining > 0 ? `${remaining} Open Slots` : 'Full / Check Detail'}
                    </span>

                    {c.reservation && !c.reservation.reservedEligibleForMe && (
                      <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[10px]" title="Gold Tier Restricted">
                        Gold Reserved
                      </span>
                    )}

                  </div>
                </div>

                {/* Lock Action Footer */}
                <div className="pt-3 border-t border-slate-900/80">
                  
                  {feedback ? (
                    <div className={`p-2.5 rounded-xl border text-xs font-mono flex items-center space-x-2 mb-2 ${
                      feedback.success
                        ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                        : 'bg-rose-500/10 text-rose-300 border-rose-500/30'
                    }`}>
                      {feedback.success ? (
                        <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                      ) : (
                        <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
                      )}
                      <span className="truncate">{feedback.message}</span>
                    </div>
                  ) : null}

                  <button
                    onClick={() => handleLock(c.id)}
                    disabled={isLocking}
                    className="w-full py-2.5 px-4 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 hover:from-cyan-400 hover:to-emerald-400 text-slate-950 font-bold text-xs tracking-wide transition-all shadow-[0_0_15px_rgba(6,182,212,0.25)] flex items-center justify-center space-x-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isLocking ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin text-slate-950" />
                        <span>Locking Slot...</span>
                      </>
                    ) : (
                      <>
                        <Lock className="w-4 h-4 text-slate-950" />
                        <span>Lock Slot Now</span>
                      </>
                    )}
                  </button>

                </div>

              </div>
            );
          })}
        </div>
      )}

    </div>
  );
};
