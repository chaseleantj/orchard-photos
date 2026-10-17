# How Orchard works

Orchard has two parts: a Python server and a React web page. The server scans a folder, builds an index, and runs the search model. The page asks the server for images and shows them in the grid, viewer and map. Both run on your computer, and the server only ever reads your photos.

```text
your folder
  -> scanner: find image files, hash them, read EXIF, make thumbnails
  -> SQLite index
  -> CLIP: turn each thumbnail into a vector
  -> near-duplicate groups, map layout
  -> HTTP API on 127.0.0.1
  -> web page
```

## Scanning

The scanner walks the whole folder and finds every image file. For each new or changed file, it:

1. Hashes the contents with SHA-256.
2. Reads the width, height, camera and date taken from EXIF.
3. Draws a 720 px WebP thumbnail.

Images are stored by their hash, so identical files share one entry, and a renamed or moved file keeps its thumbnail and search data. On later scans, a file whose size and modification time haven't changed is skipped, so rescans are fast. Files that have disappeared are removed from the index, along with any thumbnails no file uses.

The server rescans the open folder every minute.

## Visual search

Orchard uses CLIP ([`openai/clip-vit-base-patch32`](https://huggingface.co/openai/clip-vit-base-patch32)), a model trained to turn both images and text into vectors. An image and a sentence that describe the same thing get vectors that point in a similar direction.

After a scan, the server runs each new thumbnail through CLIP and stores the vector. To search, it turns your description (or your reference image) into a vector, and ranks every image by cosine similarity to it. Even with tens of thousands of images, this is one quick matrix multiplication, so there's no separate search index.

Orchard runs CLIP with ONNX Runtime, from an ONNX export of the same weights ([`Xenova/clip-vit-base-patch32`](https://huggingface.co/Xenova/clip-vit-base-patch32)), which gives the same vectors as the original. The model is downloaded once from Hugging Face at a pinned revision, and is shared by every folder. It runs on the CPU, or on an NVIDIA GPU if `onnxruntime-gpu` is installed.

## Near-duplicates

Bursts, edits and resized copies are different files, so they have different hashes. Their CLIP vectors, however, are almost the same. Orchard groups images whose vectors have a cosine similarity of 0.97 or more.

Each group forms around one centre, and every member must match that centre. This stops a slow series, like a plant photographed every day, from chaining into one long group. Crops differ more than resized copies, so Orchard also groups files in the same folder whose names differ only by a size or copy suffix (like `photo-800x400.jpg` and `photo (1).jpg`), as long as they look related.

The image that fronts each group is the sharpest one, measured by the variance of the Laplacian. Between copies of one picture, which are about equally sharp, the larger one wins.

## The map

The map uses UMAP to squeeze the CLIP vectors down to two dimensions, so similar images land close together. UMAP links each image to its 15 nearest neighbours, then arranges the images so linked ones pull together while random pairs push apart. Orchard has its own short version in NumPy, which avoids several hundred MB of dependencies. In folders of more than 10,000 images, comparing every image with every other would take most of the time, so Orchard sorts the images into clusters and compares each one only with the clusters around it. That finds about 99.5% of the true neighbours, and a folder of 100,000 images lays out in about 10 seconds on an Apple M5. Positions are saved. When new images arrive, each is placed at the weighted centre of its nearest neighbours, so the map stays put. Orchard only fits the layout again once new images make up more than a fifth of the map.

To draw thousands of images quickly, the server packs small icons into atlas sheets of 1,024 icons each. The page loads a handful of sheets instead of one request per image.

## The server

The server is a small HTTP server from Python's standard library. It serves the built page from `dist/` and a JSON API under `/api/`. It only listens on `127.0.0.1`, and it rejects requests from other hosts and other sites, so a web page you visit can't read your photos through it.

Only one folder is open at a time. Opening another folder closes the current one and stops its background work.

## Where data lives

The cache lives in `~/Library/Application Support/orchard/` on macOS, `~/.local/share/orchard/` on Linux, and `%LOCALAPPDATA%\orchard\` on Windows. You can change it with `--data-dir`.

| Path | Contents |
| --- | --- |
| `models/` | The CLIP weights, shared by all folders. |
| `libraries/<id>/` | One folder's cache: its SQLite index, thumbnails, previews, vectors, map positions and icon sheets. `folder.txt` names the folder it belongs to. |
| `recent.json` | The recently opened folders. |

Deleting a `libraries/<id>` folder clears that folder's cache. Orchard rebuilds it the next time you open the folder.
