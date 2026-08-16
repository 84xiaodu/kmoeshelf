import { useState, type FormEvent } from "react";
import { api, messageOf } from "../api";
import type { ComicDetails, ContentType, DownloadFormat, SearchPage } from "../types";
import { Alert, EmptyState, Spinner } from "../ui";

const typeLabels: Record<ContentType, string> = { volume: "单行本", extra: "番外", serial: "连载话" };

export default function Search({ connected }: { connected: boolean }) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchPage | null>(null);
  const [details, setDetails] = useState<ComicDetails | null>(null);
  const [types, setTypes] = useState<ContentType[]>(["volume"]);
  const [format, setFormat] = useState<DownloadFormat>("epub");
  const [strategy, setStrategy] = useState<"backfill" | "future_only">("future_only");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function search(event?: FormEvent, page = 1) {
    event?.preventDefault(); if (!query.trim()) return;
    setBusy(true); setError(""); setDetails(null);
    try { setResult(await api.search(query.trim(), page)); }
    catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  }
  async function open(id: string) {
    setBusy(true); setError("");
    try { setDetails(await api.comic(id)); }
    catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  }
  async function subscribe() {
    if (!details || !types.length) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await api.createSubscription({ remote_id: details.remote_id, content_types: types, download_format: format, initialization_strategy: strategy });
      setNotice(`已订阅《${details.title}》`);
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  }
  function toggle(type: ContentType) { setTypes((current) => current.includes(type) ? current.filter((value) => value !== type) : [...current, type]); }
  if (!connected) return <section className="page"><header className="page-head"><div><p className="eyebrow">发现漫画</p><h1>搜索 Kmoe 书库</h1></div></header><Alert tone="info">请先在 <a href="#/settings">设置</a> 中登录 Kmoe 账号。</Alert></section>;
  return <section className="page">
    <header className="page-head"><div><p className="eyebrow">发现漫画</p><h1>搜索 Kmoe 书库</h1><p>按标题或作者查找，然后选择追踪范围。</p></div></header>
    <form className="search-bar" onSubmit={(event) => void search(event)}><label className="sr-only" htmlFor="comic-query">漫画关键词</label><input id="comic-query" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="输入漫画标题或作者…" /><button className="button button-primary" disabled={busy}>搜索</button></form>
    {error && <Alert>{error}</Alert>}{notice && <Alert tone="success">{notice}。<a href="#/subscriptions">查看订阅</a></Alert>}{busy && <Spinner />}
    {details ? <ComicDetail details={details} types={types} setType={toggle} format={format} setFormat={setFormat} strategy={strategy} setStrategy={setStrategy} subscribe={subscribe} busy={busy} close={() => setDetails(null)} /> : result && <>
      <p className="result-count">第 {result.current_page} / {result.total_pages} 页 · {result.results.length} 条结果</p>
      {!result.results.length ? <EmptyState title="没有找到漫画">换一个关键词再试试。</EmptyState> : <div className="comic-grid">{result.results.map((comic) => <button className="comic-card" key={comic.remote_id} onClick={() => void open(comic.remote_id)}><Cover src={comic.cover_url} title={comic.title} /><span><strong>{comic.title}</strong><small>{comic.author ?? "作者未知"} · {comic.language ?? "语言未知"}</small><em>#{comic.remote_id}</em></span></button>)}</div>}
      <div className="pager"><button className="button button-quiet" disabled={result.current_page <= 1} onClick={() => void search(undefined, result.current_page - 1)}>上一页</button><button className="button button-quiet" disabled={result.current_page >= result.total_pages} onClick={() => void search(undefined, result.current_page + 1)}>下一页</button></div>
    </>}
  </section>;
}

function ComicDetail({ details, types, setType, format, setFormat, strategy, setStrategy, subscribe, busy, close }: { details: ComicDetails; types: ContentType[]; setType: (type: ContentType) => void; format: DownloadFormat; setFormat: (format: DownloadFormat) => void; strategy: "backfill" | "future_only"; setStrategy: (value: "backfill" | "future_only") => void; subscribe: () => void; busy: boolean; close: () => void }) {
  const groups = Object.entries(typeLabels).map(([type, label]) => ({ type: type as ContentType, label, items: details.items.filter((item) => item.content_type === type) }));
  return <div className="detail-view"><button className="text-button back" onClick={close}>← 返回搜索结果</button><div className="detail-hero"><Cover src={details.cover_url} title={details.title} /><div><p className="eyebrow">漫画 #{details.remote_id}</p><h2>{details.title}</h2><p>{details.author ?? "作者未知"} · {details.language ?? "语言未知"}</p><p className="description">{details.description || "暂无简介"}</p></div></div>
    <div className="detail-columns"><div><h3>远端内容</h3>{groups.map((group) => <section className="item-group" key={group.type}><div><strong>{group.label}</strong><span>{group.items.length} 项</span></div>{group.items.slice(0, 5).map((item) => <p key={item.remote_id}>{item.name}<small>{item.page_count ? `${item.page_count} 页` : "页数未知"}</small></p>)}{group.items.length > 5 && <small>另有 {group.items.length - 5} 项</small>}</section>)}</div>
      <aside className="subscribe-box"><h3>订阅设置</h3><fieldset><legend>追踪内容</legend>{(Object.keys(typeLabels) as ContentType[]).map((type) => <label className="check" key={type}><input type="checkbox" checked={types.includes(type)} onChange={() => setType(type)} />{typeLabels[type]}</label>)}</fieldset><fieldset><legend>下载格式</legend><div className="segmented"><button className={format === "epub" ? "selected" : ""} onClick={() => setFormat("epub")}>EPUB</button><button className={format === "mobi" ? "selected" : ""} onClick={() => setFormat("mobi")}>MOBI</button></div></fieldset><fieldset><legend>首次订阅</legend><label className="radio"><input type="radio" checked={strategy === "future_only"} onChange={() => setStrategy("future_only")} /><span><strong>仅追新</strong><small>保存当前基线，不下载已有内容</small></span></label><label className="radio"><input type="radio" checked={strategy === "backfill"} onChange={() => setStrategy("backfill")} /><span><strong>补齐已有内容</strong><small>立即创建符合范围的下载任务</small></span></label></fieldset><button className="button button-primary button-block" disabled={busy || !types.length} onClick={() => void subscribe()}>创建订阅</button></aside>
    </div></div>;
}

function Cover({ src, title }: { src: string | null; title: string }) { return src ? <img className="cover" src={src} alt={`${title} 封面`} loading="lazy" referrerPolicy="no-referrer" /> : <div className="cover cover-fallback" aria-label={`${title} 无封面`}>{title.slice(0, 1)}</div>; }
