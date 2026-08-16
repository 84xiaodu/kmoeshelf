import { useState, type FormEvent } from "react";
import { api, messageOf, setCsrfToken } from "../api";
import { Alert } from "../ui";
import { AuthFrame } from "./Setup";

export default function Login({ onComplete }: { onComplete: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = await api.login(password);
      setCsrfToken(result.csrf_token); onComplete();
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  }
  return <AuthFrame eyebrow="欢迎回来" title="打开你的漫画书架" copy="登录后查看订阅、追新检查和下载进度。">
    <form onSubmit={submit} className="auth-form">
      {error && <Alert>{error}</Alert>}
      <label>管理员密码<input autoFocus required minLength={12} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      <button className="button button-primary button-block" disabled={busy}>{busy ? "正在验证…" : "登录"}</button>
    </form>
  </AuthFrame>;
}
