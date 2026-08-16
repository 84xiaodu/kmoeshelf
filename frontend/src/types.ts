export type ContentType = "volume" | "extra" | "serial";
export type DownloadFormat = "epub" | "mobi";
export type TaskStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export interface AuthStatus {
  setup_required: boolean;
  authenticated: boolean;
}

export interface AuthResult {
  authenticated: boolean;
  csrf_token: string;
}

export interface KmoeStatus {
  connected: boolean;
  email: string | null;
  mirror: string | null;
  status: string | null;
}

export interface ComicSummary {
  remote_id: string;
  title: string;
  author: string | null;
  language: string | null;
  detail_path: string;
  cover_url: string | null;
}

export interface RemoteItem {
  remote_id: string;
  content_type: ContentType;
  name: string;
  sort_order: number | null;
  page_count: number | null;
  mobi_size_mb: string | number | null;
  epub_size_mb: string | number | null;
}

export interface ComicDetails extends ComicSummary {
  description: string | null;
  items: RemoteItem[];
}

export interface SearchPage {
  query: string;
  current_page: number;
  total_pages: number;
  results: ComicSummary[];
}

export interface Subscription {
  id: number;
  comic_id: number;
  remote_id: string;
  title: string;
  author: string | null;
  cover_url: string | null;
  enabled: boolean;
  content_types: ContentType[];
  download_format: DownloadFormat;
  initialization_strategy: "backfill" | "future_only";
  last_attempt_at: string | null;
  last_success_at: string | null;
  next_check_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
}

export interface DownloadTask {
  id: number;
  comic_id: number;
  comic_remote_id: string;
  comic_title: string;
  item_remote_id: string;
  item_name: string;
  content_type: ContentType;
  download_format: DownloadFormat;
  status: TaskStatus;
  attempt_count: number;
  progress_bytes: number;
  total_bytes: number | null;
  final_path: string | null;
  error_code: string | null;
  error_message: string | null;
  next_attempt_at: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface AppSettings {
  check_interval_hours: number;
  download_concurrency: number;
  max_download_retries: number;
  preferred_mirror: string;
}

export interface CheckEnqueue {
  batch_id: number;
  queued_count: number;
  created: boolean;
}
