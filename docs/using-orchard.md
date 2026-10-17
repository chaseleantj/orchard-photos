# Using Orchard

This guide covers what you can do in Orchard once it's running. To install it, see the [README](../README.md).

## Opening a folder

Choose a folder with **Folder**, at the right of the line under the search bar. It opens the system folder dialog, or you can type or paste a path, or pick a recent folder. In the browser, the dialog needs `zenity` or `kdialog` on Linux, and Windows has none, so type the path there.

You can also open a folder from the terminal, with `./orchard ~/Pictures`, or `orchard.cmd C:\Users\you\Pictures` on Windows. If Orchard is already open, this switches its window to the folder and brings it to the front.

Each folder keeps its own cache, so switching back to a folder you've opened before is quick. If the folder goes away, for example on an unplugged drive, Orchard keeps showing the last scan and says the folder is unavailable.

## The window and the browser

Orchard opens in its own window, and closing the window quits it. The window remembers its size and place, and the page remembers settings like the theme and filters.

To use your browser instead, start Orchard with `--browser`, like `./orchard ~/Pictures --browser`. Orchard is then at http://127.0.0.1:4400, and stops when you press Ctrl+C in the terminal.

On Linux, the window needs the system's GTK packages, `python3-gi` and `gir1.2-webkit2-4.1`. They work with the system's own `python3`. Without them, or without a display, Orchard opens in the browser and says why. Under WSL, the browser is your Windows one, and Show in folder opens File Explorer.

## The Mac app

`scripts/install-app` installs `~/Applications/Orchard.app`, which opens Orchard's window from the Dock or Spotlight. The first start sets things up, which takes about a minute. If Orchard can't start, the app shows the end of its log, `/tmp/orchard.log`.

The app finds Python the way your terminal did when you ran `scripts/install-app`, so run it again if you install Python somewhere new. With Python from Homebrew or python.org, the window shows in the Dock as Orchard. With other Pythons, like pyenv's, it shows as Python.

## Browsing

Images are shown newest first, grouped by month. A photo is dated by when it was taken, from its EXIF data. Images without EXIF data use the date the file was last changed.

The column of years on the right is a timeline of the whole folder, where each year takes space in proportion to its images. Click or drag it to jump to a month. When it's focused, you can use these keys:

| Key | Action |
| --- | --- |
| Up / Down arrow | Move one month |
| Page Up / Page Down | Move one year |
| Home / End | Go to the newest or oldest image |

## Viewing an image

Click an image to open it. The viewer shows the file name, date, folder, size and type. **Details** adds the full path, the camera, and any other copies of the file.

From the viewer, you can:

- Find similar images.
- Copy the image, with Cmd+C on a Mac or Ctrl+C elsewhere.
- Download the original. In the window, this asks where to save it.
- Show it in Finder, in Explorer on Windows, or in your file manager on Linux.
- Click its folder to show only images from that folder.
- Click the image, or the zoom button, to see it at actual size.

Use the left and right arrow keys to move between images, and Escape to close the viewer.

## Duplicates

Identical files appear once, and the viewer lists every place a copy is saved.

Images that look almost the same, like bursts, edits and resized copies, share one tile. The tile shows the sharpest and largest of them, with a badge for how many there are. Open the tile to see them all, and use the up and down arrow keys to switch between them.

## Filtering

**Filter** narrows the grid by:

- **Subfolder**, including the folders inside it.
- **File type**.
- **Date**: Today, Past 7 days, Past 28 days, Past year, All, or a custom range.

Filters also apply to search and the map.

## Searching

Once visual search is set up, search finds images by what they show. Type a description, like "sunset over water", and press Enter. Until then, search matches file names. The search options button, at the right of the search bar, switches between the two.

You can also search with an image:

- Paste an image into the window.
- Drop an image anywhere along the top of the window. This works with files, and with images from the grid and the map.
- Choose **Find similar** in the viewer.

Searching with an image shows its 100 closest matches.

## The map

**Map** lays the whole folder out by similarity, so images that look alike sit together. Scroll or pinch to zoom, drag to move, and click an image to open it. When you search, the matches light up and the rest dim.

To search with an image from the map, press and hold it until it lifts, then drag it to the top of the window.

The first layout takes a few seconds. After that, new images are placed next to their nearest neighbours, so the map doesn't rearrange every time you add photos.

## Setting up visual search

Visual search and the map need a model called SigLIP 2. It's a one-time download of about 504 MB on an Apple Silicon Mac, or 690 MB on other computers, and it runs offline after that.

When you choose your first folder, **Set up visual search too** is ticked, so the download starts with the scan. If you skipped it, set it up later from **Info**, from the map, or by choosing **Appearance** in the search options. Once it's set up, every folder you open is prepared for visual search on its own.

Preparing takes a moment per image, and how long a whole folder takes depends mostly on whether Orchard can use the computer's [GPU](#which-gpu-orchard-uses). These rough times come from one Mac and one Intel laptop:

