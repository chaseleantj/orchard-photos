<picture><source media="(prefers-color-scheme: dark)" srcset="docs/logo-inverted.svg"><img src="docs/logo.svg" alt="Orchard Photos" height="56"></picture>

<p align="center"><img src="docs/hero.gif" width="800" alt="Orchard Photos: a photo of the Colosseum is dragged onto the search bar and similar photos of Rome fill the grid; typing &quot;a bowl of noodles&quot; brings up photos of noodles; the map then lights up those noodle photos, grouped together among similar food."></p>

Orchard is a free app for finding photos on your computer. Open a folder, and Orchard shows every photo in it as one timeline. To find a photo, describe it, like "dog on a beach", or drop in a similar photo.

Most photo apps with this kind of search upload your library to a server. Orchard keeps everything on your computer: the search runs locally, nothing is uploaded, and Orchard never moves or changes your files.

## What you can do

- **Search by describing a photo**, in English or another language.
- **Find similar photos** by dropping one onto the search bar.
- **See your photos on a map**, where photos that look alike sit together.
- **Open your Apple Photos library** on a Mac, without exporting it.
- **Filter** by subfolder, file type and date.
- **See fewer duplicates.** Copies, bursts and edits of the same photo share one tile.

## Download

| Computer | Download |
| --- | --- |
| Mac with Apple Silicon (M1 or later), macOS 14 or later | [Orchard-mac-arm64.dmg](https://github.com/chaseleantj/orchard-photos/releases/latest/download/Orchard-mac-arm64.dmg) |
| Windows 10 or 11 | [Orchard-windows-x64.zip](https://github.com/chaseleantj/orchard-photos/releases/latest/download/Orchard-windows-x64.zip) |

**On a Mac,** open the DMG and drag Orchard to Applications. Orchard isn't signed by Apple yet, so the first time you open it, macOS says it can't verify it:

1. Click **Done**.
2. Open **System Settings › Privacy & Security**, and click **Open Anyway** next to the message about Orchard.
3. Click **Open Anyway** again, and enter your password.

**On Windows,** extract the zip, then open `Orchard.exe` in the `Orchard` folder. If Windows says it protected your PC, click **More info**, then **Run anyway**.

When you open your first folder, Orchard offers to set up search. This downloads a search model once, about 500 MB on a Mac and 700 MB on Windows. After that, Orchard works offline.

On Linux or an Intel Mac, see [Running from source](docs/running-from-source.md).

## Privacy

Orchard only goes online to download the search model, and to check for updates if you turn that on in **Info**. Your photos never leave your computer, and websites you visit can't reach them.

## More help

- [Using Orchard](docs/using-orchard.md): everything the app can do.
- [Questions and problems](docs/questions-and-problems.md): if something doesn't work.
- [How Orchard works](docs/how-it-works.md) and [Developing Orchard](docs/development.md), for the technical details.

## License

[MIT](LICENSE)
