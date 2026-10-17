# Developing Orchard

This guide is for working on Orchard's code. To see how the parts fit together first, read [How Orchard works](how-it-works.md).

## Setup

Orchard needs Python 3.12 to 3.14, since ONNX Runtime has no packages for 3.15 yet. Running `./orchard`, or `orchard.cmd` on Windows, once installs the Python packages into `.venv`. It makes a fresh `.venv` whenever `requirements.txt` changes. To do it by hand:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

On Linux, `./orchard` makes `.venv` with `--system-site-packages`, so the window can use the distribution's GTK bindings, `python3-gi` and `gir1.2-webkit2-4.1`, which pip can't install.

On Windows, the environment's Python is `.venv\Scripts\python.exe`, and `requirements.txt` installs `onnxruntime-directml` in place of `onnxruntime` on x64.

To use an NVIDIA GPU on Linux, install `onnxruntime-gpu` in place of `onnxruntime` in `.venv`. Install it again after `requirements.txt` changes, since `./orchard` then makes a fresh `.venv`.

The built page in `dist/` is committed, so running Orchard needs no Node. To work on the frontend, you need Node 18 or later:

```bash
npm ci
npm run build
```

Commit `dist/` with your change, since CI fails when it doesn't match the sources. Once `node_modules` exists, `./orchard` rebuilds the page when its sources change. `orchard.cmd` doesn't, so run `npm run build` yourself on Windows.

## Running with live reload

Run the server and the Vite dev server in two terminals:

```bash
.venv/bin/python -m server.api ~/Pictures
```

```bash
npm run dev
```

Then open http://127.0.0.1:5173. Vite reloads the page when you change the frontend, and passes `/api` requests to the server on port 4400. Restart the server after changing Python code.

The server takes these options:

| Option | Description |
| --- | --- |
| `folder` | The folder to open. Defaults to the last one opened. |
| `--port` | The port to listen on. Defaults to 4400. |
| `--data-dir` | Where to keep the cache and model. |
| `--no-watch` | Only scan when asked, instead of every minute. |
| `--window` | Open in its own window, and quit when it closes. `./orchard` passes this. |
| `--browser` | Open the page in the browser instead. The last of `--window` and `--browser` wins. |

## Project layout

| Path | Contents |
| --- | --- |
| `server/api.py` | The HTTP server, API routes and command line. |
| `server/window.py` | The native window, through pywebview, and its folder dialog. |
| `server/library.py` | One folder's library, and the queries the API answers from it. |
| `server/cache.py` | Where a folder's cache keeps its SQLite index, thumbnails and previews. |
| `server/scanner.py` | Finds image files, reads metadata and draws thumbnails. |
| `server/semantic.py` | Downloads and runs SigLIP 2 with ONNX Runtime, and stores each folder's vectors. |
| `server/groups.py` | Groups near-duplicates. |
| `server/layout.py` | Lays out the map with UMAP, written in NumPy. |
| `server/atlas.py` | Packs map icons into sheets. |
| `server/parity-vector.npy` | The vector the CPU gives for the test image that a GPU must match. |
| `web/src/` | The React frontend. `App.tsx` is the entry point, and `mapEngine.ts` draws the map. |
| `dist/` | The built page. |
| `tests/` | Python tests, one file per server module. |
| `orchard`, `orchard.cmd` | The launchers for macOS and Linux, and for Windows. They find a supported Python, install the packages, and start the server with `--window`. |
| `scripts/install-app` | Builds the Mac app that opens Orchard from the Dock. |
| `scripts/smoke-test` | Installs and starts Orchard on a few generated images, and checks the API. |
| `scripts/build-coreml-model` | Builds the Core ML image encoder and the parity vector. |
| `app.json` | The app's name, command name and ports. |
| `.github/workflows/ci.yml` | Runs the tests and the smoke test on Ubuntu, macOS and Windows, and the linters and UI test on Ubuntu. |

## Tests

Run the Python tests, and the linters and TypeScript check:

```bash
npm test
npm run lint
```

On Windows, run `.venv\Scripts\python -m unittest discover -s tests` instead of `npm test`. Tests that need symlinks or folder permissions are skipped there. The tests never download the model. They replace it with fixed vectors.

To lint, install ruff with `.venv/bin/pip install -r requirements-dev.txt`, again after `requirements.txt` changes, since `npm run lint` runs it with ESLint. `npm run test:ui` opens a few generated images in the built page with headless Chromium, which `npx playwright install chromium` installs once.

