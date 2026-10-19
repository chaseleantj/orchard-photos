# Running from source

The downloads cover Apple Silicon Macs and Windows on x64. On Linux, Intel Macs and Arm Windows, run Orchard from a clone instead. It needs Python 3.12, 3.13 or 3.14.

The first run installs Orchard's Python packages into a `.venv` folder beside the code, which takes a minute or two. Then Orchard opens in its own window.

## macOS

```bash
git clone https://github.com/chaseleantj/orchard-photos.git
cd orchard-photos
./orchard ~/Pictures
```

If your Python is too old, `./orchard` says so, and how to get a supported one, like `brew install python@3.13`. To open the clone from the Dock or Spotlight, see [The Mac app from a clone](using-orchard.md#the-mac-app-from-a-clone).

## Windows

In Command Prompt or PowerShell, install Python and the Microsoft Visual C++ Redistributable, which visual search needs:

```bat
winget install Python.Python.3.13
winget install Microsoft.VCRedist.2015+.x64
```

On an Arm laptop, like a Snapdragon one, use `Microsoft.VCRedist.2015+.arm64` instead. Then open a new Command Prompt, so it sees the new Python, and clone Orchard:

```bat
git clone https://github.com/chaseleantj/orchard-photos.git
cd orchard-photos
orchard.cmd C:\Users\you\Pictures
```

You can also double-click `orchard.cmd`. If you downloaded a zip instead of cloning, right-click it, choose Properties, then Unblock before extracting it.

## Linux

Python needs its venv package, and the window needs GTK's web view for Python, which pip can't install. On Ubuntu and Debian, including WSL:

```bash
sudo apt update && sudo apt install python3-venv python3-gi gir1.2-webkit2-4.1
git clone https://github.com/chaseleantj/orchard-photos.git
cd orchard-photos
./orchard ~/Pictures
```

Without the GTK packages, Orchard opens in your browser instead.

## Options

- Run `./orchard` with no folder to reopen the last one. Run it with a folder while Orchard is open to switch the window to that folder.
- Add `--browser` to use your browser instead of a window. Orchard is then at http://127.0.0.1:4400.
- Close the window, or press Ctrl+C in the terminal, to quit.

When run from a clone, Orchard also goes online for pip to install its Python packages, on the first run and after an update changes them.

If a step fails, see [Questions and problems](questions-and-problems.md).
