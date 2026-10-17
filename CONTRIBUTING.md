# Contributing

Bug reports, ideas and pull requests are welcome. For anything larger than a small fix, open an issue first, so we can agree on an approach before you spend time on it.

## Setup and tests

[Developing Orchard](docs/development.md) covers setting up, live reload, the project layout, and running the tests and the smoke test.

## Sending a change

- Keep each pull request to one change, with tests for new behaviour.
- If you change the frontend, commit the rebuilt `dist/` with it. CI checks that it matches the sources.
- Update the docs when behaviour changes.
- Follow the style of the code around your change. [Developing Orchard](docs/development.md) describes how the code is organised.

By contributing, you agree that your work is released under the [MIT License](LICENSE).
