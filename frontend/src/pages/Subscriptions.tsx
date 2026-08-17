import { useEffect, useState } from "react";
import { api, messageOf } from "../api";
import type { ContentType, DownloadFormat, InitializationStrategy, PolicyImpact, Subscription } from "../types";
import { Alert, EmptyState, formatDate, Spinner } from "../ui";

const labels: Record<ContentType, string> = { volume: "单行本", extra: "番外", serial: "连载话" };

export default function Subscriptions() {
  const [items, setItems] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function load() {
    try { setItems(await api.subscriptions()); }
    catch (reason) { setError(messageOf(reason)); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  async function act(action: () => Promise<unknown>, success: string): Promise<boolean> {
    setError(""); setNotice("");
    try { const result = await action(); if (result === false) return false; setNotice(success); await load(); return true; }
    catch (reason) { setError(messageOf(reason)); return false; }
  }
  async function remove(item: Subscription) {
    const cancelPending = confirm(`删除《${item.title}》的订阅？\n\n选择“确定”将同时取消尚未开始的下载任务，已完成文件不会删除。`);
    if (!cancelPending) return;
    await act(() => api.deleteSubscription(item.id, true), "订阅已删除，等待任务已取消");
  }
  return <section className="page">
    <header className="page-head"><div><p className="eyebrow">追新管理</p><h1>我的订阅</h1><p>每部漫画独立设置内容范围与下载格式。</p></div><a className="button button-primary" href="#/search">＋ 添加订阅</a></header>
    {error && <Alert>{error}</Alert>}{notice && <Alert tone="success">{notice}</Alert>}
    {loading ? <Spinner /> : !items.length ? <EmptyState title="书架还是空的">从发现漫画页搜索并创建第一个订阅。</EmptyState> : <div className="subscription-list">{items.map((item) => <SubscriptionCard key={item.id} item={item} act={act} remove={remove} />)}</div>}
  </section>;
}

function impactSummary(impact: PolicyImpact) {
  return `新增 ${impact.created}，转换 ${impact.converted}，复用 ${impact.reused}，取消 ${impact.cancelled}；运行中保留 ${impact.retained_running}，已完成保留 ${impact.retained_completed}`;
}

function SubscriptionCard({ item, act, remove }: { item: Subscription; act: (action: () => Promise<unknown>, success: string) => Promise<boolean>; remove: (item: Subscription) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [types, setTypes] = useState<ContentType[]>(item.content_types);
  const [format, setFormat] = useState<DownloadFormat>(item.download_format);
  const [strategy, setStrategy] = useState<InitializationStrategy>(item.initialization_strategy);
  function toggle(type: ContentType) { setTypes((current) => current.includes(type) ? current.filter((value) => value !== type) : [...current, type]); }
  async function savePolicy() {
    const body = { content_types: types, download_format: format, initialization_strategy: strategy };
    const saved = await act(async () => {
      const impact = await api.previewSubscriptionPolicy(item.id, body);
      if (!confirm(`应用这项下载策略？\n\n${impactSummary(impact)}\n\n运行中和已完成的任务不会被改写。`)) return false;
      await api.editSubscription(item.id, body);
      return true;
    }, "订阅策略已保存，相关等待任务已自动协调");
    if (saved) setEditing(false);
  }
  return <article className={`subscription-card ${item.enabled ? "" : "is-paused"}`}>
    <div className="subscription-main">
      {item.cover_url ? <img className="subscription-cover" src={item.cover_url} alt="" referrerPolicy="no-referrer" /> : <div className="subscription-cover cover-fallback">{item.title.slice(0, 1)}</div>}
      <div className="subscription-info"><div className="title-line"><span className={`pill ${item.enabled ? "pill-green" : ""}`}>{item.enabled ? "追新中" : "已暂停"}</span><small>#{item.remote_id}</small></div><h2>{item.title}</h2><p>{item.author ?? "作者未知"}</p><div className="tag-row">{item.content_types.map((type) => <span key={type}>{labels[type]}</span>)}<span>{item.download_format.toUpperCase()}</span><span>{item.initialization_strategy === "backfill" ? "补齐已有" : "仅追新"}</span></div></div>
      <div className="subscription-dates"><span><small>上次成功</small>{formatDate(item.last_success_at)}</span><span><small>下次检查</small>{formatDate(item.next_check_at)}</span></div>
    </div>
    {item.last_error_message && <Alert>{item.last_error_message} <code>{item.last_error_code}</code></Alert>}
    {editing && <div className="inline-editor"><fieldset><legend>追踪内容</legend>{(Object.keys(labels) as ContentType[]).map((type) => <label className="check" key={type}><input type="checkbox" checked={types.includes(type)} onChange={() => toggle(type)} />{labels[type]}</label>)}</fieldset><label>下载格式<select value={format} onChange={(e) => setFormat(e.target.value as DownloadFormat)}><option value="epub">EPUB</option><option value="mobi">MOBI</option></select></label><label>下载策略<select value={strategy} onChange={(e) => setStrategy(e.target.value as InitializationStrategy)}><option value="future_only">仅下载今后新增</option><option value="backfill">补齐所有已有内容</option></select></label><button className="button button-primary" disabled={!types.length} onClick={() => void savePolicy()}>预览并保存</button></div>}
    <footer className="card-actions"><button className="text-button" onClick={() => void act(() => api.checkOne(item.id), `已安排《${item.title}》检查`)}>立即检查</button><button className="text-button" onClick={() => { setTypes(item.content_types); setFormat(item.download_format); setStrategy(item.initialization_strategy); setEditing((value) => !value); }}>{editing ? "取消编辑" : "编辑"}</button><button className="text-button" onClick={() => void act(() => api.setSubscriptionEnabled(item.id, !item.enabled), item.enabled ? "订阅已暂停" : "订阅已恢复")}>{item.enabled ? "暂停" : "恢复"}</button><button className="text-button danger" onClick={() => void remove(item)}>删除</button></footer>
  </article>;
}
