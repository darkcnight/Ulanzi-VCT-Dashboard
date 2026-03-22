# NAS deployment (TrueNAS SCALE + Docker)

This guide deploys the **combined image**: **vlrggapi** (port 3001 inside the container) + **dashboard** (port 8000 in the container), as a single custom app.

**Assumptions**

- TrueNAS SCALE with Apps / Docker working.
- You build the image on a PC where this repo and [vlrggapi](https://github.com/axsddlr/vlrggapi) live side by side (default: `~/Downloads/Ulanzi Clock` and `~/Downloads/vlrggapi`).
- You use a **persistent dataset path** on the NAS for `config.json` and optionally `.env` (example below uses `/mnt/HDDs/Applications/ulanzi-clock/` — adjust pool/dataset names to match your system).

---

## What gets deployed where

| Item | Role |
|------|------|
| Docker image `ulanzi-clock:<tag>` | Application code (dashboard + vlrggapi) |
| Host file `.../config.json` | Mounted to `/app/dashboard/config.json` — **writable** (UI saves settings here) |
| Host file `.../.env` (optional) | Mounted to `/app/dashboard/.env` — **read-only** OK — supplies Twitch API env vars |

The image **does not** bake in `config.json` or `.env` (by design).

---

## 1. On your PC — build the image

From this repository root:

```bash
chmod +x scripts/build-combined-image.sh
./scripts/build-combined-image.sh ulanzi-clock YYYY-MM-DD
```

Use a tag you will remember (e.g. `2026-03-22`).  
If `vlrggapi` is not at `~/Downloads/vlrggapi`:

```bash
VLRGGAPI_DIR=/path/to/vlrggapi ./scripts/build-combined-image.sh ulanzi-clock YYYY-MM-DD
```

Verify:

```bash
docker image ls | grep ulanzi-clock
```

---

## 2. On your PC — export a deploy bundle (recommended)

This creates a folder with everything you need to copy to the NAS (USB, SMB, `scp`, etc.):

```bash
chmod +x scripts/export-combined-deploy-bundle.sh
./scripts/export-combined-deploy-bundle.sh ./dist ulanzi-clock YYYY-MM-DD
```

You should get:

- `dist/ulanzi-clock-YYYY-MM-DD.tar` — image
- `dist/config.json` — from your repo
- `dist/.env` — **only if** `.env` exists locally (Twitch credentials)

Copy the whole `dist/` folder to the NAS (or only the three files).

**Twitch:** copy `.env.example` to `.env` and set `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` before exporting, or set those variables in TrueNAS later (see §5).

---

## 3. On the NAS — place files on persistent storage

Pick a directory on a dataset, e.g.:

```text
/mnt/HDDs/Applications/ulanzi-clock/
```

Create it if needed, then copy:

- `ulanzi-clock-YYYY-MM-DD.tar`
- `config.json` → `.../ulanzi-clock/config.json`
- `.env` → `.../ulanzi-clock/.env` (if you use Twitch)

Example after copying:

```text
/mnt/HDDs/Applications/ulanzi-clock/ulanzi-clock-2026-03-22.tar
/mnt/HDDs/Applications/ulanzi-clock/config.json
/mnt/HDDs/Applications/ulanzi-clock/.env
```

---

## 4. On the NAS — load the image

In a TrueNAS shell (or SSH):

```bash
sudo docker load -i /mnt/HDDs/Applications/ulanzi-clock/ulanzi-clock-YYYY-MM-DD.tar
sudo docker image ls | grep ulanzi-clock
```

You should see `ulanzi-clock` with your tag.

---

## 5. On TrueNAS — install the custom app (YAML)

1. Open the TrueNAS web UI → **Apps**.
2. **Discover Apps** → **Custom App** → **Install via YAML** (or equivalent).
3. Give the app a name (lowercase, e.g. `ulanzi-vct-dashboard`).
4. Paste YAML like below — **replace** `YYYY-MM-DD`, host paths, and host port if needed.

### Full example (config + Twitch `.env`)

```yaml
services:
  ulanzi-clock:
    image: ulanzi-clock:YYYY-MM-DD
    pull_policy: never
    restart: unless-stopped
    ports:
      - "18000:8000"
    volumes:
      - /mnt/HDDs/Applications/ulanzi-clock/config.json:/app/dashboard/config.json
      - /mnt/HDDs/Applications/ulanzi-clock/.env:/app/dashboard/.env:ro
```

| Setting | Meaning |
|---------|---------|
| `pull_policy: never` | Use the image you loaded locally; do not pull from a registry. |
| `18000:8000` | Dashboard on NAS port **18000** (change if that port is taken). |
| First volume | Writable config file. |
| Second volume | Twitch credentials via `load_dotenv()` — read-only mount is fine. |

### If you do not use Twitch

Omit the `.env` line (or don’t create `.env` on the NAS). You may see harmless Twitch warnings if the module is enabled in `config.json`.

### Alternative: env vars in YAML instead of `.env`

You can set secrets in the compose `environment:` block instead of mounting `.env`. Prefer **not** committing that YAML to git if it contains secrets.

---

## 6. Open the dashboard

From your PC browser (replace with your NAS LAN IP):

```text
http://<NAS_IP>:18000
```

Example: `http://192.168.1.50:18000`

**Note:** Custom apps installed **via YAML** often do **not** show an **Open Web UI** button in the Apps screen. Bookmark the URL above.

---

## 7. Verify the container

In a shell:

```bash
sudo docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

Find the container running `ulanzi-clock:YYYY-MM-DD`. Check env (if you use `.env` or YAML `environment:`):

```bash
sudo docker inspect <CONTAINER_NAME> --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^TWITCH_'
```

---

## 8. Updates (new image from PC)

1. Build a new tag: `./scripts/build-combined-image.sh ulanzi-clock NEW-TAG`
2. Export bundle or copy the new `.tar` to the NAS.
3. `sudo docker load -i .../ulanzi-clock-NEW-TAG.tar`
4. Edit the app YAML: change `image: ulanzi-clock:NEW-TAG`
5. Save / redeploy.

`config.json` and `.env` on disk stay as-is unless you change them.

---

## 9. Reboot behavior

With `restart: unless-stopped`, the app should start again after a NAS reboot. Persistent data is the **mounted** `config.json` and `.env`, not the container filesystem.

---

## 10. Troubleshooting

| Symptom | Things to check |
|---------|------------------|
| Page won’t load | App running? Port `18000` not used by another service? Firewall? |
| Dashboard loads, clock doesn’t update | `awtrix_ip` in `config.json` reachable from NAS; same LAN/VLAN if applicable. |
| Twitch errors | `.env` mounted at `/app/dashboard/.env` **or** `TWITCH_*` in container env; credentials valid (Twitch Developer Console). |
| `400` from Twitch token URL | Wrong/expired client secret; placeholder env values; rotate secret if leaked. |
| Config changes don’t save | `config.json` mount must be **writable**; check file permissions on the NAS path. |

---

## Reference files in this repo

| File | Purpose |
|------|---------|
| `scripts/build-combined-image.sh` | Staged build + `docker build` |
| `scripts/export-combined-deploy-bundle.sh` | Export `.tar` + `config.json` + `.env` |
| `docker/truenas-compose.example.yaml` | Example compose snippet |
| `docker/Dockerfile.combined` | Combined image definition |

For general project behavior, see [README.md](README.md).

---

## Expectations

This project was built with **Cursor** (including **Composer**) and assistance from **Gemini**, **Claude**, and **ChatGPT**. Deploy and run **at your own risk**. It has been validated in a personal setup; your environment may differ.

GitHub issues are welcome, but fixes are **not guaranteed** — the project is niche and primarily for **self-use**. See the [README](README.md#ai-assisted-development--expectations) for the full disclaimer.
