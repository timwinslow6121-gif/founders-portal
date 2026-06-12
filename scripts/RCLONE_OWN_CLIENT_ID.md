# Fix: nightly Drive backup hits `RATE_LIMIT_EXCEEDED` (durable fix)

## Symptom
`scripts/backup.sh` fails at the rclone step with:

```
Error 403: Quota exceeded for quota metric 'Queries' and limit 'Queries per minute'
of service 'drive.googleapis.com' ... reason: RATE_LIMIT_EXCEEDED
```

## Root cause
The rclone remote `gdrive:` uses **rclone's shared/default OAuth client_id** (there is no
`client_id` line in `rclone config show gdrive`). Google rate-limits that shared client
*globally* across all rclone users, so a tiny nightly backup can get a 403 that has nothing
to do with our own volume.

## Mitigation already applied (no action needed)
`scripts/backup.sh` now passes retry + pacer flags (`--retries 5 --retries-sleep 30s
--low-level-retries 10 --drive-pacer-min-sleep 100ms`) so a transient shared-client 403
self-heals instead of failing the run. This alone should ride through the occasional blip.

## Durable fix — give rclone its OWN OAuth client_id (~5 min, needs the Google console)
This moves the backup onto a private quota bucket so the shared-client throttling can't touch it.

1. Go to https://console.cloud.google.com → create (or reuse) a project, e.g. "founders-backup".
2. **APIs & Services → Library →** enable **Google Drive API**.
3. **APIs & Services → OAuth consent screen:** External, app name "founders-backup",
   add your admin@ email as a test user, save. (No verification needed for personal use.)
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID →**
   Application type **Desktop app**. Copy the **Client ID** and **Client secret**.
5. On the VPS, reconfigure the remote with them:
   ```
   rclone config reconnect gdrive:            # or: rclone config → edit gdrive
   # when prompted, paste client_id + client_secret; keep scope=drive
   ```
   (Or edit `~/.config/rclone/rclone.conf` directly: add `client_id =` and `client_secret =`
   under `[gdrive]`, then `rclone config reconnect gdrive:` to refresh the token.)
6. Verify: `rclone lsd gdrive:` lists folders without a 403, then run a manual backup:
   `BACKUP_PASSPHRASE=... /var/www/founders-portal/scripts/backup.sh` (or wait for cron).

Once done, the `RATE_LIMIT_EXCEEDED` class of failure is gone for good.
