import { useEffect, useState } from "react";
import { api, messageOf, setCsrfToken } from "./api";
import type { AuthStatus, KmoeStatus } from "./types";
import { Alert, Spinner } from "./ui";
import Setup from "./pages/Setup";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Search from "./pages/Search";
import Sources from "./pages/Sources";
import Subscriptions from "./pages/Subscriptions";
import Downloads from "./pages/Downloads";
import Settings from "./pages/Settings";

const pages = [
  ["dashboard", "概览", "⌂"], ["search", "搜索漫画", "⌕"],
  ["sources", "订阅源", "◎"], ["subscriptions", "我的订阅", "▤"], ["downloads", "下载任务", "⇣"], ["settings", "设置", "⚙"],
] as const;

function currentPage() {
  const page = location.hash.replace(/^#\/?/, "");
  return pages.some(([key]) => key === page) ? page : "dashboard";
}

export default function App() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [kmoe, setKmoe] = useState<KmoeStatus | null>(null);
  const [page, setPage] = useState(currentPage());
  const [fatal, setFatal] = useState("");

  async function boot() {
    try {
      const status = await api.authStatus(); setAuth(status);
      if (status.authenticated) {
        const session = await api.me(); setCsrfToken(session.csrf_token);
        setKmoe(await api.kmoeStatus());
      }
    } catch (reason) { setFatal(messageOf(reason)); }
  }
  useEffect(() => { void boot(); }, []);
  useEffect(() => {
    const change = () => setPage(currentPage());
    addEventListener("hashchange", change); return () => removeEventListener("hashchange", change);
  }, []);

  if (fatal) return <main className="fatal"><Alert>{fatal}</Alert><button className="button" onClick={() => location.reload()}>重新加载</button></main>;
  if (!auth) return <main className="splash"><span className="brand-seal">K</span><Spinner label="正在打开书架" /></main>;
  if (auth.setup_required) return <Setup onComplete={() => void boot()} />;
  if (!auth.authenticated) return <Login onComplete={() => void boot()} />;

  async function logout() {
    await api.logout(); setAuth({ setup_required: false, authenticated: false }); setKmoe(null);
  }
  const connected = Boolean(kmoe?.connected);
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-seal">K</span><span>Kmoe 书架</span></div>
      <nav aria-label="主导航">{pages.map(([key, label, icon]) => <a key={key} href={`#/${key}`} className={page === key ? "active" : ""}><span>{icon}</span>{label}</a>)}</nav>
      <div className="sidebar-foot">
        <div className={`connection ${connected ? "is-online" : ""}`}><i /> <span><strong>{connected ? "Kmoe 已连接" : "Kmoe 未连接"}</strong><small>{kmoe?.email ?? "请前往设置登录"}</small></span></div>
        <button className="text-button" onClick={() => void logout()}>退出管理</button>
      </div>
    </aside>
    <main className="main-content">
      <header className="mobile-header"><div className="brand"><span className="brand-seal">K</span><span>Kmoe 书架</span></div><select aria-label="页面" value={page} onChange={(e) => { location.hash = `#/${e.target.value}`; }}>{pages.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></header>
      {page === "dashboard" && <Dashboard kmoe={kmoe} />}
      {page === "search" && <Search connected={connected} />}
      {page === "sources" && <Sources connected={connected} />}
      {page === "subscriptions" && <Subscriptions />}
      {page === "downloads" && <Downloads />}
      {page === "settings" && <Settings status={kmoe} onStatus={setKmoe} />}
    </main>
  </div>;
}
