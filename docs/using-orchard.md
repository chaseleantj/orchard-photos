# Using Orchard

This guide covers what you can do in Orchard once it's running. To install it, see the [README](../README.md). It has been tested with folders of up to 25,000 photos.

## Opening a folder

To choose a folder, click the open folder's name, at the right of the line under the search bar. It opens the system folder dialog, or you can type or paste a path, or pick a recent folder. When Orchard runs in your browser, the folder dialog needs `zenity` or `kdialog` on Linux. On Windows there's no dialog in the browser, so type or paste the path.

You can also open a folder from the terminal, with `./orchard ~/Pictures`, or `orchard.cmd C:\Users\you\Pictures` on Windows. If Orchard is already open, this switches its window to the folder and brings it to the front.

Each folder keeps its own cache, so switching back to a folder you've opened before is quick.

## The window and the browser

Orchard opens in its own window, and closing the window quits it. On a Mac, the window remembers its size and place. The page remembers settings like the theme and filters.

To use your browser instead, start Orchard with `--browser`, like `./orchard ~/Pictures --browser`. Orchard is then at http://127.0.0.1:4400, and stops when you press Ctrl+C in the terminal.

On Linux, the window needs the system's GTK packages, `python3-gi` and `gir1.2-webkit2-4.1`. They work with the system's own `python3`. Without them, or without a display, Orchard opens in the browser and says why.

### Under WSL

Orchard runs in WSL with its own window, through WSLg. Some things differ from Linux on its own:

- **Show in folder** opens File Explorer, and `--browser` opens your Windows browser.
- Folders under `/mnt/c` work, but scanning them is slower than folders inside WSL.
- The model runs on the CPU, since DirectML isn't available in WSL. Native Windows prepares images faster, on the GPU.

## The Mac app from a clone

The downloaded Mac app needs nothing more. When you run Orchard from a clone, `scripts/install-app` installs `~/Applications/Orchard.app`, which opens this clone's window from the Dock or Spotlight. It compiles a small launcher with clang, so it needs the Xcode command line tools, which `xcode-select --install` installs. The first start sets things up, which takes about a minute. If the clone is in your Desktop or Documents folder, macOS asks whether Orchard may open it, and may ask again after you reinstall the app. If Orchard can't start, the app shows the end of its log, `~/Library/Logs/Orchard.log`.

The app finds Python the way your terminal did when you ran `scripts/install-app`, so run it again if you install Python somewhere new. With Python from Homebrew or python.org, the window shows in the Dock as Orchard. With other Pythons, like pyenv's, it shows as Python.

## Browsing

Images are shown newest first, grouped by month. A photo is dated by when it was taken, from its EXIF data, the details a camera saves inside the file. Images without EXIF data use the date the file was last changed.

The column of years on the right is a timeline of the whole folder, where each year takes space in proportion to its images. Click or drag it to jump to a month. When it's focused, you can use these keys:

| Key | Action |
| --- | --- |
| Up / Down arrow | Move one month |
| Page Up / Page Down | Move one year |
| Home / End | Go to the newest or oldest image |

## Viewing an image

Click an image to open it. The viewer shows the file name, date, folder, size and type. **Details** adds the full path, the camera, and any other copies of the file.

The viewer's buttons are labelled:

- **Find similar** searches with the image.
- **Copy image** copies it. Cmd+C on a Mac, or Ctrl+C elsewhere, does the same.
- **Download original** saves the file. In the window, this asks where to save it.
- **Show in Finder**, or **Show in folder** on Windows and Linux, opens the folder that holds it.

Click its folder to show only images from that folder. Click the image, or the zoom button, to see it at actual size.

Use the left and right arrow keys to move between images, and Escape to close the viewer.

## Duplicates

Identical files appear once, and the viewer lists every place a copy is saved.

Images that look almost the same, like bursts, edits and resized copies, share one tile. Images without camera details, like screenshots and renders, share one only when their pixels match too, so different screens of one app stay apart. The tile shows the sharpest and largest of them, with a badge for how many there are. Open the tile to see them all, and use the up and down arrow keys to switch between them.

## Filtering

**Filter** narrows the grid by:

- **Subfolder**, including the folders inside it.
- **File type**.
- **Date**: Today, Past 7 days, Past 28 days, Past year, All, or a custom range.

Filters also apply to search and the map.

## Searching

Once visual search is set up, search finds images by what they show. Type a description, like "sunset over water", and press Enter. Until then, search matches file names. The search options button, at the right of the search bar, switches between **Appearance** and **File name**.

Press / to go to the search bar from the grid, the map or the viewer. An open viewer or panel closes first. Cmd+K on a Mac, or Ctrl+K elsewhere, does the same.

Cmd+Z, or Ctrl+Z, goes back to the previous search, and Cmd+Shift+Z, or Ctrl+Shift+Z, goes forward again. Clearing a search counts as a step. While you are typing in the search bar, the keys undo your typing first.

You can also search with an image:

- Paste an image into the window.
- Drop an image anywhere along the top of the window. This works with files, and with images from the grid and the map.
- Choose **Find similar** in the viewer.

A search shows only real matches, closest first, so the count depends on what the folder holds. If nothing in the folder fits a description, the search says so instead of showing the nearest misses.

## The map

