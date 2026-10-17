# Using Orchard

This guide covers everything you can do in Orchard once it's running. To install it, see the [README](../README.md).

## Opening a folder

Choose a folder with **Folder**, at the right of the line under the search bar. This opens the system folder dialog. In the browser on Linux, it needs `zenity` or `kdialog`, and in the browser on Windows there is none. You can also type or paste a path, or pick a recent folder. You can also open a folder from the terminal:

```bash
./orchard ~/Pictures
```

On Windows, run `orchard.cmd C:\Users\you\Pictures` instead.

If Orchard is already open, this switches its window to the folder and brings it to the front, instead of opening a second one.

## The window and the browser

Orchard opens in its own window, and closing the window quits it. To use your browser instead, start it with `--browser`:

```bash
./orchard ~/Pictures --browser
```

Orchard is then at http://127.0.0.1:4400, and stops when you press Ctrl+C in the terminal.

The window remembers its size and place, and the page remembers settings like the theme. On a Mac, the Dock app and `./orchard` in a terminal each keep their own, because macOS stores them per app.

On Linux, the window needs GTK's web view for Python, which pip can't install. On Ubuntu and Debian, install it with `sudo apt install python3-gi gir1.2-webkit2-4.1`. Orchard uses these system packages, so they need to match the Python that runs it. That's the case when it's your system's own `python3`. Without them, or without a display, Orchard opens in the browser and says why.

Each folder keeps its own cache, so switching back to a folder you've opened before is quick. If the folder goes away, for example on an unplugged drive, Orchard keeps showing the last scan and tells you the folder is unavailable.

## Browsing

Images are shown newest first, grouped by month. Each photo is dated by when it was taken, from its EXIF data. Images without EXIF data use the date the file was last changed.

The column of years on the right is a timeline of the whole folder. Each year takes up space based on how many images it holds. Click or drag it to jump to a month. When it's focused, you can use these keys:

| Key | Action |
| --- | --- |
| Up / Down arrow | Move one month |
| Page Up / Page Down | Move one year |
| Home / End | Go to the newest or oldest image |

## Viewing an image

Click an image to open it. The viewer shows the file name, date, folder, size and type. **Details** adds the full path, the camera, and any other copies of the file.

From the viewer, you can:

- Find similar images.
- Copy the image (Cmd+C on a Mac, Ctrl+C elsewhere).
- Download the original. In the window, this asks where to save it.
- Show it in Finder, in Explorer on Windows, or in your file manager on Linux.
- Click its folder to show only images from that folder.
- Click the image, or the zoom button, to see it at actual size.

Use the left and right arrow keys to move between images, and Escape to close the viewer.

## Duplicates

Identical files appear once. The viewer lists every place a copy is saved.

Images that look almost the same, like bursts, edits and resized copies, share one tile. The tile shows the sharpest and largest one, with a badge for how many there are. Open the tile to see all of them, and use the up and down arrow keys to switch between them.

## Filtering

**Filter** narrows the grid by:

- **Subfolder**, including the folders inside it.
- **File type**.
- **Date**: Today, Past 7 days, Past 28 days, Past year, All, or a custom range.

Filters also apply to search and the map.

## Searching

Once visual search is set up, search finds images by what they look like. Type a description, like "sunset over water", and press Enter. Until visual search is set up, search matches file names instead. The search options button switches between the two.

You can also search with an image:

- Paste an image into the window.
- Drop an image anywhere along the top of the window. This works with files, images from the grid, and images from the map.
- Choose **Find similar** in the viewer.

Searching with an image shows its 100 closest matches.

## The map

**Map** lays out the whole folder by similarity, so images that look alike sit together. Scroll or pinch to zoom, drag to move, and click an image to open it. When you search, the matches light up and the rest dim.

To search with an image from the map, press and hold it until it lifts, then drag it to the top of the window.

The first layout takes a few seconds. After that, new images are placed next to their nearest neighbours, so the map doesn't rearrange every time you add photos.

## Setting up visual search

Visual search and the map need a model called CLIP. It's a one-time download of about 600 MB, and it runs offline after that.

When you choose your first folder, **Set up visual search too** is ticked, so the download starts with the scan. If you skipped it, you can set it up later from **Info**, from the map, or by choosing **Appearance** in the search options. Once it's set up, every folder you open is prepared for visual search automatically.

## Background work and Library

Background work shows beside the image count: reading new files, downloading the model, and preparing images for visual search. You can search images that are already prepared while the rest are still in progress.

Click the progress, or the ⓘ button, to open **Info**. It shows:

- How many images and files the folder holds, and how long background work has left.
- A button to rescan the folder.

You rarely need to rescan by hand. Orchard rescans the folder every minute, so added, changed and removed files show up on their own.

## Supported files

Orchard reads JPEG, PNG, GIF, WebP, BMP, TIFF, HEIC/HEIF and AVIF. Browsers can't show HEIC and TIFF, so the viewer shows a converted JPEG preview of those. **Download** still gives you the original file.

Orchard skips:

- Hidden files and folders, including the `._` files macOS leaves on external drives.
- Photos libraries, since macOS keeps them closed to other apps. Library tells you when it finds one. To browse your Apple Photos, export them to a folder first.
- Damaged, empty and very large files (over 300 megapixels). These are listed in Library with the reason.

Symlinked folders are followed once, so a link loop can't trap the scan.
