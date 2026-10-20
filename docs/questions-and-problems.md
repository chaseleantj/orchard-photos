# Questions and problems

Answers to common problems with installing Orchard, the search model, and finding your photos. For how to use Orchard, see [Using Orchard](using-orchard.md).

## Orchard says it needs Python 3.12, 3.13 or 3.14

Orchard runs on Python 3.12 to 3.14. Python 3.15 isn't supported yet, since the search model's library doesn't support it. You don't need to remove another Python. Install 3.13 beside it, and the launcher finds it:

- On a Mac: `brew install python@3.13`, or the installer from [python.org](https://www.python.org/downloads/).
- On Windows: `winget install Python.Python.3.13`. Then open a new Command Prompt, since one that was already open doesn't see it.
- On Ubuntu 24.04 and later: `sudo apt update && sudo apt install python3 python3-venv`. On older Ubuntu, get `python3.12` from the [deadsnakes PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa).

## Orchard asks you to install python3-venv, on Linux

On Debian and Ubuntu, Orchard needs one more package to install itself. Install the one Orchard names, for example:

```bash
sudo apt update && sudo apt install python3.12-venv
```

A fresh install, including WSL's, has no package lists yet, so `apt install` fails without `apt update` first.

## Visual search needs the Visual C++ Redistributable, on Windows

Visual search needs Microsoft's C++ runtime, which Python doesn't include. Browsing works without it, but visual search shows this message. Install it, then restart Orchard:

```bat
winget install Microsoft.VCRedist.2015+.x64
```

On an Arm laptop, use `Microsoft.VCRedist.2015+.arm64`.

## The port is in use

Orchard listens on port 4400. If another program has it, Orchard says so and stops. Quit that program, or start Orchard on another port, like `./orchard --port 4401`, or `orchard.cmd --port 4401` on Windows. The page's saved settings, like the theme, belong to the port, so a new port starts with the defaults.

## The search model won't download

The model goes into `models/` in the [data folder](using-orchard.md#where-orchard-keeps-its-data). If the download stops, choose **Try again** in Info, and it carries on where it stopped.

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

## Some photos are missing

Check these, in order:

- **Unsupported files.** Orchard reads only the [supported formats](using-orchard.md#supported-files). RAW files, videos and Live Photo videos aren't shown, and Info counts them.
- **Files Orchard can't read.** Info counts damaged, empty and very large files under **Could not be read**, and folders it couldn't open. **Rescan now** tries those files again, for when you've fixed their permissions or downloaded them.
- **Hidden files and Photos libraries.** Both are skipped inside a folder. To browse your Photos library, see [Apple Photos](using-orchard.md#apple-photos).
- **Duplicates.** Identical copies show once, and near-duplicates share one tile. Info counts both.
- **Filters.** Info says how many images your filters show.
- **The date.** A photo without EXIF data is dated by when the file last changed, so a copied photo may sit in a later month than you expect.
- **New files.** Orchard rescans every minute. **Rescan now** in Info does it at once.

On a Mac, a folder macOS keeps Orchard out of can't be read at all. See [Orchard says macOS is blocking access](#orchard-says-macos-is-blocking-access).

## Orchard says macOS is blocking access

The first time Orchard opens your Desktop, Documents, Downloads or an external drive, macOS asks whether to allow it. If you chose **Don't Allow**, Orchard says macOS is blocking access to the folder. If the clone itself is in one of those folders, the Mac app from `scripts/install-app` instead stops with "Operation not permitted" in its log.

To allow it, open **System Settings › Privacy & Security › Files & Folders**, and turn on the folder for Orchard, or for the app you started Orchard from, like Terminal. If it isn't listed there, add it to **Full Disk Access** instead. Then choose **Rescan now** in Info, or open Orchard again. Each update of the downloaded app counts as a new app to macOS, so it may ask again.

## Orchard says macOS hasn't allowed it to read your Photos library

macOS asks once whether Orchard may access your photos. If you chose **Don't Allow**, open **System Settings › Privacy & Security › Photos**, turn on Orchard, then choose **Rescan now** in Info. Started from Terminal, Orchard can't ask at all, so open it from its app instead. See [Apple Photos](using-orchard.md#apple-photos).

## Orchard says "This app is available only on this computer"

The server refused the request. It accepts requests only from Orchard's own page and from programs on the computer, so it refuses a page opened through another address, like a proxy, a tunnel, another hostname or another port. Use Orchard's own window, or open http://127.0.0.1:4400, or the port you chose with `--port`.

The terminal, or the app's log, shows a line starting with `Refused` for each refused request, with the Host, Origin and `Sec-Fetch-Site` it came with. Include it if you report the problem.

## Photos on external, network and cloud drives

The cache stays on your computer. If a drive is unplugged while Orchard is open, it keeps showing the last scan, and the cache is still there when the drive comes back. If the drive or network drops partway through a scan, Orchard stops reading, and carries on from where it was once the folder is back. Info counts any files it couldn't reach, and each scan tries them again. The cache belongs to the folder's path, so if the drive comes back under another name or drive letter, Orchard treats it as a new folder and reads it again.

The first scan reads every file in full, to recognise copies, so a large folder on a slow USB or network drive takes a while. After that, Orchard only checks each file's size and date every minute. On a slow network share, start Orchard with `--no-watch` to stop that, and use **Rescan now** when you've added photos, or to carry on a scan the network interrupted.

Cloud folders, like iCloud Drive, OneDrive, Dropbox and Google Drive, work best when their files are kept on the computer. A file that's only online is downloaded when Orchard reads it, so the first scan may download the whole folder, or fail to read files that aren't available.

## Using Orchard on two computers

Install Orchard on each computer. Each one keeps its own cache and prepares its own search index, so nothing is shared or synced between them. The photos themselves can live on a shared drive, but keep each computer's data folder on that computer, since its SQLite database isn't safe to share over a network.

## Reporting a problem

[Open a bug report](https://github.com/chaseleantj/orchard-photos/issues/new/choose) with your system, what you did, and what happened. In Info, click **Copy diagnostics**, and paste the report into the form. It names versions, counts and the last error, but no file names or folders.

Include what the terminal printed, too. The Mac apps write it to `~/Library/Logs/Orchard.log`, and the Windows app to `%TEMP%\Orchard.log`.
