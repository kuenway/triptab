import { expect, type Page } from "@playwright/test";

export async function openSection(page: Page, name: "Expenses" | "Balances" | "Tripmates" | "History") {
  const link = page.getByRole("navigation", { name: "Trip sections" }).getByRole("link", { name, exact: true });
  await link.click();
  await expect(link).toHaveAttribute("aria-current", "page");
}

export async function openExpense(page: Page) {
  await page.getByRole("button", { name: "Add expense", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Add expense", exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}
