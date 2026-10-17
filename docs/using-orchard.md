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

Visual search and the map need a model called SigLIP 2. It's a one-time download of about 500 MB on an Apple Silicon Mac, or 690 MB on other computers, and it runs offline after that.

When you choose your first folder, **Set up visual search too** is ticked, so the download starts with the scan. If you skipped it, set it up later from **Info**, from the map, or by choosing **Appearance** in the search options. Once it's set up, every folder you open is prepared for visual search on its own.

Preparing takes a moment per image. On an Apple Silicon Mac, a folder of 20,000 images is ready in a few minutes. On a computer that prepares images on its CPU, it takes from 20 minutes to a few hours. The newest images are prepared first, so you can search recent photos while the rest are still being prepared.

## Background work and Info

Background work shows beside the image count: reading new files, downloading the model, and preparing images for visual search. Click it, or the ⓘ button, to open **Info**, which shows how many images and files the folder holds, how long background work has left, and a button to rescan the folder.

You rarely need to rescan by hand. Orchard rescans the folder every minute, so added, changed and removed files show up on their own.

## Supported files

Orchard reads JPEG, PNG, GIF, WebP, BMP, TIFF, HEIC/HEIF and AVIF. Browsers can't show HEIC and TIFF, so the viewer shows a converted JPEG of those, and **Download** still gives you the original.

Orchard skips:

- Hidden files and folders, including the `._` files macOS leaves on external drives.
- Photos libraries, since macOS keeps them closed to other apps. Info says when it finds one. To browse your Apple Photos, export them to a folder first.
- Damaged, empty and very large files, over 300 megapixels. Info lists how many could not be read.

Symlinked folders are followed once, so a link loop can't trap the scan.
