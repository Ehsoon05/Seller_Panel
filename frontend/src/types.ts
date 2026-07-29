export interface Seller {
  id: number;
  username: string;
  display_name: string;
  wallet_balance: number;
  allow_negative_balance: boolean;
  is_active: boolean;
}

export interface Dashboard {
  total_services: number;
  active_services: number;
  used_bytes: number;
  monthly_spend: number;
  wallet_balance: number;
}

export interface Offer {
  id: number;
  title: string;
  panel_key: string;
  price_toman: number;
  pricing_mode: "fixed" | "per_gb";
  price_per_gb_toman: number;
  volume_gb: number;
  lock_volume: boolean;
  default_duration_days: number;
  allowed_time_modes: string[];
  default_time_mode: string;
  lock_time: boolean;
  lock_time_mode: boolean;
  lock_duration: boolean;
  subscription_device_limit: number;
}

export interface Service {
  id: number;
  offer_id: number;
  panel_key: string;
  panel_username: string;
  display_name: string | null;
  public_url: string;
  volume_gb: number;
  duration_days: number;
  time_mode: string;
  price_toman: number;
  status: string;
  used_bytes: number;
  data_limit_bytes: number;
  remaining_bytes: number;
  expires_at: string | null;
  online_at: string | null;
  last_refreshed_at: string | null;
  created_at: string;
}

export interface Ledger {
  id: number;
  amount: number;
  balance_after: number;
  kind: string;
  description: string;
  service_id: number | null;
  created_at: string;
}
