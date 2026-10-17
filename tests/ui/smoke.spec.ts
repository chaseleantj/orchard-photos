import { expect, test, type Page } from '@playwright/test';
import { FIXTURE } from './server';

const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

async function filter(page: Page, label: string, value: string) {
  await page.getByRole('button', { name: /^Filters/ }).click();
  const panel = page.getByRole('dialog', { name: 'Filters' });
  // The folder and type lists are disabled until their facets arrive.
  await expect(panel.getByLabel(label)).toBeEnabled();
  await panel.getByLabel(label).selectOption(value);
  await panel.getByRole('button', { name: 'Apply' }).click();
  await expect(panel).toBeHidden();
}

test('opens a folder and browses, filters, maps and searches it', async ({ page }) => {
  const meta = page.locator('.library-meta p');
  const pictures = page.getByRole('button', { name: /^Open / });

  await test.step('welcome screen', async () => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Choose a folder of images' })).toBeVisible();
  });

  await test.step('open the folder, without setting up visual search', async () => {
    await page.getByRole('checkbox', { name: /Set up visual search too/ }).uncheck();
    await page.getByPlaceholder('~/Pictures').fill(process.env.ORCHARD_UI_PHOTOS!);
    await page.getByRole('button', { name: 'Open', exact: true }).click();
    await expect(page.getByRole('button', { name: 'photos', exact: true })).toBeVisible();
  });

  await test.step('the grid fills', async () => {
    await expect(pictures).toHaveCount(FIXTURE.images);
    await expect(meta).toHaveText(plural(FIXTURE.images, 'image'));
  });

  await test.step('the viewer opens, steps to the next image and closes', async () => {
    await pictures.first().click();
    const viewer = page.getByRole('dialog', { name: 'Image viewer' });
    const name = viewer.getByRole('heading', { level: 1 });
    const first = await name.textContent();
    await expect(viewer.locator('img').first()).toBeVisible();
    await viewer.getByRole('button', { name: 'Next image' }).click();
    await expect(name).not.toHaveText(first!);
    await page.keyboard.press('Escape');
    await expect(viewer).toBeHidden();
  });

  await test.step('filters narrow the grid by folder, type and date', async () => {
    await filter(page, 'Folder', 'trips');
    await expect(meta).toHaveText(`${plural(FIXTURE.trips, 'image')} · in trips`);
    await expect(pictures).toHaveCount(FIXTURE.trips);
    await filter(page, 'Folder', '');
    await filter(page, 'File type', 'image/bmp');
    await expect(meta).toHaveText(`${plural(1, 'image')} · BMP`);
    await filter(page, 'File type', '');
    await filter(page, 'Date', 'year');
    await expect(meta).toHaveText(`${plural(FIXTURE.today, 'image')} · Past year`);
    await filter(page, 'Date', 'all');
    await expect(meta).toHaveText(plural(FIXTURE.images, 'image'));
  });

  await test.step('the map offers to set up visual search, since there is no model', async () => {
    await page.getByRole('button', { name: 'Map', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Your folder, laid out by look' })).toBeVisible();
    await page.getByRole('button', { name: 'Grid', exact: true }).click();
    await expect(pictures).toHaveCount(FIXTURE.images);
  });

  await test.step('typed searches match file names', async () => {
    await expect(page.getByRole('textbox', { name: 'Search images' })).toHaveAttribute('placeholder', 'Search file names');
    await page.getByRole('textbox', { name: 'Search images' }).fill('beach');
    await page.keyboard.press('Enter');
    await expect(meta).toHaveText(plural(1, 'match', 'matches'));
    await expect(pictures).toHaveCount(1);
    await expect(pictures.first()).toHaveAccessibleName('Open beach.png');
    await page.getByRole('button', { name: 'Clear search' }).click();
    await expect(pictures).toHaveCount(FIXTURE.images);
  });
});
