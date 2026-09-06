import { useEffect, useMemo, useState } from "react";
import { api, messageOf } from "../api";
import type { DownloadSnapshot, DownloadTask, TaskStatus } from "../types";
import { Alert, EmptyState, formatBytes, formatDate, Spinner } from "../ui";

const statuses: [TaskStatus | "", string][] = [["", "全部"], ["running", "下载中"], ["pending", "等待"], ["failed", "失败"], ["completed", "完成"], ["cancelled", "已取消"]];
const statusLabel: Record<TaskStatus, string> = { pending: "等待中", running: "下载中", completed: "已完成", failed: "失败", cancelled: "已取消" };
const errorAdvice: Record<string, string> = {
  download_forbidden: "下载节点拒绝了请求。请先在设置中重新登录 Kmoe，再重试任务。",
  download_url_expired: "临时下载地址已过期，点击重试会重新获取地址。",
  auth_expired: "Kmoe 登录已失效，请在设置中重新登录后重试。",
  connect_timeout: "连接下载节点超时，请稍后重试并检查宿主机网络。",
  download_server_error: "下载节点暂时不可用，稍后重试即可。",
  non_file_response: "远端返回的不是漫画文件，请重新登录；若持续出现请保留错误码。",
  download_range_invalid: "远端续传范围异常，重试时会重新校验临时文件。",
  storage_not_writable: "当前保存目录不可写，请在设置中检查挂载权限或切换目录。",
};

export default function Downloads() {
  const [snapshot, setSnapshot] = useState<DownloadSnapshot>({
    tasks: [],
    counts: { pending: 0, running: 0, completed: 0, failed: 0, cancelled: 0 },
  });
  const [filter, setFilter] = useState<TaskStatus | "">("");
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let receivedDownloadEvent = false;
    setLoading(true);
    void api.downloads(filter || undefined)
      .then((next) => { if (active && !receivedDownloadEvent) setSnapshot(next); })
      .catch((reason) => { if (active) setError(messageOf(reason)); })
      .finally(() => { if (active) setLoading(false); });
    const statusQuery = filter ? `?status=${filter}` : "";
    const events = new EventSource(`/api/downloads/events${statusQuery}`);
    const update = (event: MessageEvent<string>) => {
      if (!active) return;
      try { const next = JSON.parse(event.data) as DownloadSnapshot; receivedDownloadEvent = true; setSnapshot(next); setLive(true); }
      catch { setError("下载状态事件格式无效"); }
    };
    events.addEventListener("downloads", update as EventListener);
    events.onerror = () => { if (active) setLive(false); };
    return () => { active = false; events.close(); };
  }, [filter]);
  const visible = useMemo(() => filter ? snapshot.tasks.filter((task) => task.status === filter) : snapshot.tasks, [filter, snapshot.tasks]);
  async function mutate(action: () => Promise<DownloadTask>) {
    setError("");
    try { const next = await action(); setSnapshot((current) => ({ ...current, tasks: current.tasks.map((task) => task.id === next.id ? next : task) })); }
    catch (reason) { setError(messageOf(reason)); }
  }
  return <section className="page">
    <header className="page-head"><div><p className="eyebrow">传输中心</p><h1>下载任务</h1><p><span className={`live-indicator ${live ? "is-live" : ""}`} />{live ? "实时状态已连接" : "正在连接实时状态"}</p></div></header>
    {error && <Alert>{error}</Alert>}
    <div className="filter-tabs" role="tablist" aria-label="任务状态">{statuses.map(([value, label]) => <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{label}<span>{value ? snapshot.counts[value] : Object.values(snapshot.counts).reduce((total, count) => total + count, 0)}</span></button>)}</div>
    {loading ? <Spinner /> : !visible.length ? <EmptyState title="当前筛选没有任务">任务由补齐订阅或追新检查自动创建。</EmptyState> : <div className="task-list">{visible.map((task) => <TaskRow key={task.id} task={task} mutate={mutate} />)}</div>}
  </section>;
}

function TaskRow({ task, mutate }: { task: DownloadTask; mutate: (action: () => Promise<DownloadTask>) => Promise<void> }) {
  const percentage = task.total_bytes ? Math.min(100, Math.round(task.progress_bytes / task.total_bytes * 100)) : 0;
  return <article className="task-row"><div className="task-top"><div><span className={`pill status-${task.status}`}>{statusLabel[task.status]}</span><small>任务 #{task.id}</small><h2>{task.comic_title}</h2><p>{task.item_name} · {task.content_type} · {task.download_format.toUpperCase()}</p></div><div className="task-actions">{["pending", "running"].includes(task.status) && <button className="button button-quiet" onClick={() => void mutate(() => api.cancelDownload(task.id))}>取消</button>}{["failed", "cancelled"].includes(task.status) && <button className="button button-primary" onClick={() => void mutate(() => api.retryDownload(task.id))}>重试</button>}</div></div>
    {(task.status === "running" || task.progress_bytes > 0) && <div className="progress"><div><span>已传输 {formatBytes(task.progress_bytes)}{task.total_bytes ? ` / ${formatBytes(task.total_bytes)}` : ""}</span><strong>{task.total_bytes ? `${percentage}%` : "计算中"}</strong></div><progress max="100" value={percentage} /></div>}
    {task.error_message && <Alert>{task.error_message} <code>{task.error_code}</code>{task.error_code && errorAdvice[task.error_code] && <span className="error-advice">{errorAdvice[task.error_code]}</span>}</Alert>}
    <footer className="task-meta"><span>尝试 {task.attempt_count} 次</span><span>创建于 {formatDate(task.created_at)}</span>{task.next_attempt_at && <span>下次重试 {formatDate(task.next_attempt_at)}</span>}{task.final_path && <span className="path" title={task.final_path}>{task.final_path}</span>}</footer></article>;
}
