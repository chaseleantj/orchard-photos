<picture><source media="(prefers-color-scheme: dark)" srcset="docs/logo-inverted.svg"><img src="docs/logo.svg" alt="Orchard Photos" height="56"></picture>

Orchard Photos is a private, local photo browser with AI search. Point it at a folder on your computer and it shows every image inside, subfolders included, as one scrollable library. You can filter by folder, type and date, and search by describing a picture or showing a similar one. Everything runs on your computer, nothing is uploaded, and your files are never changed.

- **Timeline.** Images are sorted newest first by the date they were taken, with a year scrubber to jump around.
- **Visual search.** Describe a picture ("dog on a beach"), or paste or drop an image to find similar ones.
- **Map.** The whole folder laid out by similarity, so look-alike images sit together.
- **Duplicates.** Identical files show once. Bursts, edits and resized copies share one tile, fronted by the sharpest.

## Quick start

You need macOS, Linux or Windows, and Python 3.12, 3.13 or 3.14. Python 3.15 doesn't work yet, because ONNX Runtime, which runs visual search, has no packages for it. If your Python doesn't fit, `./orchard` says which version it found and how to get a supported one. On Debian and Ubuntu, install the packages [below](#linux-packages) first. For Windows, see [Windows](#windows) below.

```bash
git clone https://github.com/chaseleantj/orchard-photos.git
cd orchard-photos
./orchard ~/Pictures
```

The first run installs Python packages, which takes about a minute: about 55 MB to download and 230 MB on disk on macOS, and about 65 MB and 250 MB on Linux. After that, Orchard opens in its own window. Close the window, or press Ctrl+C in the terminal, to quit.

Run `./orchard` with no folder to reopen the last one. Running it with a folder while Orchard is already open switches the open window to that folder. To use your browser instead of a window, add `--browser`. Orchard is then at http://127.0.0.1:4400.

<a id="linux-packages"></a>On Linux, Python needs its venv package, and the window needs GTK's web view for Python, which pip can't install. On Ubuntu and Debian, including WSL:

```bash
sudo apt update && sudo apt install python3-venv python3-gi gir1.2-webkit2-4.1
```

Without the GTK packages, Orchard opens in your browser and says why. In the browser, the Choose folder button needs `zenity` or `kdialog`. Without one, type the folder path instead. Under WSL, Show in folder opens File Explorer, and the browser is your Windows one.

### Windows

Install Python 3.13 and the Microsoft Visual C++ Redistributable, which visual search needs, in Command Prompt or PowerShell:

```bat
winget install Python.Python.3.13
winget install Microsoft.VCRedist.2015+.x64
```

On a laptop with an Arm processor, like a Snapdragon, use `Microsoft.VCRedist.2015+.arm64` instead. Then clone or download Orchard, and run `orchard.cmd` in its folder, or double-click it. Open a new Command Prompt first, since the one that ran winget doesn't see the new Python yet. If you downloaded a zip, right-click it, choose Properties, then Unblock before extracting it, or Windows asks before running `orchard.cmd`.

```bat
orchard.cmd C:\Users\you\Pictures
```

The first run installs Python packages into the `.venv` folder beside it, which takes about two minutes, a download of about 90 MB, and 290 MB on disk. The window uses Microsoft Edge's WebView2, which comes with Windows 10 and 11. Visual search runs on the GPU through DirectML, with any DirectX 12 graphics from NVIDIA, AMD or Intel, and falls back to the CPU without one. On Windows on Arm, it uses the CPU. In the browser, there is no Choose folder button on Windows, so type or paste the folder path instead.

### The Mac app

To open Orchard from the Dock or Spotlight like any Mac app, run this once:

```bash
scripts/install-app
```

It installs `~/Applications/Orchard.app`, which opens Orchard's window. The first start sets things up, which takes about a minute. If Orchard can't start, the app shows the end of its log, `/tmp/orchard.log`. Closing the window quits Orchard.

The app finds Python the same way your Terminal does when you run `scripts/install-app`. If you install Python somewhere new later, run it again. With Python from Homebrew or python.org, the window shows in the Dock as Orchard. With other Pythons, like pyenv's, it shows as Python.

## Visual search

Visual search and the map use SigLIP 2, a model that turns images and text into vectors that sit close together when their meaning is similar. It understands descriptions in many languages. The model is a one-time download of about 500 MB on an Apple Silicon Mac, or 690 MB on other computers, and runs offline afterwards. Orchard offers to set it up when you open your first folder. You can also set it up later from Info (the ⓘ button). Until then, browsing, filters and file-name search all work without it.

Progress for scanning, downloading and preparing images shows beside the image count. Images can be searched as soon as they're prepared.

## Privacy

Orchard only reads your photos. It never moves, edits or uploads them. The server listens only on this computer and rejects requests from other sites, so don't expose it through a public proxy.

The cache (thumbnails, the search index and the model) lives in `~/Library/Application Support/orchard/` on macOS, `~/.local/share/orchard/` on Linux, and `%LOCALAPPDATA%\orchard\` on Windows. See [Where data lives](docs/how-it-works.md#where-data-lives) to clear it.

## Uninstall

Quit Orchard, then delete whichever of these you have:

- The `orchard-photos` folder you cloned, or the folder you downloaded. Its `.venv` folder holds the Python packages.
- `~/Applications/Orchard.app`, if you ran `scripts/install-app`.
- The cache and search model, in `~/Library/Application Support/orchard/` on macOS, `~/.local/share/orchard/` on Linux and `%LOCALAPPDATA%\orchard\` on Windows, and any folder you gave with `--data-dir`.
- `/tmp/orchard.log`, the Mac app's log. macOS clears it when you restart.
- pip's download cache, in `~/Library/Caches/pip` on macOS, `~/.cache/pip` on Linux and `%LOCALAPPDATA%\pip\Cache` on Windows. Other Python projects share it, but deleting it is safe.
- npm's cache in `~/.npm`, if you built the page yourself. Deleting it is also safe.

## Documentation

- [Using Orchard](docs/using-orchard.md): browsing, search, the map, duplicates, and supported files.
- [How Orchard works](docs/how-it-works.md): scanning, visual search, near-duplicate grouping and the map layout.
- [Developing Orchard](docs/development.md): live reload, project layout, tests and renaming.

## License

[MIT](LICENSE)
