import { useEffect, useState, type FormEvent } from "react";
import { api, messageOf } from "../api";
import type { BangumiCollectionType, SubscriptionSource, SubscriptionSourceItem } from "../types";
import { Alert, EmptyState, formatDate, Spinner } from "../ui";

const SEARCH_HANDOFF_KEY = "kmoeshelf.discovery.query";
const collectionLabels: Record<BangumiCollectionType, string> = {
  wish: "想看", collect: "看过", doing: "在看", on_hold: "搁置", dropped: "抛弃",
};

export default function Sources({ connected }: { connected: boolean }) {
  const [sources, setSources] = useState<SubscriptionSource[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [items, setItems] = useState<SubscriptionSourceItem[]>([]);
  const [name, setName] = useState("我的 Bangumi");
  const [username, setUsername] = useState("");
  const [types, setTypes] = useState<BangumiCollectionType[]>(["wish", "doing"]);
  const [interval, setInterval] = useState(24);
  const [intervalDraft, setIntervalDraft] = useState(24);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function loadSources(preferred?: number) {
    const next = await api.sources();
    setSources(next);
    const target = preferred ?? selected ?? next[0]?.id ?? null;
    setSelected(target);
    const source = next.find((item) => item.id === target) ?? null;
    setIntervalDraft(source?.sync_interval_hours ?? 24);
    setItems(target ? await api.sourceItems(target) : []);
  }
  useEffect(() => {
    loadSources().catch((reason) => setError(messageOf(reason))).finally(() => setLoading(false));
  }, []);

  async function choose(id: number) {
    setSelected(id); setError("");
    const source = sources.find((item) => item.id === id) ?? null;
    setIntervalDraft(source?.sync_interval_hours ?? 24);
    try { setItems(await api.sourceItems(id)); }
    catch (reason) { setError(messageOf(reason)); }
  }
  function toggle(type: BangumiCollectionType) {
    setTypes((current) => current.includes(type) ? current.filter((value) => value !== type) : [...current, type]);
  }
  async function create(event: FormEvent) {
    event.preventDefault(); if (!types.length) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const source = await api.createSource({ name, username, collection_types: types, enabled: true, sync_interval_hours: interval });
      const result = await api.syncSource(source.id);
      await loadSources(source.id);
      setNotice(`已读取 ${result.imported_count} 个 Bangumi 收藏条目`);
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  }
  async function sync() {
    if (!selected) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api.syncSource(selected);
      await loadSources(selected);
      setNotice(`已同步 ${result.imported_count} 个条目`);
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  }
  async function saveInterval() {
    const source = sources.find((item) => item.id === selected);
    if (!source) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await api.editSource(source.id, {
        name: source.name,
        username: source.username,
        collection_types: source.collection_types,
        enabled: source.enabled,
        sync_interval_hours: intervalDraft,
      });
      await loadSources(source.id);
      setNotice("同步周期已更新");
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!selected || !confirm("删除这个订阅源及其本地来源快照？现有 Kmoe 订阅不会删除。")) return;
    setBusy(true); setError(""); setNotice("");
    try { await api.deleteSource(selected); setSelected(null); await loadSources(); setNotice("订阅源已删除"); }
    catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  }
  function searchKmoe(query: string) {
    sessionStorage.setItem(SEARCH_HANDOFF_KEY, query);
    location.hash = "#/search";
  }

  const active = sources.find((source) => source.id === selected) ?? null;
  return <section className="page sources-page">
    <header className="page-head"><div><p className="eyebrow">外部收藏同步</p><h1>订阅源</h1><p>读取 Bangumi 的想看、在看等书籍收藏，确认匹配后再创建 Kmoe 订阅。</p></div></header>
    {error && <Alert>{error}</Alert>}{notice && <Alert tone="success">{notice}</Alert>}
    <Alert tone="info">公开收藏只需要 Bangumi 用户名；私密收藏需在服务端配置 <code>KMOE_BANGUMI_ACCESS_TOKEN</code>。为避免误订阅，系统不会把模糊匹配结果自动加入 Kmoe。</Alert>
    <div className="sources-layout">
      <aside className="panel source-sidebar">
        <h2>来源列表</h2>
        {loading ? <Spinner /> : !sources.length ? <EmptyState title="还没有订阅源">在下方添加一个 Bangumi 用户。</EmptyState> : <div className="source-list">{sources.map((source) => <button key={source.id} className={source.id === selected ? "active" : ""} onClick={() => void choose(source.id)}><strong>{source.name}</strong><span>@{source.username} · {source.item_count} 项 · 每 {source.sync_interval_hours} 小时</span></button>)}</div>}
        <form className="source-form" onSubmit={(event) => void create(event)}>
          <h3>添加 Bangumi 来源</h3>
          <label>显示名称<input required maxLength={128} value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label>Bangumi 用户名<input required pattern="[A-Za-z0-9_-]+" maxLength={64} placeholder="例如 sai" value={username} onChange={(event) => setUsername(event.target.value)} /></label>
          <fieldset><legend>读取状态</legend>{(Object.keys(collectionLabels) as BangumiCollectionType[]).map((type) => <label className="check" key={type}><input type="checkbox" checked={types.includes(type)} onChange={() => toggle(type)} />{collectionLabels[type]}</label>)}</fieldset>
          <label>同步周期（小时）<input type="number" min="1" max="720" value={interval} onChange={(event) => setInterval(Number(event.target.value))} /></label>
          <button className="button button-primary" disabled={busy || !types.length}>添加并同步</button>
        </form>
      </aside>
      <div className="source-content">
        {active && <div className="panel-head source-toolbar"><div><h2>{active.name}</h2><p>@{active.username} · 最近同步 {formatDate(active.last_success_at)}</p></div><div><label className="inline-number">周期（小时）<input type="number" min="1" max="720" value={intervalDraft} onChange={(event) => setIntervalDraft(Number(event.target.value))} /></label><button className="button button-quiet" disabled={busy || intervalDraft === active.sync_interval_hours} onClick={() => void saveInterval()}>保存周期</button><button className="button button-quiet" disabled={busy} onClick={() => void sync()}>立即同步</button><button className="text-button danger" disabled={busy} onClick={() => void remove()}>删除</button></div></div>}
        {!active ? <EmptyState title="请选择或添加订阅源">Bangumi 收藏条目会显示在这里。</EmptyState> : !items.length ? <EmptyState title="这个来源还没有条目">检查用户收藏可见性和所选状态，然后重新同步。</EmptyState> : <div className="source-item-grid">{items.map((item) => <article className="source-item" key={item.id}>{item.cover_url ? <img className="cover" src={item.cover_url} alt={`${item.title} 封面`} loading="lazy" referrerPolicy="no-referrer" /> : <div className="cover cover-fallback">{item.title.slice(0, 1)}</div>}<div><span className="pill">{collectionLabels[item.source_status]}</span><h3>{item.title}</h3>{item.original_title && item.original_title !== item.title && <small>{item.original_title}</small>}<div className="source-item-actions"><button className="button button-primary" disabled={!connected} onClick={() => searchKmoe(item.search_query)}>在 Kmoe 搜索</button><a className="text-button" href={item.external_url} target="_blank" rel="noreferrer">Bangumi ↗</a></div></div></article>)}</div>}
      </div>
    </div>
  </section>;
}
