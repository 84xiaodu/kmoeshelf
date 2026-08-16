import { expect, test, type Route } from "@playwright/test";

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

test("管理员可完成初始化、Kmoe 登录、搜索和订阅", async ({ page }) => {
  let setupRequired = true;
  let connected = false;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/auth/status") return json(route, { setup_required: setupRequired, authenticated: !setupRequired });
    if (path === "/api/auth/setup") { setupRequired = false; return json(route, { authenticated: true, csrf_token: "test-csrf" }, 201); }
    if (path === "/api/auth/me") return json(route, { authenticated: true, csrf_token: "test-csrf" });
    if (path === "/api/kmoe/status") return json(route, { connected, email: connected ? "reader@example.com" : null, mirror: connected ? "mox.moe" : null, status: connected ? "active" : null });
    if (path === "/api/kmoe/login") { connected = true; return json(route, { connected: true, email: "reader@example.com", mirror: "mox.moe", status: "active" }); }
    if (path === "/api/subscriptions" && request.method() === "GET") return json(route, []);
    if (path === "/api/subscriptions" && request.method() === "POST") return json(route, { id: 1, comic_id: 1, remote_id: "50076", title: "星海书简", author: "林墨", cover_url: null, enabled: true, content_types: ["volume"], download_format: "epub", initialization_strategy: "future_only", last_attempt_at: null, last_success_at: null, next_check_at: null, last_error_code: null, last_error_message: null }, 201);
    if (path === "/api/downloads") return json(route, []);
    if (path === "/api/settings" && request.method() === "GET") return json(route, { check_interval_hours: 6, download_concurrency: 2, max_download_retries: 3, preferred_mirror: "mox.moe" });
    if (path === "/api/kmoe/search") return json(route, { query: "星海", current_page: 1, total_pages: 1, results: [{ remote_id: "50076", title: "星海书简", author: "林墨", language: "zh", detail_path: "/c/50076.htm", cover_url: null }] });
    if (path === "/api/kmoe/comics/50076") return json(route, { remote_id: "50076", title: "星海书简", author: "林墨", language: "zh", detail_path: "/c/50076.htm", cover_url: null, description: "一段穿越星海的旅程。", items: [{ remote_id: "v1", content_type: "volume", name: "第一卷", sort_order: 1, page_count: 180, mobi_size_mb: "32", epub_size_mb: "18" }] });
    return json(route, { detail: `Unhandled ${request.method()} ${path}` }, 500);
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "创建管理员" })).toBeVisible();
  await page.getByLabel("管理员密码").fill("correct horse battery staple");
  await page.getByLabel("确认密码").fill("correct horse battery staple");
  await page.getByRole("button", { name: "创建并进入书架" }).click();
  await expect(page.getByRole("heading", { name: "今天也在自动追新" })).toBeVisible();

  await page.getByRole("link", { name: "设置" }).click();
  await page.getByLabel("邮箱").fill("reader@example.com");
  await page.getByLabel("密码", { exact: true }).fill("not-persisted");
  await page.getByRole("button", { name: "连接 Kmoe" }).click();
  await expect(page.getByText("Kmoe 账号已连接")).toBeVisible();

  await page.getByRole("link", { name: "发现漫画" }).click();
  await page.getByLabel("漫画关键词").fill("星海");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await page.getByRole("button", { name: /星海书简/ }).click();
  await expect(page.getByRole("heading", { name: "星海书简" })).toBeVisible();
  await page.getByRole("button", { name: "创建订阅" }).click();
  await expect(page.getByText("已订阅《星海书简》")).toBeVisible();
});
