export interface AccountInfo {
  index: number;
  name: string;
  label: string;
  is_valid: boolean;
  has_token: boolean;
  daily_count: number;
  max_slots_per_day: number;
  last_check: string | null;
  tracked_campaigns: number;
}

export interface BotStats {
  total_accounts: number;
  active_accounts: number;
  slots_locked_today: number;
  is_paused: boolean;
  auto_lock_enabled: boolean;
  poll_interval: number;
}

export interface ScheduledSlot {
  _id: string;
  slotNumber: number;
  scheduledPostAt: string;
  clipGroupId: string;
  taken?: boolean;
  isMine?: boolean;
  reservedForGold?: boolean;
  blockedForMe?: boolean;
}

export interface Campaign {
  id: string;
  title: string;
  kind: 'ugc' | 'cpm' | string;
  status: string;
  postPrice?: number;
  slotsRemaining?: number;
  cpmRules?: Array<{ tier: string; ratePerThousand: number }>;
  reservation?: {
    reservedEligibleForMe?: boolean;
    generalCapacity?: number;
    generalLocked?: number;
  };
  scheduledSlots?: ScheduledSlot[];
  myLock?: any;
  mySubmission?: any;
}

export interface LogTrace {
  id: string;
  timestamp: string;
  level: string;
  event: string;
  line: string;
  extras?: Record<string, any>;
}

export interface LockedRecord {
  id: string;
  account_name: string;
  campaign_id: string;
  campaign_title: string;
  slot_number?: number | null;
  slot_id?: string | null;
  payout?: string | null;
  strategy: string;
  response_time_ms: number;
  locked_at: string;
  success: boolean;
  status: string;
  reason?: string | null;
}
