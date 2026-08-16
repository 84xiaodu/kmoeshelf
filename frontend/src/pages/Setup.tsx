import { useState, type FormEvent } from "react";
import { api, messageOf, setCsrfToken } from "../api";
import { Alert } from "../ui";

export default function Setup({ onComplete }: { onComplete: () => void }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) return setError("两次输入的密码不一致");
    setBusy(true); setError("");
    try {
      const result = await api.setup(password);
      setCsrfToken(result.csrf_token);
      onComplete();
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  }

  return <AuthFrame eyebrow="首次启动" title="创建管理员" copy="这个账号只保护本地管理界面。Kmoe 登录将在下一步单独配置。">
    <form onSubmit={submit} className="auth-form">
      {error && <Alert>{error}</Alert>}
      <label>管理员密码<input autoFocus required minLength={12} type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /><small>至少 12 个字符</small></label>
      <label>确认密码<input required minLength={12} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></label>
      <button className="button button-primary button-block" disabled={busy}>{busy ? "正在创建…" : "创建并进入书架"}</button>
    </form>
  </AuthFrame>;
}

export function AuthFrame({ eyebrow, title, copy, children }: { eyebrow: string; title: string; copy: string; children: React.ReactNode }) {
  return <main className="auth-page">
    <section className="auth-hero">
      <div className="brand"><span className="brand-seal">K</span><span>Kmoe 书架</span></div>
      <div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="lede">{copy}</p></div>
      <p className="auth-footnote">私有部署 · 自动追新 · 安全下载</p>
    </section>
    <section className="auth-panel">{children}</section>
  </main>;
}
