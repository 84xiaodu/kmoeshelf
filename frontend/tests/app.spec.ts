import { expect, test, type Route } from "@playwright/test";

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

test("仪表盘使用完整任务计数而不是有界任务列表计数", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/status") return json(route, { setup_required: false, authenticated: true });
    if (path === "/api/auth/me") return json(route, { authenticated: true, csrf_token: "test-csrf" });
    if (path === "/api/kmoe/status") return json(route, { connected: true, email: "reader@example.com", mirror: "mox.moe", status: "active" });
    if (path === "/api/subscriptions") return json(route, []);
    if (path === "/api/downloads") return json(route, {
      tasks: [],
      counts: { pending: 7, running: 3, completed: 1000, failed: 2, cancelled: 4 },
    });
    return json(route, { detail: `Unhandled ${path}` }, 500);
  });

  await page.goto("/");

  const downloading = page.locator(".stat-card").filter({ hasText: "正在下载" });
  await expect(downloading.locator("strong")).toHaveText("3");
  await expect(downloading.locator("small")).toHaveText("7 个等待中");
});

test("较慢的 REST 快照不会覆盖较新的下载事件", async ({ page }) => {
  const liveTask = {
    id: 8,
    comic_title: "实时更新漫画",
    item_name: "第二卷",
    content_type: "volume",
    download_format: "epub",
    status: "failed",
    attempt_count: 1,
    progress_bytes: 0,
    total_bytes: null,
    final_path: null,
    error_code: "network_error",
    error_message: "连接失败",
    next_attempt_at: null,
    created_at: "2026-08-17T00:02:00",
  };
  const staleTask = { ...liveTask, id: 7, comic_title: "过期任务", status: "pending", error_code: null, error_message: null };
  let releaseRest!: () => void;
  const restGate = new Promise<void>((resolve) => { releaseRest = resolve; });
  let eventRequests = 0;

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/status") return json(route, { setup_required: false, authenticated: true });
    if (path === "/api/auth/me") return json(route, { authenticated: true, csrf_token: "test-csrf" });
    if (path === "/api/kmoe/status") return json(route, { connected: true, email: "reader@example.com", mirror: "mox.moe", status: "active" });
    if (path === "/api/downloads/events") {
      eventRequests += 1;
      const body = eventRequests === 1
        ? `event: downloads\ndata: ${JSON.stringify({ tasks: [liveTask], counts: { pending: 0, running: 0, completed: 0, failed: 1, cancelled: 0 } })}\n\n: keepalive\n\n`
        : ": keepalive\n\n";
      return route.fulfill({ status: 200, contentType: "text/event-stream", body });
    }
    if (path === "/api/downloads") {
      await restGate;
      return json(route, { tasks: [staleTask], counts: { pending: 1, running: 0, completed: 0, failed: 0, cancelled: 0 } });
    }
    return json(route, { detail: `Unhandled ${path}` }, 500);
  });

  await page.goto("/#/downloads");
  await expect(page.getByRole("button", { name: /失败/ }).locator("span")).toHaveText("1");
  releaseRest();

  await expect(page.getByRole("heading", { name: "实时更新漫画" })).toBeVisible();
  await expect(page.getByRole("button", { name: "重试" })).toBeVisible();
  await expect(page.getByRole("button", { name: /失败/ }).locator("span")).toHaveText("1");
  await expect(page.getByText("过期任务")).toHaveCount(0);
});

test("下载状态筛选取回默认快照外的失败任务并提供重试", async ({ page }) => {
  const failedTask = {
    id: 7,
    comic_id: 1,
    comic_remote_id: "comic-1",
    comic_title: "旧失败漫画",
    item_remote_id: "volume-1",
    item_name: "第一卷",
    content_type: "volume",
    download_format: "epub",
    status: "failed",
    attempt_count: 3,
    progress_bytes: 0,
    total_bytes: null,
    final_path: null,
    error_code: "network_error",
    error_message: "连接失败",
    next_attempt_at: null,
    created_at: "2026-08-17T00:00:00",
    started_at: null,
    completed_at: "2026-08-17T00:01:00",
  };
  const eventStatuses: (string | null)[] = [];
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/auth/status") return json(route, { setup_required: false, authenticated: true });
    if (path === "/api/auth/me") return json(route, { authenticated: true, csrf_token: "test-csrf" });
    if (path === "/api/kmoe/status") return json(route, { connected: true, email: "reader@example.com", mirror: "mox.moe", status: "active" });
    if (path === "/api/downloads/events") {
      eventStatuses.push(url.searchParams.get("status"));
      return route.fulfill({ status: 200, contentType: "text/event-stream", body: ": keepalive\n\n" });
    }
    if (path === "/api/downloads") {
      const filtered = url.searchParams.get("status") === "failed";
      return json(route, {
        tasks: filtered ? [failedTask] : [],
        counts: { pending: 0, running: 0, completed: 100, failed: 1, cancelled: 0 },
      });
    }
    return json(route, { detail: `Unhandled ${path}` }, 500);
  });

  await page.goto("/#/downloads");
  await page.getByRole("button", { name: /失败/ }).click();

  await expect(page.getByRole("heading", { name: "旧失败漫画" })).toBeVisible();
  await expect(page.getByRole("button", { name: "重试" })).toBeVisible();
  await expect.poll(() => eventStatuses).toContain("failed");
});

