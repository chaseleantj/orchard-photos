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
  // The count reads into the folder button: "Showing 12 images in photos", then any filters.
  const showing = (count: string, scope = '') => `Showing ${count} in photos${scope}`;
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
    await expect(meta).toHaveText(showing(plural(FIXTURE.images, 'image')));
  });

  await test.step('the status line offers visual search in words, with its download size', async () => {
    const line = page.locator('.activity');
    await expect(line.getByRole('button', { name: /^Set up visual search · \d+ MB, once$/ })).toBeVisible();
    await expect(line.getByRole('progressbar')).toHaveCount(0);
  });

  await test.step('Ctrl+R reloads the page and rescans the folder', async () => {
    const rescan = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/api/scan'));
    await page.locator('body').press('Control+r');
    await rescan;
    await expect(pictures).toHaveCount(FIXTURE.images);
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

  await test.step('the grid is one tab stop, and arrow keys move across it', async () => {
    await expect(pictures.and(page.locator('[tabindex="0"]'))).toHaveCount(1);
    await pictures.first().focus();
    await page.keyboard.press('ArrowRight');
    await expect(pictures.nth(1)).toBeFocused();
    await expect(pictures.nth(1)).toHaveAttribute('tabindex', '0');
    await page.keyboard.press('ArrowLeft');
    await expect(pictures.first()).toBeFocused();
  });

  await test.step('the viewer zooms, swipes, and keeps its keys when focus falls out of it', async () => {
    await page.keyboard.press('Enter');
    const viewer = page.getByRole('dialog', { name: 'Image viewer' });
    const name = viewer.getByRole('heading', { level: 1 });
    const stage = viewer.locator('.image-stage');
    const first = await name.textContent();
    await viewer.locator('.image-stage img').click();
    await expect(stage).toHaveClass(/zoomed/);
    // Escape zooms out before it closes.
    await page.keyboard.press('Escape');
    await expect(stage).not.toHaveClass(/zoomed/);
    await expect(viewer).toBeVisible();
    await page.keyboard.press('ControlOrMeta+=');
    await expect(stage).toHaveClass(/zoomed/);
    await page.keyboard.press('ControlOrMeta+0');
    await expect(stage).not.toHaveClass(/zoomed/);
    // A two-finger swipe left moves to the next image, and one right comes back.
    await stage.hover();
    await page.mouse.wheel(200, 0);
    await expect(name).not.toHaveText(first!);
    await page.waitForTimeout(400);
    await page.mouse.wheel(-200, 0);
    await expect(name).toHaveText(first!);
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await page.keyboard.press('ArrowRight');
    await expect(name).not.toHaveText(first!);
    await page.keyboard.press('Escape');
    await expect(viewer).toBeHidden();
  });

  await test.step('a tile dropped on the search bar searches with its image', async () => {
    await pictures.first().locator('img').dragTo(page.getByRole('search'));
    await expect(page.getByRole('search').getByAltText('Image you are matching')).toBeVisible();
    await page.getByRole('button', { name: 'Clear search' }).click();
    await expect(meta).toHaveText(showing(plural(FIXTURE.images, 'image')));
  });

  await test.step('the folders sidebar shows one folder, by pointer or keyboard, and collapses', async () => {
    const tree = page.getByRole('tree', { name: 'Folders' });
    const everything = tree.getByRole('treeitem', { name: `All images ${FIXTURE.images}` });
    const trips = tree.getByRole('treeitem', { name: `trips ${FIXTURE.trips}` });
    await expect(everything).toHaveAttribute('aria-selected', 'true');
    await trips.click();
    await expect(meta).toHaveText(showing(plural(FIXTURE.trips, 'image'), ' › trips'));
    await expect(pictures).toHaveCount(FIXTURE.trips);
    await expect(trips).toHaveAttribute('aria-selected', 'true');
    // A filter that is on is a button in the line, which takes it off again.
    await page.getByRole('button', { name: 'trips. Show all folders' }).click();
    await expect(meta).toHaveText(showing(plural(FIXTURE.images, 'image')));
    await expect(everything).toHaveAttribute('aria-selected', 'true');
    // The tree is one tab stop; the arrow keys move through it and Enter shows a folder.
    await everything.focus();
    await page.keyboard.press('ArrowDown');
    await expect(trips).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(meta).toHaveText(showing(plural(FIXTURE.trips, 'image'), ' › trips'));
    await page.keyboard.press('ArrowUp');
    await page.keyboard.press('Enter');
    await expect(meta).toHaveText(showing(plural(FIXTURE.images, 'image')));
    // Collapsed, it stays collapsed after a reload, and the folder is still said in the line.
    await page.getByRole('button', { name: 'Hide folders' }).click();
    await expect(tree).toBeHidden();
    await page.reload();
    await expect(page.getByRole('button', { name: 'Show folders' })).toBeVisible();
    await expect(tree).toBeHidden();
    await page.getByRole('button', { name: 'Show folders' }).click();
    await expect(everything).toBeVisible();
  });

  await test.step('filters narrow the grid by type and date', async () => {
    await filter(page, 'File type', 'image/bmp');
    await expect(meta).toHaveText(showing(plural(1, 'image'), ' · BMP'));
    await filter(page, 'File type', '');
    await filter(page, 'Date', 'year');
    await expect(meta).toHaveText(showing(plural(FIXTURE.today, 'image'), ' · Past year'));
    await filter(page, 'Date', 'all');
    await expect(meta).toHaveText(showing(plural(FIXTURE.images, 'image')));
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
    await expect(meta).toHaveText(showing(plural(1, 'match', 'matches')));
    await expect(pictures).toHaveCount(1);
    await expect(pictures.first()).toHaveAccessibleName('Open beach.png');
    // The map counts the same file-name matches it lights.
    await page.getByRole('button', { name: 'Map', exact: true }).click();
    await expect(meta).toHaveText(showing(plural(1, 'match', 'matches')));
    await page.getByRole('button', { name: 'Grid', exact: true }).click();
    await page.getByRole('button', { name: 'Clear search' }).click();
    await expect(pictures).toHaveCount(FIXTURE.images);
  });

  await test.step('Cmd or Ctrl and Z undo and redo searches', async () => {
    const box = page.getByRole('textbox', { name: 'Search images' });
    await box.fill('red');
    await page.keyboard.press('Enter');
    await expect(pictures).toHaveCount(1);
    await box.fill('beach');
    await page.keyboard.press('Enter');
    await expect(pictures.first()).toHaveAccessibleName('Open beach.png');
    // The search bar still holds the search shown, so the keys step through searches there too.
    await page.keyboard.press('ControlOrMeta+z');
    await expect(box).toHaveValue('red');
    await expect(pictures.first()).toHaveAccessibleName('Open red.png');
    await pictures.first().focus();
    await page.keyboard.press('ControlOrMeta+Shift+z');
    await expect(box).toHaveValue('beach');
    await expect(pictures.first()).toHaveAccessibleName('Open beach.png');
    await expect(page).toHaveURL(/\?q=beach$/);
    // Words typed since are undone first, leaving the search alone.
    await box.press('End');
    await page.keyboard.type('es');
    await page.keyboard.press('ControlOrMeta+z');
    await expect(box).toHaveValue('beach');
    await expect(pictures.first()).toHaveAccessibleName('Open beach.png');
    // Clearing is a step too.
    await page.getByRole('button', { name: 'Clear search' }).click();
    await expect(pictures).toHaveCount(FIXTURE.images);
    await pictures.first().focus();
    await page.keyboard.press('ControlOrMeta+z');
    await expect(pictures).toHaveCount(1);
    await page.keyboard.press('ControlOrMeta+Shift+z');
    await expect(pictures).toHaveCount(FIXTURE.images);
    await expect(box).toHaveValue('');
  });

  await test.step('slash goes to the search bar from the grid, the viewer and the map', async () => {
    const box = page.getByRole('textbox', { name: 'Search images' });
    const selection = () => box.evaluate((input: HTMLInputElement) => input.value.slice(input.selectionStart!, input.selectionEnd!));
    await box.fill('red');
    await pictures.first().focus();
    await page.keyboard.press('/');
    await expect(box).toBeFocused();
    await expect(box).toHaveValue('red');
    expect(await selection()).toBe('red');
    // In the search bar, a slash is typed like any other character.
    await page.keyboard.press('/');
    await expect(box).toHaveValue('/');
    await box.fill('');
    // Held with a modifier, or typed in another field, a slash is left alone.
    await pictures.first().focus();
    await page.keyboard.press('Control+/');
    await expect(box).not.toBeFocused();
    await page.getByRole('button', { name: 'photos', exact: true }).click();
    const path = page.getByRole('dialog', { name: 'Folder' }).getByPlaceholder('~/Pictures');
    await path.fill('~');
    await page.keyboard.press('/');
    await expect(path).toHaveValue('~/');
    await page.keyboard.press('Escape');

    await pictures.first().click();
    const viewer = page.getByRole('dialog', { name: 'Image viewer' });
    await expect(viewer).toBeVisible();
    await page.keyboard.press('/');
    await expect(viewer).toBeHidden();
    await expect(box).toBeFocused();

    await page.getByRole('button', { name: 'Map', exact: true }).click();
    await page.keyboard.press('/');
    await expect(box).toBeFocused();
    await page.getByRole('button', { name: 'Grid', exact: true }).click();
  });
});

