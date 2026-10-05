# Running py-tbparse as a server

The browser GUI is built for one person on their own machine. The Docker image runs it as a small shared
service instead: a team opens a URL, drops in their workbooks and looks at them. TLS ends at a reverse proxy in
front of it; the app speaks plain HTTP on port 8080.

**There is no login** (see Limits in the [README](https://github.com/DDSNA/py-tbparse/blob/main/README.md#limits)). Anyone who can reach the URL can upload files and use the CPU. Put the proxy's own
authentication (basic auth, SSO, a VPN) in front of it, and do not expose it to the public internet without one.

## Quick start

```bash
TBPARSE_HOST=tbparse.example.com docker compose up -d --build
```

This starts the app and a Caddy proxy that gets a certificate for that name. For another proxy, run the image
on its own:

```bash
docker build -t py-tbparse .
docker run -d --name tbparse -p 127.0.0.1:8080:8080 \
    --read-only --tmpfs /tmp:size=512m \
    -e PY_TBPARSE_ALLOWED_HOSTS=tbparse.example.com \
    py-tbparse
```

## Published image

From the next GitHub Release on, each release also publishes the image to the GitHub Container Registry, tagged with
the release version (without the leading `v`); `latest` follows the newest release that is not a pre-release. No
image exists yet: the publish workflow was added after 0.4.6 and has not run, so there is no `0.4.6` image (build it
from the source as above).

```bash
docker pull ghcr.io/ddsna/py-tbparse:<version>
docker run -d --name tbparse -p 127.0.0.1:8080:8080 \
    --read-only --tmpfs /tmp:size=512m \
    -e PY_TBPARSE_ALLOWED_HOSTS=tbparse.example.com \
    ghcr.io/ddsna/py-tbparse:<version>
```

Pin a version rather than `latest` for anything you run for a team. To use it with the compose file, replace
`build: .` with `image: ghcr.io/ddsna/py-tbparse:<version>`. The image is built from the release's source, not
from PyPI.

The publish job uses the same `release` environment as the PyPI upload and runs without manual approval. The first push creates the package as private; the maintainer makes it public once in the package settings on GitHub so it can be pulled without logging in.

## What server mode changes

The image starts `py-tbparse-gui` with `--server-mode --trust-proxy` (through environment variables).

- **One session per browser.** Each browser gets a random, `HttpOnly`, `SameSite=Strict` cookie and its own
  workbook, so nobody sees anyone else's file. Sessions end after `PY_TBPARSE_SESSION_TTL` seconds without a
  request (default 3600); when more than `PY_TBPARSE_MAX_SESSIONS` (default 20) are open, the least recently used
  one is dropped. Ending a session deletes its uploaded files. Sessions live in memory, so a restart or a second
  replica starts everyone over: run one container.
- **Uploads only.** Typing a server path (`/load`) and "Create fixed workbook" (which saves beside the original)
  are refused, and the path box is hidden. Download the fixed copy instead. The same holds for the templates
  endpoints: opening a template or data file by path and saving beside the template are refused, and nothing in
  a request body is ever opened as a file.
- **Host and origin checks follow the proxy.** The app accepts the names in `PY_TBPARSE_ALLOWED_HOSTS` (comma or
  space separated, any port). With `--trust-proxy` it also accepts the `https://` form of the same `Host` as the
  `Origin` of a POST, and marks the cookie `Secure` when the proxy sends `X-Forwarded-Proto: https`. A request
  for any other name gets a 403.
- **`GET /healthz`** answers `ok` without a session or a host check, for Docker and the proxy.

## What the proxy must do

1. Pass the original `Host` header through (Caddy and nginx's `proxy_set_header Host $host` do; some proxies
   rewrite it to the upstream name, which the app will then refuse).
2. Send `X-Forwarded-Proto` if you want the `Secure` cookie flag.
3. Allow request bodies up to the app's 200 MB upload limit, and stream them:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 200m;
    proxy_request_buffering off;
}
```

## Sizing

An upload is written to `/tmp` (the container's `TMPDIR`) and kept until the session ends. A session can hold an
opened workbook, a template, a data file (200 MB limit each) and one workbook made from the template, so the worst
case is `PY_TBPARSE_MAX_SESSIONS` x about 600 MB plus the outputs. An upload is refused with 507 when the temp
folder has less than twice its size plus 256 MB free. The compose file gives `/tmp` a 512 MB tmpfs, which assumes
most files are far smaller; raise it, or lower the session limit, to match your workbooks. Parsing a large
workbook or template uses memory on top of that.

## Settings

| Variable | Option | Default | Meaning |
|---|---|---|---|
| `PY_TBPARSE_SERVER_MODE` | `--server-mode` | on in the image | sessions, uploads only |
| `PY_TBPARSE_ALLOWED_HOSTS` | `--allowed-host` | none | public host names, any port |
| `PY_TBPARSE_TRUST_PROXY` | `--trust-proxy` | on in the image | accept https origins, `Secure` cookie |
| `PY_TBPARSE_MAX_SESSIONS` | `--max-sessions` | 20 | sessions held at once |
| `PY_TBPARSE_SESSION_TTL` | `--session-ttl` | 3600 | idle seconds before a session ends |

Do not use `--trust-proxy` when the app is reachable without going through the proxy; the `Origin` check is
then looser than it needs to be.
