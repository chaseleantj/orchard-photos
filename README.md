<picture><source media="(prefers-color-scheme: dark)" srcset="docs/logo-inverted.svg"><img src="docs/logo.svg" alt="Orchard" height="56"></picture>

Orchard is a private photo browser for a folder on your computer. Point it at a folder and it shows every image inside, subfolders included, as one scrollable library. You can filter by folder, type and date, and search by what the pictures look like. Everything runs locally, nothing is uploaded, and your files are never changed.

- **Timeline.** Images are sorted newest first by the date they were taken, with a year scrubber to jump around.
- **Visual search.** Describe a picture ("dog on a beach"), or paste or drop an image to find similar ones.
- **Map.** The whole folder laid out by similarity, so look-alike images sit together.
- **Duplicates.** Identical files show once. Bursts, edits and resized copies share one tile, fronted by the sharpest.

## Quick start

You need macOS or Linux, and Python 3.12 or later. If your Python is older, `./orchard` says which version it found and how to get a newer one. On Debian and Ubuntu, you also need the `python3-venv` package.

```bash
git clone https://github.com/chaseleantj/orchard.git
cd orchard
./orchard ~/Pictures
```

The first run installs Python packages, which takes a few minutes: about 300 MB to download, and 1.2 GB on disk. On Linux without an NVIDIA GPU, it installs the CPU build of PyTorch, which avoids several GB of CUDA libraries. After that, Orchard opens at http://127.0.0.1:4400. Stop it with Ctrl+C.

Run `./orchard` with no folder to reopen the last one. Running it with a folder while Orchard is already open switches to that folder.

On Linux, the Choose folder button needs `zenity` or `kdialog`. Without one, type the folder path instead.

To open Orchard from the Dock or Spotlight like any Mac app, run this once:

```bash
scripts/install-app
```

It installs `~/Applications/Orchard.app`, which starts Orchard in the background and opens the page. The first start sets things up, which takes a few minutes. If Orchard can't start, the app shows the end of its log, `/tmp/orchard.log`. Orchard stays in the Dock while it runs. Click the icon to bring the page back, and quit it to stop Orchard.

The app finds Python the same way your Terminal does when you run `scripts/install-app`. If you install Python somewhere new later, run it again.

## Visual search

Visual search and the map use CLIP, a model that turns images and text into vectors that sit close together when their meaning is similar. The model is a one-time download of about 600 MB, and runs offline afterwards. Orchard offers to set it up when you open your first folder. You can also set it up later from Info (the ⓘ button). Until then, browsing, filters and file-name search all work without it.

Progress for scanning, downloading and preparing images shows beside the image count. Images can be searched as soon as they're prepared.

## Privacy

Orchard only reads your photos. It never moves, edits or uploads them. The server listens only on this computer and rejects requests from other sites, so don't expose it through a public proxy.

The cache (thumbnails, the search index and the model) lives in `~/Library/Application Support/orchard/` on macOS, and `~/.local/share/orchard/` on Linux. See [Where data lives](docs/how-it-works.md#where-data-lives) to clear it.

## Uninstall

Quit Orchard, then delete whichever of these you have:

- The `orchard` folder you cloned or downloaded. Its `.venv` folder holds the Python packages.
- `~/Applications/Orchard.app`, if you ran `scripts/install-app`.
- The cache and search model, in `~/Library/Application Support/orchard/` on macOS and `~/.local/share/orchard/` on Linux, and any folder you gave with `--data-dir`.
- `/tmp/orchard.log`, the Mac app's log. macOS clears it when you restart.
- pip's download cache, in `~/Library/Caches/pip` on macOS and `~/.cache/pip` on Linux. Other Python projects share it, but deleting it is safe.
- npm's cache in `~/.npm`, if you built the page yourself. Deleting it is also safe.

## Documentation

- [Using Orchard](docs/using-orchard.md): browsing, search, the map, duplicates, and supported files.
- [How Orchard works](docs/how-it-works.md): scanning, CLIP search, near-duplicate grouping and the map layout.
- [Developing Orchard](docs/development.md): live reload, project layout, tests and renaming.

## License

[MIT](LICENSE)
