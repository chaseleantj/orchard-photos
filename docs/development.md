# Developing Orchard

This guide is for working on Orchard's code. To understand how the parts fit together first, read [How Orchard works](how-it-works.md).

## Setup

Orchard runs on macOS and Linux, and needs Python 3.12+. Running `./orchard` once installs the Python packages. To do it by hand:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

On Linux without an NVIDIA GPU, add `--extra-index-url https://download.pytorch.org/whl/cpu` to the `pip install`. Otherwise pip downloads several GB of CUDA libraries. `./orchard` does this for you. Search uses CUDA when it's available, then Apple's GPU, then the CPU.

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
| `--open-browser` | Open the page in the browser on start. |

## Project layout

| Path | Contents |
| --- | --- |
| `server/api.py` | The HTTP server, API routes and command line. |
| `server/library.py` | One folder's library, and the queries the API answers from it. |
| `server/scanner.py` | Finds image files, reads metadata and draws thumbnails. |
| `server/semantic.py` | Downloads and runs CLIP, and stores each folder's vectors. |
| `server/groups.py` | Groups near-duplicates. |
| `server/layout.py` | Lays out the map with UMAP. |
| `server/atlas.py` | Packs map icons into sheets. |
| `web/src/` | The React frontend. `App.tsx` is the entry point, and `mapEngine.ts` draws the map. |
| `dist/` | The built page. Committed, so running Orchard needs no Node. |
| `tests/` | Python tests, one file per server module. |
| `scripts/install-app` | Builds the macOS launcher app. Mac only. |
| `scripts/smoke-test` | Installs and starts Orchard on a few generated images, and checks the API. |
| `.github/workflows/ci.yml` | Runs the tests and the smoke test on Ubuntu and macOS. |
| `app.json` | The app's name, command name and ports. |

## Tests

Run the Python tests and the TypeScript build check:

```bash
npm test
```

```bash
npm run build
```

The tests never download CLIP. They replace the model with fixed vectors.

The smoke test runs Orchard the way a user does. It installs and starts it through `./orchard` on a few generated images, with a temporary cache and port 4499, and checks that the API lists them and the page loads. On a fresh clone, it covers the first-run install too:

```bash
scripts/smoke-test
```

Add `--visual` to also download the search model and check that a search finds the right image. CI runs the smoke test and the Python tests on Ubuntu and macOS, and checks that `dist/` matches the sources. To run the visual check there, start the workflow by hand with **visual** ticked.

## Renaming

The app's name, command name and ports live in `app.json`. The window title, wordmark, messages, data folder and browser storage keys all read from it. A few places carry the name directly, and need to change by hand:

- The logo, in `web/src/Logo.tsx`, `public/` and `docs/`.
- The package name in `package.json`.
- The `orchard` launcher file.
- The docs.
