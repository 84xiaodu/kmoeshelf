export type ContentType = "volume" | "extra" | "serial";
export type DownloadFormat = "epub" | "mobi";
export type InitializationStrategy = "backfill" | "future_only";
export type TaskStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type StorageMigrationPhase = "pending" | "waiting_for_downloads" | "copying" | "committing" | "cleaning" | "completed" | "failed";

export interface PolicyImpact {
  created: number;
  converted: number;
  reused: number;
  cancelled: number;
  retained_running: number;
  retained_completed: number;
}

export interface AuthStatus {
  setup_required: boolean;
  authenticated: boolean;
}

export interface AuthResult {
  authenticated: boolean;
  csrf_token: string;
}

export interface KmoeQuotaUsage {
  total_mb: number | null;
  used_mb: number | null;
  remaining_mb: number | null;
  reset_day: number | null;
}

export interface KmoeUsage {
  user_level: number | null;
  is_vip: boolean | null;
  free: KmoeQuotaUsage | null;
  vip: KmoeQuotaUsage | null;
  checked_at: string | null;
}

export interface KmoeStatus {
  connected: boolean;
  email: string | null;
  mirror: string | null;
  status: string | null;
  usage: KmoeUsage | null;
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

export type BangumiCollectionType = "wish" | "collect" | "doing" | "on_hold" | "dropped";

export interface SubscriptionSource {
  id: number;
  source_type: "bangumi";
  name: string;
  enabled: boolean;
  username: string;
  collection_types: BangumiCollectionType[];
  sync_interval_hours: number;
  item_count: number;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
}

export interface SubscriptionSourceItem {
  id: number;
  source_id: number;
  external_id: string;
  title: string;
  original_title: string | null;
  source_status: BangumiCollectionType;
  cover_url: string | null;
  external_url: string;
  search_query: string;
  first_seen_at: string;
  last_seen_at: string;
}

export interface SourceSync {
  source: SubscriptionSource;
  imported_count: number;
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
  initialization_strategy: InitializationStrategy;
  last_attempt_at: string | null;
  last_success_at: string | null;
  next_check_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  reconciliation?: PolicyImpact | null;
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

export interface DownloadSnapshot {
  tasks: DownloadTask[];
  counts: Record<TaskStatus, number>;
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

export interface StorageMigration {
  id: number;
  source_subpath: string;
  target_subpath: string;
  phase: StorageMigrationPhase;
  failed_phase: StorageMigrationPhase | null;
  total_files: number;
  processed_files: number;
  total_bytes: number;
  processed_bytes: number;
  current_relative_path: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface StorageStatus {
  mounted_root: string;
  active_subpath: string;
  effective_path: string;
  writable: boolean;
  migration: StorageMigration | null;
}

export interface StoragePreview {
  source_subpath: string;
  target_subpath: string;
  total_files: number;
  total_bytes: number;
}

export interface DirectoryListing {
  path: string;
  directories: string[];
}
