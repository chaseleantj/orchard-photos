# Contributing

Bug reports, ideas and pull requests are welcome. For anything larger than a small fix, open an issue first, so we can agree on the approach before you spend time on it.

## Setup

Clone the repository and run Orchard once, which installs its Python packages into `.venv`:

```bash
git clone https://github.com/chaseleantj/orchard-photos.git
cd orchard-photos
./orchard ~/Pictures
```

On Windows, run `orchard.cmd` instead. To change the web page, you also need Node 18 or later and `npm ci`. [Developing Orchard](docs/development.md) covers live reload, the project layout and the server's options.

## Tests

Run the Python tests and the TypeScript check:

```bash
npm test
npm run build
```

Then run the smoke test, which installs and starts Orchard on a few generated images. Add `--visual` to also download the search model and check a search:

```bash
scripts/smoke-test
```

On Windows, run `.venv\Scripts\python -m unittest discover -s tests` and `python scripts\smoke-test`. CI runs all of these on Ubuntu, macOS and Windows for every pull request.

## Sending a change

- Keep each pull request to one change, with tests for new behaviour.
- If you change the frontend, commit the rebuilt `dist/` with it. CI checks that it matches the sources.
- Update the docs when behaviour changes.
- Follow the style of the code around your change. [Developing Orchard](docs/development.md) describes how the code is organised.

By contributing, you agree that your work is released under the [MIT License](LICENSE).
