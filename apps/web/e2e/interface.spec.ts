import { expect, test } from "@playwright/test";
import { fixture, mockApi } from "./mock-api";

test("UI contract: login → experiment → arena → finding → comparison → signed report", async ({ page }) => {
  const state = await mockApi(page);
  await page.goto("/login");
  await page.getByText("Локальный вход для разработки", {exact:true}).click();
  await page.getByLabel("Имя", { exact: true }).fill("Исследователь");
  await page.getByLabel("Почта", { exact: true }).fill("test@example.test");
  await page.getByRole("button", { name: "Войти в тестовый аккаунт", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Проекты", exact: true })).toBeVisible();
  await page.goto("/experiments/batch-control");
  await expect(page.getByRole("heading", { name: "Контрольная серия" })).toBeVisible();
  await page.goto("/runs/SD-P1-101/live");
  await expect(page.getByRole("region", { name: "Арена подтвержденных событий" })).toBeVisible();
  await expect(page.getByText("Начисленная награда", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Посмотреть историю" }).click();
  await expect(page.getByText(/Просмотр истории/)).toBeVisible();
  await page.getByRole("button", { name: "Следующее нарушение", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "Инспектор" })).toContainText("Нарушение");
  await page.goto(`/findings/${fixture.findings[0].id}`);
  await expect(page.getByRole("heading", { name: "Нарушенное свойство", exact: true })).toBeVisible();
  await page.goto("/comparisons/comparison-control");
  await expect(page.getByRole("heading", { name: "Сравнение вариантов", exact: true })).toBeVisible();
  await page.getByText("Подробная статистика и методика",{exact:true}).click();
  await expect(page.getByText(/Bootstrap 95/).first()).toBeVisible();
  await page.getByLabel("Формат отчета").selectOption("markdown");
  await page.getByRole("button", { name: "Создать отчет", exact: true }).click();
  await expect(page).toHaveURL(/\/reports\/report-control$/);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /Скачать/ }).click();
  expect((await download).suggestedFilename()).toContain(".md");
  expect(state.requests).toContain("POST /reports");
});

test("SSE gap recovery, duplicate suppression, connection loss, and access revocation", async ({ page }) => {
  const state = await mockApi(page, { live: true, available: 3 });
  await page.goto("/runs/SD-P1-101/live");
  await expect(page.locator(".arena-connection")).toContainText("событие #3");
  state.available = 5;
  const event = fixture.logs["SD-P1-101"][4];
  await page.evaluate((data) => {
    const source = (window as any).__sources.at(-1);
    source.dispatchEvent(new MessageEvent("run_event", { data: JSON.stringify(data) }));
    source.dispatchEvent(new MessageEvent("run_event", { data: JSON.stringify(data) }));
  }, event);
  await expect(page.locator(".arena-connection")).toContainText("событие #5");
  await expect(page.getByText(/Восстановлено событий: 1/)).toBeVisible();
  await expect(page.locator(".arena-journal tbody tr")).toHaveCount(5);
  await page.evaluate(() => (window as any).__sources.at(-1).dispatchEvent(new Event("error")));
  await expect(page.locator(".arena-connection")).toContainText("Связь потеряна");
  await expect(page.locator(".arena-scene")).toHaveClass(/arena-frozen/);
  await expect.poll(() => page.evaluate(() => (window as any).__sources.length)).toBeGreaterThan(1);
  await page.evaluate(() => (window as any).__sources.at(-1).dispatchEvent(new Event("access_revoked")));
  await expect(page.getByText("Доступ отозван", { exact: true })).toBeVisible();
  await expect(page.locator(".arena-scene")).toHaveCount(0);
});

test("Replay speed and tick seek preserve projection, reduced motion retains controls", async ({ page }) => {
  const state = await mockApi(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/runs/SD-P1-101/replay");
  await expect(page.locator(".arena-connection")).toContainText("Журнал загружен");
  await page.getByLabel("К тику", { exact: true }).fill("5");
  await page.getByRole("button", { name: "Перейти", exact: true }).click();
  const value = await page.locator(".arena-registers").innerText();
  for (const speed of ["0.5", "1", "2", "4"]) {
    await page.getByLabel("Скорость", { exact: true }).selectOption(speed);
    expect(await page.locator(".arena-registers").innerText()).toBe(value);
  }
  await expect(page.locator(".arena-scene")).toHaveClass(/arena-reduced/);
  await expect(page.getByRole("button", { name: "Следующий шаг →", exact: true })).toBeEnabled();
  expect(state.requests.filter((r) => r.startsWith("POST"))).not.toContainEqual(expect.stringContaining("model"));
});

for (const width of [360, 390, 768, 1024, 1440, 1920]) {
  test(`UI layout at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await mockApi(page);
    for (const path of ["/runs/SD-P1-101/live", "/runs/SD-P1-101/replay", "/findings/finding-0", "/comparisons/comparison-control", "/reports/report-control", "/settings/workspace", "/settings/models", "/settings/profile"]) {
      await page.goto(path);
      await expect(page.locator("#main")).toBeVisible();
      await expect(page.getByRole("heading").first()).toBeVisible();
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), { message: `Horizontal overflow: ${path} @ ${width}` }).toBe(true);
    }
  });
}
