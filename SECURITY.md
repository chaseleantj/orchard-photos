# Security

## Reporting a vulnerability

Please report vulnerabilities privately, through GitHub's [private vulnerability reporting](https://github.com/chaseleantj/orchard-photos/security/advisories/new), not in a public issue. Say what an attacker could do, and how to reproduce it. I'll reply in the advisory, and credit you when the fix is released, unless you'd rather not be named.

Only the latest version on `main` gets fixes.

## How Orchard is meant to be used

Orchard is a server that runs on your own computer, for you alone:

- It listens only on `127.0.0.1`, so other computers can't reach it.
- It rejects requests whose host or origin isn't its own, so a website you visit can't use it to read your photos.
- It has no accounts or passwords. Any program running on the same computer can reach it, like any other local server.
- It only reads the folder you open, and never writes to it.

Don't expose Orchard to a network, through a reverse proxy, a tunnel or port forwarding. Anyone who reaches it can browse your photos, and nothing in Orchard is designed to stop them. Reports that need Orchard to be exposed this way aren't vulnerabilities, but anything that lets a website or another computer reach it is.
