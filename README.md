# Orchard

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/logo-inverted.svg"><img src="docs/logo.svg" alt="Orchard" height="56"></picture>

Orchard is a private photo browser for a folder on your computer. Point it at a folder and it shows every image inside, including all subfolders. You can scroll through them, filter by folder, type and date, and search by what the pictures look like. Everything runs locally, and your files are never changed.

## Run

```sh
./orchard ~/Pictures
```

This starts the server at http://127.0.0.1:4400 and opens it in your browser. Without a folder, Orchard reopens the last one. If Orchard is already running, the command switches it to the new folder. Stop the server with Ctrl+C.

To use `orchard` as a terminal command from anywhere (with `~/.local/bin` on your PATH):

```sh
ln -s "$PWD/orchard" ~/.local/bin/orchard
```

First-time setup:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm ci
npm run build
```

For frontend development, run `.venv/bin/python -m server.api <folder>` and `npm run dev` in separate terminals. Vite proxies the API.

## Use

Images appear newest first. A photo is dated by when it was taken, from its EXIF data. Images without that record use the date the file last changed.

Click an image to open it. The viewer shows the file name, folder, dimensions, size, type, camera and full path. From there you can download the original, show it in Finder, find similar images, or jump to its folder. Arrow keys move between images and Escape closes the viewer. Identical files appear once, and the viewer lists every place a copy is saved.

**Filter** narrows the grid by subfolder (subfolders of it included), file type, and date: Today, Past 7 days, Past 28 days, Past year, All, or a custom range.

**Search** defaults to appearance. Type a description and press Enter. You can also drop an image on the search bar, paste one, drag an image from the grid into it, or choose **Find similar**. Searching by an image shows its 100 closest matches. The search options button switches to searching file names. Filters still apply to every search.

**Map** lays the whole folder out by similarity, so look-alike images sit together. Scroll or pinch to zoom, drag to move, and click an image for a larger card. Searching lights up the matches and dims the rest. The first layout takes a few seconds. New images are placed next to their nearest neighbours, so the map stays put. The refresh button at the top left lays it out again, and images glide to their new places.

**Folder**, at the right of the line under the search bar, switches folders. On a Mac it opens the system folder dialog. You can also type a path or pick a recent folder. Each folder keeps its own cache, so switching back is quick.

**Library** (the ⓘ button) shows counts, lists files that could not be read and why, and can rescan the folder. Orchard also rescans every minute, so added, changed and removed files show up without asking.

Visual search uses CLIP, a model that places images and text in the same space. It is downloaded once (about 600 MB) from **Library → Prepare visual search** and then runs offline. After that, every folder you open is prepared automatically.

## What it reads

JPEG, PNG, GIF, WebP, BMP, TIFF, HEIC/HEIF and AVIF. Browsers cannot show HEIC and TIFF, so the viewer shows a converted JPEG preview of those, and Download still gives you the original.

Hidden files and folders are skipped, which also skips the `._` files macOS leaves on external drives. Symlinked folders are followed once, so a link loop cannot trap the scan. Damaged, empty and oversized files (over 300 megapixels) are listed in Library with a reason and skipped. If the folder disappears, for example on an unplugged drive, Orchard keeps showing the last scan and says the folder is unavailable.

## Where data lives

The cache lives in `~/Library/Application Support/orchard/` (`~/.local/share/orchard/` on Linux). You can choose another location with `--data-dir`. It contains:

- `models/`: the CLIP weights, shared by all folders.
- `libraries/<id>/`: one folder per image folder, holding its SQLite index, thumbnails, previews, embeddings, map positions and map icon sheets. `folder.txt` names the folder it belongs to.
- `recent.json`: the recent folders.

Deleting a `libraries/<id>` folder clears that folder's cache. The server listens only on this computer and rejects requests from other sites. Do not expose it through a public proxy.

## Renaming

The name, command slug and ports live in `app.json`. The logo (in `web/src/Logo.tsx`, `public/` and `docs/`) spells the name, so it changes with a rename. The window title, wordmark, messages, data folder and browser storage keys all read it. The package name in `package.json`, the `orchard` launcher file name, and this README also carry the name.

## Verify

```sh
npm run build
.venv/bin/python -m unittest discover -s tests -v
```
