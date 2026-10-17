# Security

## Reporting a vulnerability

Please report vulnerabilities privately, through GitHub's [private vulnerability reporting](https://github.com/chaseleantj/orchard-photos/security/advisories/new), not in a public issue. Say what an attacker could do, and how to reproduce it. I'll reply in the advisory, and credit you when the fix is released, unless you'd rather not be named.

Only the latest release, and `main`, get fixes.

## How Orchard is meant to be used

Orchard is a server that runs on your own computer, for you alone:

- It listens only on `127.0.0.1`, so other computers can't reach it.
- It accepts requests only from Orchard's own page and from programs on the computer, so a website you visit can't use it to read your photos. It refuses pages on other local ports, including the Vite development server's, any Host other than 127.0.0.1, localhost or [::1] on its own port, and POSTs that aren't JSON, which a web form could send, apart from an image search, which sends the image itself. A link from another page still opens Orchard, but no page can frame it.
- It has no accounts or passwords. Any program running on the same computer can reach it, like any other local server.
- It never moves, renames or changes your files. It keeps its cache in its own data folder.
- It goes online only to download the search model, for pip to install its packages when run from a clone, and, if you turn on **Check for updates** in Info, to ask api.github.com once a day for the latest release. That check is off unless you turn it on, and sends nothing about your photos.

Don't expose Orchard to a network, through a reverse proxy, a tunnel or port forwarding. It won't work through a proxy, and anyone who gets past that can browse your photos, since nothing in Orchard is designed to stop them. Reports that need Orchard to be exposed this way aren't vulnerabilities, but anything that lets a website or another computer reach it is.
