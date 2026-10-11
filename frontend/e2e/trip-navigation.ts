import { expect, type Page } from "@playwright/test";

export async function openSection(page: Page, name: "Expenses" | "Balances" | "Travelers" | "History") {
  const link = page.getByRole("navigation", { name: "Trip sections" }).getByRole("link", { name, exact: true });
  await link.click();
  await expect(link).toHaveAttribute("aria-current", "page");
}