test("管理员可完成初始化、Kmoe 登录、搜索和订阅", async ({ page }) => {
  let setupRequired = true;
  let connected = false;
  let subscription: Record<string, unknown> | null = null;
  let migration: Record<string, unknown> | null = null;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/auth/status") return json(route, { setup_required: setupRequired, authenticated: !setupRequired });
    if (path === "/api/auth/setup") { setupRequired = false; return json(route, { authenticated: true, csrf_token: "test-csrf" }, 201); }
    if (path === "/api/auth/me") return json(route, { authenticated: true, csrf_token: "test-csrf" });
    if (path === "/api/kmoe/status") return json(route, { connected, email: connected ? "reader@example.com" : null, mirror: connected ? "mox.moe" : null, status: connected ? "active" : null });
    if (path === "/api/kmoe/login") { connected = true; return json(route, { connected: true, email: "reader@example.com", mirror: "mox.moe", status: "active" }); }
    if (path === "/api/subscriptions" && request.method() === "GET") return json(route, subscription ? [subscription] : []);
    if (path === "/api/subscriptions" && request.method() === "POST") { subscription = { id: 1, comic_id: 1, remote_id: "50076", title: "星海书简", author: "林墨", cover_url: null, enabled: true, content_types: ["volume"], download_format: "epub", initialization_strategy: "future_only", last_attempt_at: null, last_success_at: null, next_check_at: null, last_error_code: null, last_error_message: null }; return json(route, subscription, 201); }
    if (path === "/api/subscriptions/1/policy-preview") return json(route, { created: 1, converted: 0, reused: 0, cancelled: 0, retained_running: 0, retained_completed: 0 });
    if (path === "/api/subscriptions/1" && request.method() === "PATCH") { subscription = { ...(subscription ?? {}), content_types: ["volume", "extra"], initialization_strategy: "backfill" }; return json(route, subscription); }
    if (path === "/api/downloads") return json(route, { tasks: [], counts: { pending: 0, running: 0, completed: 0, failed: 0, cancelled: 0 } });
    if (path === "/api/settings" && request.method() === "GET") return json(route, { check_interval_hours: 6, download_concurrency: 2, max_download_retries: 3, preferred_mirror: "mox.moe" });
    if (path === "/api/storage" && request.method() === "GET") return json(route, { mounted_root: "/storage", active_subpath: "", effective_path: "/storage", writable: true, migration });
    if (path === "/api/storage/directories" && request.method() === "GET") return json(route, { path: url.searchParams.get("path") ?? "", directories: ["manga"] });
    if (path === "/api/storage/migrations/preview") return json(route, { source_subpath: "", target_subpath: "manga/library", total_files: 3, total_bytes: 4096 });
    if (path === "/api/storage/migrations" && request.method() === "POST") { migration = { id: 1, source_subpath: "", target_subpath: "manga/library", phase: "completed", failed_phase: null, total_files: 3, processed_files: 3, total_bytes: 4096, processed_bytes: 4096, current_relative_path: null, error_code: null, error_message: null, created_at: "2026-08-17T00:00:00", started_at: "2026-08-17T00:00:00", completed_at: "2026-08-17T00:00:01" }; return json(route, migration, 201); }
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
  await page.getByLabel("保存位置（相对挂载根目录）").fill("manga/library");
  await page.getByRole("button", { name: "预检" }).click();
  await expect(page.getByText(/共 3 个文件/)).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "确认并开始搬迁" }).click();
  await expect(page.getByText("目录迁移已开始")).toBeVisible();

  await page.getByRole("link", { name: "发现漫画" }).click();
  await page.getByLabel("漫画关键词").fill("星海");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await page.getByRole("button", { name: /星海书简/ }).click();
  await expect(page.getByRole("heading", { name: "星海书简" })).toBeVisible();
  await page.getByRole("button", { name: "创建订阅" }).click();
  await expect(page.getByText("已订阅《星海书简》")).toBeVisible();

  await page.getByRole("link", { name: "我的订阅" }).click();
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("番外").check();
  await page.getByLabel("下载策略").selectOption("backfill");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "预览并保存" }).click();
  await expect(page.getByText("订阅策略已保存")).toBeVisible();
});