| Computer | 10,000 photos |
| --- | --- |
| Apple Silicon Mac | A few minutes |
| Intel laptop with Windows, on its GPU | About 40 minutes |
| The same laptop, on its CPU | Over an hour |

Before that, Orchard reads each new file and draws its thumbnail, which took about 40 seconds per 1,000 photos on the laptop. You can browse while both run. The newest images are prepared first, so you can search recent photos while the rest are still being prepared. If you quit Orchard, or the computer sleeps, it carries on where it stopped.

## Background work and Info

Background work shows beside the image count: reading new files, downloading the model, and preparing images for visual search. Click it, or the ⓘ button, to open **Info**, which shows how many images and files the folder holds, how long background work has left, and a button to rescan the folder.

You rarely need to rescan by hand. Orchard rescans the folder every minute, so added, changed and removed files show up on their own.

## Supported files

Orchard reads JPEG, PNG, GIF, WebP, BMP, TIFF, HEIC/HEIF and AVIF. Browsers can't show HEIC and TIFF, so the viewer shows a converted JPEG of those, and **Download** still gives you the original.

Orchard skips:

- Hidden files and folders, including the `._` files macOS leaves on external drives.
- Photos libraries, since macOS keeps them closed to other apps. Info says when it finds one. To browse your Apple Photos, [export them to a folder](#apple-photos) first.
- Damaged, empty and very large files, over 300 megapixels. Info lists how many could not be read.

Symlinked folders are followed once, so a link loop can't trap the scan.

## Apple Photos

Orchard can't read a Photos library, so to browse those photos, export them to a folder first:

1. Open Photos and choose **Library** in the sidebar.
2. Select the photos you want, or press Cmd+A for all of them.
3. Choose **File › Export › Export Unmodified Originals**, then **Export**.
4. Choose or make a folder, like `Pictures/Photos export`, and click **Export Originals**.
5. Open that folder in Orchard.

Unmodified originals keep their EXIF dates, so they land in the right month. They don't include edits made in Photos. To get the edited versions, choose **File › Export › Export Photos** instead. The export is a full copy, so it needs as much free space as the photos themselves.

If **Optimize Mac Storage** is on in Photos' iCloud settings, most originals are only in iCloud. Photos downloads them during the export, which can take a long time for a large library. To download them all first, choose **Download Originals to this Mac** in the same settings.

## Where Orchard keeps its data

Orchard keeps its cache, the search model and the list of recent folders in one data folder, never beside your photos:

| System | Data folder |
| --- | --- |
| macOS | `~/Library/Application Support/orchard/` |
| Windows | `%LOCALAPPDATA%\orchard\` |
| Linux and WSL | `~/.local/share/orchard/`, or `$XDG_DATA_HOME/orchard/` if that's set |

If you start Orchard with `--data-dir`, it's that folder instead. The Python packages are separate, in `.venv` inside Orchard's own folder, and take about 250 MB.

### Disk space

Each photo needs a thumbnail, its search vector and a map icon. In tests, that came to 30 to 40 KB for most photos, and about 60 KB for phone photos, so allow about 6 GB per 100,000 photos. The search model adds one copy, shared by every folder. Each HEIC or TIFF photo you open in the viewer also keeps a JPEG up to 4,096 pixels across, so it opens quickly next time.

### Resetting Orchard

Quit Orchard, then delete, inside the data folder:

- `libraries/<id>/` to clear one folder's cache. Its `folder.txt` names the folder it belongs to. Orchard reads the folder again the next time you open it.
- `models/` to download the search model again.
- `recent.json` to clear the list of recent folders.
- The whole data folder to start over.

To reinstall the Python packages, delete `.venv` in Orchard's own folder. The next run installs them again.

### Uninstalling

Quit Orchard, then delete Orchard's own folder, the cloned or unzipped one, and its data folder. On a Mac, also delete `~/Applications/Orchard.app` if you installed it.

The window keeps its page settings, like the theme, in the system web view's storage. On a Mac, the Mac app's are in `~/Library/WebKit/local.orchard.launcher/`.

## Questions and problems

### Orchard says it needs Python 3.12, 3.13 or 3.14

Orchard runs on Python 3.12 to 3.14. Python 3.15 isn't supported yet, since ONNX Runtime, which runs the search model, has no packages for it. You don't need to remove another Python. Install 3.13 beside it, and the launcher finds it:

- On a Mac: `brew install python@3.13`, or the installer from [python.org](https://www.python.org/downloads/).
- On Windows: `winget install Python.Python.3.13`. Then open a new Command Prompt, since one that was already open doesn't see it.
- On Ubuntu 24.04 and later: `sudo apt update && sudo apt install python3 python3-venv`. On older Ubuntu, get `python3.12` from the [deadsnakes PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa).

### Python can't create environments, on Linux

Debian and Ubuntu ship the part of Python that makes environments as a separate package. Install the one Orchard names, for example:

```bash
sudo apt update && sudo apt install python3.12-venv
```

A fresh install, including WSL's, has no package lists yet, so `apt install` fails without `apt update` first.

### Visual search needs the Visual C++ Redistributable, on Windows

ONNX Runtime needs Microsoft's C++ runtime, which Python doesn't include. Browsing works without it, but visual search shows this message. Install it, then restart Orchard:

```bat
winget install Microsoft.VCRedist.2015+.x64
```

On an Arm laptop, use `Microsoft.VCRedist.2015+.arm64`.

### The port is in use

Orchard listens on port 4400. If another program has it, Orchard says so and stops. Quit that program, or start Orchard on another port, like `./orchard --port 4401`, or `orchard.cmd --port 4401` on Windows. The page's saved settings, like the theme, belong to the port, so a new port starts with the defaults.

### The search model won't download

The model goes into `models/` in the [data folder](#where-orchard-keeps-its-data). If the download stops, choose **Try again** in Info, and it carries on where it stopped.

The download comes from huggingface.co. Behind a proxy, set `HTTPS_PROXY` before starting Orchard, and make sure the proxy allows huggingface.co and hf.co:

```bash
HTTPS_PROXY=http://proxy.example.com:8080 ./orchard
```

```bat
set HTTPS_PROXY=http://proxy.example.com:8080
orchard.cmd
```

If the proxy inspects HTTPS with its own certificate, also set `SSL_CERT_FILE` to that certificate's file.

If the model downloaded but won't load, delete `models/`, and Orchard downloads it again. To skip the download on a computer that's offline, copy `models/` from another computer of the same kind, like another Apple Silicon Mac.

### Which GPU Orchard uses

Orchard prepares images on the GPU where it can:

- **Apple Silicon Macs** use Core ML.
- **Windows on x64** uses DirectML, with any DirectX 12 GPU.
- **Everything else**, including Linux, WSL and Windows on Arm, uses the CPU. On Linux, an NVIDIA GPU works through CUDA, as described in [Developing Orchard](development.md#setup).

If the GPU fails, Orchard uses the CPU and prints a warning in the terminal, like "Core ML could not run the search model, so the CPU runs it". On a Mac, the CPU then needs its own copy of part of the model, a further 372 MB download. [How Orchard works](how-it-works.md#visual-search) explains the check it runs first.

### Some photos are missing

Check these, in order:

- **Unsupported files.** Orchard reads only the [formats listed above](#supported-files). RAW files, videos and Live Photo videos aren't shown.
- **Files Orchard can't read.** Info counts damaged, empty and very large files under **Could not be read**, and folders it couldn't open.
- **Hidden files and Photos libraries.** Both are skipped. See [Apple Photos](#apple-photos).
- **Duplicates.** Identical copies show once, and near-duplicates share one tile. Info counts both.
- **Filters.** Info says how many images your filters show.
- **The date.** A photo without EXIF data is dated by when the file last changed, so a copied photo may sit in a later month than you expect.
- **New files.** Orchard rescans every minute. **Rescan now** in Info does it at once.

On a Mac, the first time you open your Desktop, Documents, Downloads or an external drive, macOS asks whether to allow access. If you chose **Don't Allow**, Orchard can't read the folder. Turn it back on in System Settings › Privacy & Security › Files and Folders, for the app you started Orchard from, like Terminal.

### Photos on external, network and cloud drives

The cache stays on your computer. If a drive is unplugged while Orchard is open, it keeps showing the last scan, and the cache is still there when the drive comes back. The cache belongs to the folder's path, so if the drive comes back under another name or drive letter, Orchard treats it as a new folder and reads it again.

The first scan reads every file in full, to recognise copies, so a large folder on a slow USB or network drive takes a while. After that, Orchard only checks each file's size and date every minute. On a slow network share, start Orchard with `--no-watch` to stop that, and use **Rescan now** when you've added photos.

Cloud folders, like iCloud Drive, OneDrive, Dropbox and Google Drive, work best when their files are kept on the computer. A file that's only online is downloaded when Orchard reads it, so the first scan may download the whole folder, or fail to read files that aren't available.

### Using Orchard on two computers

Install Orchard on each computer. Each one keeps its own cache and prepares its own search index, so nothing is shared or synced between them. The photos themselves can live on a shared drive, but keep each computer's data folder on that computer, since its SQLite database isn't safe to share over a network.

### Under WSL

Orchard runs in WSL with its own window, through WSLg. Some things differ from Linux on its own:

- **Show in folder** opens File Explorer, and `--browser` opens your Windows browser.
- Folders under `/mnt/c` work, but scanning them is slower than folders inside WSL.
- The model runs on the CPU, since DirectML isn't available in WSL. Native Windows prepares images faster, on the GPU.

### Reporting a problem

[Open a bug report](https://github.com/chaseleantj/orchard-photos/issues/new/choose) with your system, what you did, and what happened. Include what the terminal printed. The Mac app writes the same output to `/tmp/orchard.log`.
<!-- INTEGRATION: when Info gains Copy diagnostics, say to paste its output here. -->
