import { useEffect, useMemo, useState } from "react";
import { api, messageOf } from "../api";
import type { DownloadSnapshot, KmoeStatus, Subscription } from "../types";
import { Alert, EmptyState, formatDate, Spinner } from "../ui";

export default function Dashboard({ kmoe }: { kmoe: KmoeStatus | null }) {
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [downloads, setDownloads] = useState<DownloadSnapshot>({
    tasks: [],
    counts: { pending: 0, running: 0, completed: 0, failed: 0, cancelled: 0 },
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function load() {
    try {
      const [subs, tasks] = await Promise.all([api.subscriptions(), api.downloads()]);
      setSubscriptions(subs); setDownloads(tasks);
    } catch (reason) { setError(messageOf(reason)); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  const counts = useMemo(() => ({
    active: subscriptions.filter((item) => item.enabled).length,
    errors: subscriptions.filter((item) => item.last_error_code).length,
    running: downloads.counts.running,
    pending: downloads.counts.pending,
  }), [subscriptions, downloads.counts]);
  const next = subscriptions.filter((item) => item.next_check_at).sort((a, b) => a.next_check_at!.localeCompare(b.next_check_at!))[0]?.next_check_at ?? null;
  const quotaRemaining = remainingQuota(kmoe);
  async function checkAll() {
    setError(""); setNotice("");
    try {
      const result = await api.checkAll();
      setNotice(result.created ? `已加入 ${result.queued_count} 个订阅检查` : "已有检查批次正在运行");
    } catch (reason) { setError(messageOf(reason)); }
  }
  return <section className="page">
    <header className="page-head"><div><p className="eyebrow">书架概览</p><h1>今天也在自动追新</h1><p>快速查看订阅健康度与最近下载。</p></div><button className="button button-primary" onClick={() => void checkAll()} disabled={!subscriptions.length}>立即检查全部</button></header>
    {error && <Alert>{error}</Alert>}{notice && <Alert tone="success">{notice}</Alert>}
    {loading ? <Spinner /> : <>
      <div className="stat-grid">
        <article className="stat-card accent"><span>启用订阅</span><strong>{counts.active}</strong><small>{subscriptions.length} 个订阅总计</small></article>
        <article className="stat-card"><span>正在下载</span><strong>{counts.running}</strong><small>{counts.pending} 个等待中</small></article>
        <article className="stat-card"><span>异常订阅</span><strong>{counts.errors}</strong><small>{counts.errors ? "需要检查错误信息" : "状态良好"}</small></article>
        <article className="stat-card"><span>Kmoe 会话</span><strong className="status-word">{kmoe?.connected ? "已连接" : "需登录"}</strong><small>{quotaRemaining === null ? (kmoe?.mirror ?? "尚未选择镜像") : `剩余 ${formatQuota(quotaRemaining)}`}</small></article>
      </div>
      <div className="dashboard-grid">
        <article className="panel next-check"><p className="eyebrow">下一次自动检查</p><h2>{formatDate(next)}</h2><p>检查间隔可在设置中调整；手动检查不会改变已有基线。</p></article>
        <article className="panel"><div className="panel-head"><h2>最近任务</h2><a href="#/downloads">查看全部 →</a></div>
          {!downloads.tasks.length ? <EmptyState title="还没有下载任务">创建一个补齐已有内容的订阅后，任务会出现在这里。</EmptyState> : <div className="compact-list">{downloads.tasks.slice(0, 5).map((task) => <div key={task.id}><span className={`status-dot status-${task.status}`} /><span><strong>{task.comic_title}</strong><small>{task.item_name}</small></span><em>{statusLabel[task.status]}</em></div>)}</div>}
        </article>
      </div>
    </>}
  </section>;
}

function remainingQuota(status: KmoeStatus | null) {
  const free = status?.usage?.free?.remaining_mb;
  const vip = status?.usage?.vip?.remaining_mb;
  return free == null && vip == null ? null : (free ?? 0) + (vip ?? 0);
}

function formatQuota(megabytes: number) {
  return megabytes >= 1024 ? `${(megabytes / 1024).toFixed(1)} GB` : `${megabytes.toFixed(0)} MB`;
}

const statusLabel = { pending: "等待中", running: "下载中", completed: "已完成", failed: "失败", cancelled: "已取消" };