**Map** lays the whole folder out by similarity, so images that look alike sit together. It shows the newest 25,000 images that match your filters, so in a larger folder, filter by date or subfolder to reach the rest. Scroll or pinch to zoom, drag to move, and click an image to open it. When you search, the matches light up and the rest dim.

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

### Which GPU Orchard uses

Orchard prepares images on the GPU where it can:

- **Apple Silicon Macs** use Core ML.
- **Windows on x64** uses DirectML, with any DirectX 12 GPU.
- **Everything else**, including Linux, WSL and Windows on Arm, uses the CPU. On Linux, an NVIDIA GPU works through CUDA, as described in [Developing Orchard](development.md#setup).

If the GPU fails, Orchard uses the CPU and prints a warning in the terminal, like "Core ML could not run the search model, so the CPU runs it". On a Mac, Orchard then downloads a 372 MB version of the image model for the CPU. [How Orchard works](how-it-works.md#visual-search) explains the check it runs first.

## Background work and Info

Background work shows beside the image count: reading new files, downloading the model, and preparing images for visual search. Click it, or the ⓘ button, to open **Info**, which shows how many images and files the folder holds, how long background work has left, and a button to rescan the folder.

At the bottom, Info shows Orchard's version, and:

- **Check for updates on GitHub**, which is off until you turn it on. Once on, Orchard asks GitHub once a day whether a newer version is out, and Info links to it. Nothing about your images is sent.
- **Copy diagnostics**, which copies a short report for a bug report: versions, the search engine, counts and the last error, without file names or folders.

You rarely need to rescan by hand. Orchard rescans the folder every minute, so added, changed and removed files show up on their own. A folder that's slow to list, like one on a network drive, is rechecked less often. **Rescan now** also tries again the files that couldn't be read.

## Supported files

Orchard reads JPEG, PNG, GIF, WebP, BMP, TIFF, HEIC/HEIF and AVIF. Browsers can't show HEIC and TIFF, so the viewer shows a converted JPEG of those, and **Download** still gives you the original.

Orchard skips:

- RAW photos and videos. Info counts them, and says they aren't shown yet.
- Hidden files and folders, including the `._` files macOS leaves on external drives.
- Photos libraries, since macOS keeps them closed to other apps. Info says when it finds one. To browse your Apple Photos, [export them to a folder](#apple-photos) first.
- Damaged, empty and very large files, over 300 megapixels. Info lists how many could not be read.

## Apple Photos

On a Mac, Orchard can show and search your Photos library. Choose **Photos library** on the welcome screen, or in the panel under the folder name. The first time, macOS asks whether Orchard may access your photos. To change your answer later, use **System Settings › Privacy & Security › Photos**.

- Orchard reads each photo through Photos, with your edits, and never changes your library.
- Hidden photos and videos are skipped.
- Photos has no folders, so there's no folder filter. Searching file names uses each photo's original name.
- **Show in Photos** opens the photo in Photos, in place of Show in Finder. The first time, macOS asks whether Orchard may control Photos. **Download original** saves the file.
- Photos kept only in iCloud, when **Optimize Mac Storage** is on, can't be read, and Info counts them under **Could not be read**. To include them, choose **Download Originals to this Mac** in **Photos › Settings › iCloud**, then **Rescan now** in Info.
- Orchard opens the library Photos uses as its System Photo Library. To browse another one, make it the system library in **Photos › Settings › General**.
- Started from Terminal, Orchard can't ask for access, since macOS only asks apps that say why they want it. Open Orchard from its app, or from the one [`scripts/install-app`](#the-mac-app-from-a-clone) makes.

On another computer, export the photos to a folder instead: in Photos, select them, choose **File › Export › Export Unmodified Originals**, and open that folder in Orchard. Unmodified originals keep their dates but not your edits. **File › Export › Export Photos** includes the edits.

## Where Orchard keeps its data

Orchard keeps its cache, the search model and the list of recent folders in one data folder, never beside your photos:

| System | Data folder |
| --- | --- |
| macOS | `~/Library/Application Support/orchard/` |
| Windows | `%LOCALAPPDATA%\orchard\` |
| Linux and WSL | `~/.local/share/orchard/`, or `$XDG_DATA_HOME/orchard/` if that's set |

If you start Orchard with `--data-dir`, it's that folder instead. Run from a clone, the Python packages are separate, in `.venv` inside the clone, and take about 250 MB. The downloaded apps carry their own.

### Disk space

Each photo needs a thumbnail, its search vector and a map icon. Allow about 600 MB per 10,000 photos, or 1.5 GB for 25,000. The search model adds one copy, shared by every folder. Each HEIC or TIFF photo you open in the viewer also keeps a JPEG up to 4,096 pixels across, so it opens quickly next time.

### Resetting Orchard

Quit Orchard, then delete, inside the data folder:

- `libraries/<id>/` to clear one folder's cache. Its `folder.txt` names the folder it belongs to. Orchard reads the folder again the next time you open it.
- `models/` to download the search model again.
- `recent.json` to clear the list of recent folders.
- The whole data folder to start over.

To reinstall the Python packages of a clone, delete its `.venv`. The next run installs them again.

### Uninstalling

Quit Orchard, then delete the app, or Orchard's own folder if you cloned it, and its data folder. On a Mac, delete `Orchard.app` from Applications, and for a clone, also `~/Applications/Orchard.app` if you installed it. On Windows, delete the extracted `Orchard` folder.

If something goes wrong, see [Questions and problems](questions-and-problems.md).