The smoke test runs Orchard the way a user does. It starts `./orchard --browser`, or `orchard.cmd` on Windows, on a few generated images, with a temporary cache and port 4499, and checks that the API lists them and the page loads. On a fresh clone, it covers the first-run install too. Add `--visual` to also download the model and check that a search finds the right image:

```bash
scripts/smoke-test --visual
```

On Windows, run `python scripts\smoke-test`. CI runs the Python tests and the smoke test on Ubuntu, macOS and Windows. On Ubuntu, it also runs the linters with `npm run lint`, the UI test with `npm run test:ui`, and checks that `dist/` matches the sources. `npm run lint` runs ruff from `.venv/bin`, so on Windows, leave linting to CI. To run the visual check in CI, start the workflow by hand with **visual** ticked.

## Building the downloads

The Mac DMG and the Windows zip carry their own Python, with the packages installed, so they need no Python or terminal. `scripts/build-app` builds the one for the computer it runs on, an Apple Silicon Mac or Windows x64, into `build/`. Run it with Python 3.13, the version inside the app, since pip installs the packages for the Python that runs it:

```bash
python3.13 scripts/build-app --version 0.1.0
```

- **macOS** gives `build/Orchard-mac-arm64.dmg`, holding `Orchard.app`. Its executable is a small launcher, compiled from `scripts/app/macos-launcher.c` with the Xcode command line tools. It runs python-build-standalone's Python from inside `Contents/MacOS`, so its window shows under Orchard's name and icon. A compiled launcher, unlike a script, lets macOS ask to allow Desktop and Documents and remember the answer. The app is signed ad hoc, so macOS asks once for Open Anyway, and each new build counts as a new app that asks for folders again.
- **Windows** gives `build/Orchard-windows-x64.zip`, holding an `Orchard` folder. `Orchard.exe` is a small launcher, compiled from `scripts/app/windows-launcher.cs` with the .NET compiler that comes with Windows. It runs python.org's embeddable Python in `runtime\`.

Both launchers, in `scripts/app/`, write Python's output to a log, `~/Library/Logs/Orchard.log` or `%TEMP%\Orchard.log`, and show its end if Orchard stops without opening. To test a build the way CI does, point the smoke test at its launcher:

```bash
scripts/smoke-test --launcher build/dmg/Orchard.app/Contents/MacOS/Orchard
```

Pushing a tag like `v0.1.0` runs `.github/workflows/release.yml`. It builds both on GitHub's runners, copies each out of its DMG or zip, runs the smoke test with `--visual` on it, and attaches both to a draft release to check and publish. Started by hand, it keeps them as workflow artifacts instead. The asset names carry no version, so `releases/latest/download/Orchard-mac-arm64.dmg` always links the newest. On Linux, people run `./orchard` from a clone.

When renaming, the launchers and the app's bundle identifier in `scripts/build-app` carry the name too.

## The Core ML model

On an Apple Silicon Mac, Orchard downloads its image encoder from its own Hugging Face repository. `scripts/build-coreml-model` makes that file from the ONNX export's pinned revision, and prints its SHA-256. The same input always gives the same file. It needs the `onnx` package, which the app doesn't:

```bash
.venv/bin/pip install onnx==1.23.2
.venv/bin/python scripts/build-coreml-model build/
```

To publish a new version, upload the file to `CORE_ML_REPOSITORY` in `server/semantic.py`, then set `CORE_ML_REVISION` to the upload's commit, and `CORE_ML_SHA256` and its entry in `SIZES` to what the script printed. If the model or the test image changes, add `--parity` to also write `server/parity-vector.npy`.

To try the Core ML path without the download, put the built file where the download would go, in the data folder:

```text
models/models--<owner>--<name>/snapshots/<CORE_ML_REVISION>/vision_model_fp16_coreml.onnx
```

Orchard logs a warning when it falls back to the CPU.

## Renaming

The app's name, command name and ports live in `app.json`, which the window title, wordmark, messages, data folder and browser storage keys read. These carry the name directly, and need to change by hand:

- The logo, in `web/src/Logo.tsx`, `public/` and `docs/`, and the app icons in `assets/`.
- The package name in `package.json`.
- The `orchard` and `orchard.cmd` launchers.
- The Mac app in `scripts/install-app`: its name, bundle identifier and icon.
- `server/window.py`: the `ORCHARD_BUNDLE` variable the Mac app sets, and the icon paths.
- The docs.
