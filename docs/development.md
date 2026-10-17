# Developing Orchard

This guide is for working on Orchard's code. To understand how the parts fit together first, read [How Orchard works](how-it-works.md).

## Setup

Orchard runs on macOS, Linux and Windows, and needs Python 3.12 to 3.14. ONNX Runtime has no packages for 3.15 yet. Running `./orchard`, or `orchard.cmd` on Windows, once installs the Python packages. To do it by hand:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

On Linux, `./orchard` makes `.venv` with `--system-site-packages`, so the window can use the distribution's GTK bindings (`python3-gi` and `gir1.2-webkit2-4.1`), which pip can't install. The pinned packages in `requirements.txt` install into `.venv`, but pip may reuse a distribution package for one of their unpinned dependencies.

On Windows, the environment's Python is `.venv\Scripts\python.exe`, and `orchard.cmd` doesn't rebuild the page, so run `npm run build` yourself after changing the frontend. ONNX Runtime needs the Microsoft Visual C++ Redistributable there. Without it, visual search says how to install it.

Search runs SigLIP 2 with ONNX Runtime on the CPU, or on the GPU through Core ML on an Apple Silicon Mac. To use an NVIDIA GPU, install `onnxruntime-gpu` in place of `onnxruntime`, and search uses CUDA. `./orchard` makes a fresh `.venv` whenever `requirements.txt` changes, so install `onnxruntime-gpu` again after that.

The built page in `dist/` is committed, so running Orchard needs no Node. To work on the frontend, you need Node 18+:

```bash
npm ci
npm run build
```

Commit `dist/` with your change. CI fails when it doesn't match the sources. Once `node_modules` exists, `./orchard` also rebuilds the page when its sources change.

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
| `server/scanner.py` | Finds image files, reads metadata and draws thumbnails. |
| `server/semantic.py` | Downloads and runs SigLIP 2 with ONNX Runtime, and stores each folder's vectors. |
| `server/groups.py` | Groups near-duplicates. |
| `server/layout.py` | Lays out the map with UMAP, written in NumPy. |
| `server/atlas.py` | Packs map icons into sheets. |
| `web/src/` | The React frontend. `App.tsx` is the entry point, and `mapEngine.ts` draws the map. |
| `dist/` | The built page. Committed, so running Orchard needs no Node. |
| `tests/` | Python tests, one file per server module. |
| `scripts/install-app` | Builds the macOS app that opens Orchard's window from the Dock. Mac only. |
| `orchard`, `orchard.cmd` | The launchers for macOS and Linux, and for Windows. They find a supported Python, install the packages, and start the server with `--window`. |
| `scripts/smoke-test` | Installs and starts Orchard on a few generated images, and checks the API. |
| `scripts/build-coreml-model` | Builds the image encoder Orchard runs through Core ML, and the parity vector Orchard checks it against. |
| `.github/workflows/ci.yml` | Runs the tests and the smoke test on Ubuntu, macOS and Windows. |
| `app.json` | The app's name, command name and ports. |

## Tests

Run the Python tests and the TypeScript build check:

```bash
npm test
```

`npm test` runs `.venv/bin/python`, which Windows doesn't have. There, run `.venv\Scripts\python -m unittest discover -s tests`. Tests that need symlinks or folder permissions are skipped on Windows.

```bash
npm run build
```

The tests never download the model. They replace the model with fixed vectors.

The smoke test runs Orchard the way a user does. It installs and starts it through `./orchard --browser`, or `orchard.cmd` on Windows, on a few generated images, with a temporary cache and port 4499, and checks that the API lists them and the page loads. On a fresh clone, it covers the first-run install too:

```bash
scripts/smoke-test
```

On Windows, run `python scripts\smoke-test`.

Add `--visual` to also download the search model and check that a search finds the right image. CI runs the smoke test and the Python tests on Ubuntu, macOS and Windows, and checks that `dist/` matches the sources. To run the visual check there, start the workflow by hand with **visual** ticked.

## The Core ML model

On an Apple Silicon Mac, Orchard downloads its image encoder from its own Hugging Face repository instead of the ONNX export, as [How Orchard works](how-it-works.md#visual-search) describes. `scripts/build-coreml-model` makes that file from the export's pinned revision, and prints its SHA-256. The same input always gives the same file. It needs the `onnx` package, which the app doesn't:

```bash
.venv/bin/pip install onnx==1.23.2
.venv/bin/python scripts/build-coreml-model build/
```

To publish a new version, upload the file to the repository named by `CORE_ML_REPOSITORY` in `server/semantic.py`, then set `CORE_ML_REVISION` to the upload's commit, and `CORE_ML_SHA256` and its entry in `SIZES` to what the script printed. If the model or the test image changes, add `--parity` to also write `server/parity-vector.npy`, the vector the full-precision encoder gives on the CPU for the test image.

To try the Core ML path without the download, put the built file where the download would go, under the data folder's `models` folder:

```text
models--<owner>--<name>/snapshots/<CORE_ML_REVISION>/vision_model_fp16_coreml.onnx
```

Orchard logs a warning when it falls back to the CPU.

## Renaming

The app's name, command name and ports live in `app.json`. The window title, wordmark, messages, data folder and browser storage keys all read from it. A few places carry the name directly, and need to change by hand:

- The logo, in `web/src/Logo.tsx`, `public/` and `docs/`.
- The package name in `package.json`.
- The `orchard` and `orchard.cmd` launcher files.
- The Mac app in `scripts/install-app`: its name, bundle identifier, icon and log file.
- `server/window.py`: the `ORCHARD_BUNDLE` variable the Mac app sets, and the icon path.
- The docs.
