import { useEffect, useState, type FormEvent } from "react";
import { api, messageOf } from "../api";
import type { AppSettings, KmoeStatus } from "../types";
import { Alert, Spinner } from "../ui";

const mirrors = ["mox.moe", "kxo.moe", "kxx.moe", "kzz.moe", "koz.moe"];

export default function Settings({ status, onStatus }: { status: KmoeStatus | null; onStatus: (status: KmoeStatus) => void }) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [email, setEmail] = useState(status?.email ?? "");
  const [password, setPassword] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => { api.settings().then(setSettings).catch((reason) => setError(messageOf(reason))); }, []);
  async function run(action: () => Promise<void>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); setNotice(success); }
    catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  }
  function connect(event: FormEvent) {
    event.preventDefault();
    void run(async () => { const next = await api.kmoeLogin(email, password); onStatus(next); setPassword(""); }, "Kmoe 账号已连接，会话已加密保存");
  }
  function save(event: FormEvent) {
    event.preventDefault(); if (!settings) return;
    void run(async () => { setSettings(await api.updateSettings(settings)); }, "运行设置已保存。下载并发数将在服务重启后完全生效");
  }
  function changePassword(event: FormEvent) {
    event.preventDefault();
    if (newPassword !== confirmPassword) { setError("两次输入的新密码不一致"); return; }
    void run(async () => { await api.changePassword(currentPassword, newPassword); setCurrentPassword(""); setNewPassword(""); setConfirmPassword(""); }, "管理员密码已更新，其他会话已退出");
  }
  return <section className="page">
    <header className="page-head"><div><p className="eyebrow">系统配置</p><h1>设置</h1><p>账号密码不会写入日志或以明文保存。</p></div></header>
    {error && <Alert>{error}</Alert>}{notice && <Alert tone="success">{notice}</Alert>}
    <div className="settings-grid">
      <article className="panel settings-card"><div className="settings-heading"><div><p className="eyebrow">远端账号</p><h2>Kmoe 登录</h2></div><span className={`pill ${status?.connected ? "pill-green" : ""}`}>{status?.connected ? "已连接" : "未连接"}</span></div>{status?.connected && <p className="account-summary"><strong>{status.email}</strong><span>当前镜像 {status.mirror}</span></p>}<form className="stack-form" onSubmit={connect}><label>邮箱<input required type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} /></label><label>{status?.connected ? "重新登录密码" : "密码"}<input required type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label><button className="button button-primary" disabled={busy}>{status?.connected ? "重新登录" : "连接 Kmoe"}</button></form></article>
      <article className="panel settings-card"><p className="eyebrow">自动化</p><h2>检查与下载</h2>{!settings ? <Spinner /> : <form className="stack-form" onSubmit={save}><div className="form-row"><label>检查间隔（小时）<input type="number" min="1" max="720" value={settings.check_interval_hours} onChange={(e) => setSettings({ ...settings, check_interval_hours: Number(e.target.value) })} /></label><label>下载并发数<input type="number" min="1" max="8" value={settings.download_concurrency} onChange={(e) => setSettings({ ...settings, download_concurrency: Number(e.target.value) })} /></label></div><div className="form-row"><label>失败重试次数<input type="number" min="0" max="10" value={settings.max_download_retries} onChange={(e) => setSettings({ ...settings, max_download_retries: Number(e.target.value) })} /></label><label>首选镜像<select value={settings.preferred_mirror} onChange={(e) => setSettings({ ...settings, preferred_mirror: e.target.value })}>{mirrors.map((mirror) => <option key={mirror}>{mirror}</option>)}</select></label></div><small>首选镜像在下次 Kmoe 登录时使用；当前有效会话保持原镜像。</small><button className="button button-primary" disabled={busy}>保存运行设置</button></form>}</article>
      <article className="panel settings-card"><p className="eyebrow">本地安全</p><h2>管理员密码</h2><form className="stack-form" onSubmit={changePassword}><label>当前密码<input required minLength={12} type="password" autoComplete="current-password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} /></label><label>新密码<input required minLength={12} type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} /></label><label>确认新密码<input required minLength={12} type="password" autoComplete="new-password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} /></label><button className="button button-quiet" disabled={busy}>更新管理员密码</button></form></article>
    </div>
  </section>;
}
