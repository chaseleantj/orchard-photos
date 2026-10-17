<picture><source media="(prefers-color-scheme: dark)" srcset="docs/logo-inverted.svg"><img src="docs/logo.svg" alt="Orchard Photos" height="56"></picture>

<!-- HERO: a screenshot or GIF of a described search, a dropped image and the map goes here, like
<p><img src="docs/hero.gif" alt="Searching for &quot;dog on a beach&quot; in Orchard" width="800"></p>
-->

Orchard Photos is a photo browser that runs entirely on your computer. Point it at a folder, and it shows every image inside, subfolders included, as one timeline you can filter and search. You can find a photo by describing it, like "dog on a beach", or by showing it a similar image.

Most photo apps with this kind of search upload your library to a server. Orchard keeps everything local: the search model runs on your computer, nothing is uploaded, and your files are only ever read, never moved or changed.

Orchard is a small Python server with a React page, shown in its own window. The server scans the folder, makes thumbnails, and runs [SigLIP 2](https://huggingface.co/google/siglip2-base-patch16-256), a model that turns images and text into vectors that sit close together when their meaning is similar. A search compares the vector of your description, or of your example image, with every image's.

## Quick start

The downloads bring their own Python, so they need no setup:

| System | Download |
| --- | --- |
| Mac with Apple Silicon, macOS 14 or later | [Orchard-mac-arm64.dmg](https://github.com/chaseleantj/orchard-photos/releases/latest/download/Orchard-mac-arm64.dmg) |
| Windows 10 or 11, x64 | [Orchard-windows-x64.zip](https://github.com/chaseleantj/orchard-photos/releases/latest/download/Orchard-windows-x64.zip) |

On Linux and Intel Macs, run Orchard from a clone, which works on macOS, Windows and Linux with Python 3.12, 3.13 or 3.14. If a step fails, see [Questions and problems](docs/questions-and-problems.md).

### Installing the Mac app

Open the DMG and drag Orchard to Applications. Orchard isn't signed by Apple yet, so the first time you open it, macOS says it can't verify it:

1. Click **Done**.
2. Open **System Settings › Privacy & Security**, and click **Open Anyway** next to the message about Orchard.
3. Click **Open Anyway** again when macOS asks, and enter your password.

You can instead run `xattr -dr com.apple.quarantine /Applications/Orchard.app` in Terminal before opening it. The first time you open a folder in your Desktop or Documents, macOS asks whether Orchard may open it, and it may ask again after an update.

### Installing on Windows

Extract the zip, then open `Orchard.exe` in the `Orchard` folder. Windows may say it protected your PC. Click **More info**, then **Run anyway**.

### Running from source on macOS

```bash
git clone https://github.com/chaseleantj/orchard-photos.git
cd orchard-photos
./orchard ~/Pictures
```

If your Python is too old, `./orchard` says so, and how to get a supported one, like `brew install python@3.13`. To open the clone from the Dock or Spotlight, run `scripts/install-app` once. It installs `~/Applications/Orchard.app`, and needs the Xcode command line tools, which `xcode-select --install` installs.

### Running from source on Windows

In Command Prompt or PowerShell, install Python and the Microsoft Visual C++ Redistributable, which visual search needs:

```bat
winget install Python.Python.3.13
winget install Microsoft.VCRedist.2015+.x64
```

On an Arm laptop, like a Snapdragon one, use `Microsoft.VCRedist.2015+.arm64` instead. Then open a new Command Prompt, so it sees the new Python, and clone or download Orchard:

```bat
git clone https://github.com/chaseleantj/orchard-photos.git
cd orchard-photos
orchard.cmd C:\Users\you\Pictures
```

You can also double-click `orchard.cmd`. If you downloaded a zip, right-click it, choose Properties, then Unblock before extracting it.

### Running from source on Linux

Python needs its venv package, and the window needs GTK's web view for Python, which pip can't install. On Ubuntu and Debian, including WSL:

```bash
sudo apt update && sudo apt install python3-venv python3-gi gir1.2-webkit2-4.1
git clone https://github.com/chaseleantj/orchard-photos.git
cd orchard-photos
./orchard ~/Pictures
```

Without the GTK packages, Orchard opens in your browser instead.

## Using Orchard

The first run from a clone installs the Python packages into a `.venv` folder beside the code, which takes a minute or two. Then Orchard opens in its own window. Close the window, or press Ctrl+C in the terminal, to quit.

- Run `./orchard` with no folder to reopen the last one. Run it with a folder while Orchard is open to switch the window to that folder.
- Add `--browser` to use your browser instead of a window. Orchard is then at http://127.0.0.1:4400.
- Images are sorted newest first, by the date they were taken. **Filter** narrows them by subfolder, file type and date.
- Identical files show once, and bursts, edits and resized copies share one tile.
- **Map** lays the whole folder out by similarity, so look-alike images sit together. It shows the newest 25,000 images, and filters reach the rest.

Visual search and the map need the search model, a one-time download of about 504 MB on an Apple Silicon Mac, or 690 MB on other computers. Orchard offers to set it up when you open your first folder. Until then, the search bar matches file names. Orchard has been tested with libraries of up to 25,000 photos.

## Privacy

Orchard only goes online to download the search model from Hugging Face once, and, when run from a clone, for pip to install its Python packages on the first run and after an update changes them. After that, it works offline. If you turn on **Check for updates** in Info, it also asks api.github.com once a day whether a newer version is out. That check is off unless you turn it on. Orchard's cache stays in a [data folder](docs/using-orchard.md#where-orchard-keeps-its-data) on your computer.

The server listens only on this computer, and accepts requests only from Orchard's own page and from programs on the computer, so a website you visit can't read your photos. It won't work through a proxy, so don't expose it through one or a tunnel. [SECURITY.md](SECURITY.md) says how to report a vulnerability.

## Documentation

- [Using Orchard](docs/using-orchard.md): browsing, search, the map, supported files, Apple Photos, and where Orchard keeps its data.
- [Questions and problems](docs/questions-and-problems.md): installing, the search model, missing photos, drives, and reporting a bug.
- [How Orchard works](docs/how-it-works.md): scanning, visual search, near-duplicate grouping, the map, and where data lives.
- [Developing Orchard](docs/development.md): setup, live reload, project layout and tests. To send a change, see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
