<picture><source media="(prefers-color-scheme: dark)" srcset="docs/logo-inverted.svg"><img src="docs/logo.svg" alt="Orchard" height="56"></picture>

Orchard is a private photo browser for a folder on your computer. Point it at a folder and it shows every image inside, subfolders included, as one scrollable library. You can filter by folder, type and date, and search by what the pictures look like. Everything runs locally, nothing is uploaded, and your files are never changed.

- **Timeline.** Images are sorted newest first by the date they were taken, with a year scrubber to jump around.
- **Visual search.** Describe a picture ("dog on a beach"), or paste or drop an image to find similar ones.
- **Map.** The whole folder laid out by similarity, so look-alike images sit together.
- **Duplicates.** Identical files show once. Bursts, edits and resized copies share one tile, fronted by the sharpest.

## Quick start

You need macOS or Linux, Python 3.12+ and Node 18+.

```bash
git clone https://github.com/chaseleantj/orchard.git
cd orchard
./orchard ~/Pictures
```

The first run installs dependencies and builds the page, which takes a few minutes. On Linux without an NVIDIA GPU, it installs the CPU build of PyTorch, which avoids several GB of CUDA libraries. After that, Orchard opens at http://127.0.0.1:4400. Stop it with Ctrl+C.

Run `./orchard` with no folder to reopen the last one. Running it with a folder while Orchard is already open switches to that folder.

On Linux, the Choose folder button needs `zenity` or `kdialog`. Without one, type the folder path instead.

To open Orchard from the Dock or Spotlight like any Mac app, run this once:

```bash
scripts/install-app
```

It installs `~/Applications/Orchard.app`, which starts Orchard in the background (logging to `/tmp/orchard.log`) and opens the page. Orchard stays in the Dock while it runs. Click the icon to bring the page back, and quit it to stop Orchard.

## Visual search

Visual search and the map use CLIP, a model that turns images and text into vectors that sit close together when their meaning is similar. The model is a one-time download of about 600 MB, and runs offline afterwards. Orchard offers to set it up when you open your first folder. You can also set it up later from Info (the ⓘ button). Until then, browsing, filters and file-name search all work without it.

Progress for scanning, downloading and preparing images shows beside the image count. Images can be searched as soon as they're prepared.

## Privacy

Orchard only reads your photos. It never moves, edits or uploads them. The server listens only on this computer and rejects requests from other sites, so don't expose it through a public proxy.

The cache (thumbnails, the search index and the model) lives in `~/Library/Application Support/orchard/` on macOS, and `~/.local/share/orchard/` on Linux. See [Where data lives](docs/how-it-works.md#where-data-lives) to clear it.

## Documentation

- [Using Orchard](docs/using-orchard.md): browsing, search, the map, duplicates, and supported files.
- [How Orchard works](docs/how-it-works.md): scanning, CLIP search, near-duplicate grouping and the map layout.
- [Developing Orchard](docs/development.md): live reload, project layout, tests and renaming.

## License

[MIT](LICENSE)