test('while the model is here and a scan reads, the page waits instead of offering setup', async ({ page }) => {
  // The folder the first test opened, with the status of a first scan that visual search is waiting on.
  await page.route('**/api/status', async route => {
    const status = await (await route.fetch()).json();
    status.model.present = true;
    status.library.scan = { state: 'scanning', found: 7872, done: 1200, changed: 7872 };
    status.library.search = { state: 'waiting', indexed: 0, total: 1200, downloaded: true };
    await route.fulfill({ json: status });
  });
  await page.goto('/');
  const line = page.locator('.activity');
  await expect(line.getByRole('button', { name: 'Reading images: 1,200 of 7,872' })).toBeVisible();
  await expect(line.getByRole('progressbar')).toHaveCount(0);
  await page.getByRole('button', { name: 'Search options' }).click();
  const menu = page.getByRole('dialog', { name: 'Search options' });
  await expect(menu.getByRole('button', { name: 'Appearance' })).toBeDisabled();
  await expect(menu.getByText('Ready once your images are read')).toBeVisible();
  await expect(page.getByText(/set up/i)).toHaveCount(0);
});

test('how many images a search covers is said once, by the status line while they are being prepared', async ({ page }) => {
  // Some images prepared: first with the rest being prepared, then with the rest waiting on a scan.
  let search = { state: 'indexing', indexed: 1542, total: 7504, downloaded: true };
  let scan: Record<string, unknown> = { state: 'ready' };
  await page.route('**/api/status', async route => {
    const status = await (await route.fetch()).json();
    status.model.present = true;
    Object.assign(status.library, { scan, search });
    await route.fulfill({ json: status });
  });
  await page.goto('/');
  const row = page.locator('.library-meta');
  await page.getByRole('textbox', { name: 'Search images' }).fill('a red square');
  await page.keyboard.press('Enter');
  await expect(row.getByRole('button', { name: 'Preparing visual search: 1,542 of 7,504' })).toBeVisible();
  await expect(row.locator('.showing')).not.toContainText('prepared');
  search = { ...search, state: 'waiting' };
  scan = { state: 'scanning', found: 7872, done: 7600, changed: 7872 };
  await expect(row.getByRole('button', { name: 'Reading images: 7,600 of 7,872' })).toBeVisible();
  await expect(row.locator('.showing')).toContainText('1,542 of 7,504 prepared');
});
