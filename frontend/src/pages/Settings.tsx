import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, messageOf } from "../api";
import type { AppSettings, DirectoryListing, KmoeStatus, StorageMigration, StoragePreview, StorageStatus } from "../types";
import { Alert, formatBytes, Spinner } from "../ui";

const mirrors = ["mox.moe", "kxo.moe", "kxx.moe", "kzz.moe", "koz.moe"];
const activeMigrationPhases = new Set(["pending", "waiting_for_downloads", "copying", "committing", "cleaning"]);
const phaseLabels: Record<StorageMigration["phase"], string> = {
  pending: "准备中", waiting_for_downloads: "等待当前下载结束", copying: "正在复制文件",
  committing: "正在切换目录", cleaning: "正在清理原目录", completed: "已完成", failed: "迁移失败",
};

function joinPath(parent: string, child: string) { return parent ? `${parent}/${child}` : child; }

export default function Settings({ status, onStatus }: { status: KmoeStatus | null; onStatus: (status: KmoeStatus) => void }) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [storage, setStorage] = useState<StorageStatus | null>(null);
  const [listing, setListing] = useState<DirectoryListing | null>(null);
  const [browsePath, setBrowsePath] = useState("");
  const [targetPath, setTargetPath] = useState("");
  const [newFolder, setNewFolder] = useState("");
  const [preview, setPreview] = useState<StoragePreview | null>(null);
  const [email, setEmail] = useState(status?.email ?? "");
  const [password, setPassword] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refreshStorage = useCallback(async () => {
    const next = await api.storageStatus();
    setStorage(next);
    setTargetPath((current) => current || next.active_subpath);
  }, []);
  const browse = useCallback(async (path: string) => {
    const next = await api.storageDirectories(path);
    setBrowsePath(next.path); setListing(next);
  }, []);

  useEffect(() => {
    Promise.all([api.settings().then(setSettings), refreshStorage(), browse("")]).catch((reason) => setError(messageOf(reason)));
  }, [browse, refreshStorage]);
  useEffect(() => {
    if (!storage?.migration || !activeMigrationPhases.has(storage.migration.phase)) return;
    const timer = window.setInterval(() => { refreshStorage().catch((reason) => setError(messageOf(reason))); }, 1000);
    return () => window.clearInterval(timer);
  }, [refreshStorage, storage?.migration?.id, storage?.migration?.phase]);

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
    void run(async () => { setSettings(await api.updateSettings(settings)); }, "运行设置已保存，下载并发数已生效");
  }
  function changePassword(event: FormEvent) {
    event.preventDefault();
    if (newPassword !== confirmPassword) { setError("两次输入的新密码不一致"); return; }
    void run(async () => { await api.changePassword(currentPassword, newPassword); setCurrentPassword(""); setNewPassword(""); setConfirmPassword(""); }, "管理员密码已更新，其他会话已退出");
  }
  function inspectStorage() {
    void run(async () => { setPreview(await api.previewStorageMigration(targetPath)); }, "已完成迁移预检，请确认文件数量与容量");
  }
  function startMigration() {
    if (!preview) return;
    const destination = preview.target_subpath || "挂载根目录";
    if (!confirm(`将 ${preview.total_files} 个文件（${formatBytes(preview.total_bytes)}）自动搬迁到“${destination}”？\n\n迁移期间不会启动新的下载，完成后会自动切换保存目录。`)) return;
    void run(async () => { const migration = await api.startStorageMigration(preview.target_subpath); setStorage((current) => current ? { ...current, migration } : current); setPreview(null); }, "目录迁移已开始，可留在此页查看进度");
  }
  function createFolder() {
    const name = newFolder.trim(); if (!name) return;
    void run(async () => { await api.createStorageDirectory(joinPath(browsePath, name)); setNewFolder(""); await browse(browsePath); }, "文件夹已创建");
  }
  function retryMigration() {
    if (!storage?.migration) return;
    void run(async () => { const migration = await api.retryStorageMigration(storage.migration!.id); setStorage((current) => current ? { ...current, migration } : current); }, "已重新开始迁移");
  }

  const migration = storage?.migration;
  const migrationPercent = migration?.total_bytes ? Math.min(100, Math.round(migration.processed_bytes / migration.total_bytes * 100)) : 0;
  const parentPath = browsePath.split("/").slice(0, -1).join("/");
  return <section className="page">
    <header className="page-head"><div><p className="eyebrow">系统配置</p><h1>设置</h1><p>账号密码不会写入日志或以明文保存。</p></div></header>
    {error && <Alert>{error}</Alert>}{notice && <Alert tone="success">{notice}</Alert>}
    <div className="settings-grid">
      <article className="panel settings-card"><div className="settings-heading"><div><p className="eyebrow">远端账号</p><h2>Kmoe 登录</h2></div><span className={`pill ${status?.connected ? "pill-green" : ""}`}>{status?.connected ? "已连接" : "未连接"}</span></div>{status?.connected && <p className="account-summary"><strong>{status.email}</strong><span>当前镜像 {status.mirror}</span></p>}<form className="stack-form" onSubmit={connect}><label>邮箱<input required type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} /></label><label>{status?.connected ? "重新登录密码" : "密码"}<input required type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label><button className="button button-primary" disabled={busy}>{status?.connected ? "重新登录" : "连接 Kmoe"}</button></form></article>
      <article className="panel settings-card"><p className="eyebrow">自动化</p><h2>检查与下载</h2>{!settings ? <Spinner /> : <form className="stack-form" onSubmit={save}><div className="form-row"><label>检查间隔（小时）<input type="number" min="1" max="720" value={settings.check_interval_hours} onChange={(e) => setSettings({ ...settings, check_interval_hours: Number(e.target.value) })} /></label><label>下载并发数<input type="number" min="1" max="8" value={settings.download_concurrency} onChange={(e) => setSettings({ ...settings, download_concurrency: Number(e.target.value) })} /></label></div><div className="form-row"><label>失败重试次数<input type="number" min="0" max="10" value={settings.max_download_retries} onChange={(e) => setSettings({ ...settings, max_download_retries: Number(e.target.value) })} /></label><label>首选镜像<select value={settings.preferred_mirror} onChange={(e) => setSettings({ ...settings, preferred_mirror: e.target.value })}>{mirrors.map((mirror) => <option key={mirror}>{mirror}</option>)}</select></label></div><small>首选镜像在下次 Kmoe 登录时使用；当前有效会话保持原镜像。</small><button className="button button-primary" disabled={busy}>保存运行设置</button></form>}</article>
      <article className="panel settings-card storage-card"><div className="settings-heading"><div><p className="eyebrow">本地存储</p><h2>下载根目录</h2></div>{storage && <span className={`pill ${storage.writable ? "pill-green" : ""}`}>{storage.writable ? "可写" : "不可写"}</span>}</div>
        {!storage ? <Spinner /> : <><div className="storage-summary"><span><small>宿主机挂载点（容器内）</small><code>{storage.mounted_root}</code></span><span><small>当前保存位置</small><code>{storage.active_subpath || "/"}</code></span><span><small>实际路径</small><code>{storage.effective_path}</code></span></div>
        <p className="storage-note">只能选择宿主机挂载目录下的相对路径；切换时会自动搬迁由本服务管理的已完成文件。</p>
        <div className="storage-browser"><div className="browser-head"><strong>目录浏览：/{browsePath}</strong><button className="text-button" disabled={!browsePath} onClick={() => void browse(parentPath)}>返回上级</button></div><div className="directory-list">{listing?.directories.length ? listing.directories.map((directory) => <button key={directory} onClick={() => void browse(joinPath(browsePath, directory))}>▰ {directory}</button>) : <small>当前目录没有子文件夹</small>}</div><div className="browser-create"><input aria-label="新文件夹名称" placeholder="新文件夹名称" value={newFolder} onChange={(e) => setNewFolder(e.target.value)} /><button className="button button-quiet" disabled={busy || !newFolder.trim()} onClick={createFolder}>新建</button><button className="button button-quiet" onClick={() => { setTargetPath(browsePath); setPreview(null); }}>选择当前目录</button></div></div>
        <div className="storage-target"><label>保存位置（相对挂载根目录）<input value={targetPath} placeholder="例如 manga/library" onChange={(e) => { setTargetPath(e.target.value); setPreview(null); }} /></label><button className="button button-quiet" disabled={busy || targetPath === storage.active_subpath || Boolean(migration && activeMigrationPhases.has(migration.phase))} onClick={inspectStorage}>预检</button></div>
        {preview && <Alert tone="info">将从 <code>/{preview.source_subpath}</code> 搬迁到 <code>/{preview.target_subpath}</code>，共 {preview.total_files} 个文件、{formatBytes(preview.total_bytes)}。 <button className="button button-primary" disabled={busy} onClick={startMigration}>确认并开始搬迁</button></Alert>}
        {migration && <div className={`migration-box ${migration.phase === "failed" ? "migration-failed" : ""}`}><div><strong>{phaseLabels[migration.phase]}</strong><span>{migration.processed_files} / {migration.total_files} 个文件 · {formatBytes(migration.processed_bytes)} / {formatBytes(migration.total_bytes)}</span></div>{activeMigrationPhases.has(migration.phase) && <progress max="100" value={migrationPercent} />}{migration.current_relative_path && <small>正在处理：{migration.current_relative_path}</small>}{migration.error_message && <Alert>{migration.error_message} <code>{migration.error_code}</code></Alert>}{migration.phase === "failed" && <button className="button button-primary" disabled={busy} onClick={retryMigration}>重试迁移</button>}</div>}</>}</article>
      <article className="panel settings-card"><p className="eyebrow">本地安全</p><h2>管理员密码</h2><form className="stack-form" onSubmit={changePassword}><label>当前密码<input required minLength={12} type="password" autoComplete="current-password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} /></label><label>新密码<input required minLength={12} type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} /></label><label>确认新密码<input required minLength={12} type="password" autoComplete="new-password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} /></label><button className="button button-quiet" disabled={busy}>更新管理员密码</button></form></article>
    </div>
  </section>;
}
