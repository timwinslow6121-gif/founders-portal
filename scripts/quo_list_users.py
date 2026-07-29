"""List Quo (OpenPhone) workspace users + their IDs.

Reads QUO_API_KEY from the environment (VPS .env / Flask config) and calls
GET https://api.quo.com/v1/users, printing each user's id / name / email / role.

Use this to find the `id` (US...) that belongs to a portal agent, then set it as
that agent's `User.quo_user_id` so inbound Quo call/SMS webhooks attribute to them.

Run on the VPS:
    cd /var/www/founders-portal
    PYTHONPATH=. ./venv/bin/python3 scripts/quo_list_users.py

Read-only against Quo; writes nothing.
"""
import os
import sys

import requests

BASE = "https://api.quo.com/v1/users"


def _api_key():
    key = os.environ.get("QUO_API_KEY", "").strip()
    if key:
        return key
    # Fall back to the app config (loads .env the same way the portal does).
    try:
        from app import create_app
        app = create_app()
        with app.app_context():
            return (app.config.get("QUO_API_KEY") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def list_users(api_key):
    """Yield every user dict across all pages. Quo caps maxResults at 50."""
    page_token = None
    while True:
        params = {"maxResults": 50}
        if page_token:
            params["pageToken"] = page_token
        resp = requests.get(
            BASE,
            headers={"Authorization": api_key},  # no "Bearer" prefix — Quo convention
            params=params,
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"ERROR {resp.status_code}: {resp.text[:500]}", file=sys.stderr)
            sys.exit(1)
        body = resp.json()
        for u in body.get("data", []):
            yield u
        page_token = body.get("nextPageToken")
        if not page_token:
            break


def main():
    api_key = _api_key()
    if not api_key:
        print("QUO_API_KEY not set (env or app config). Aborting.", file=sys.stderr)
        sys.exit(2)

    rows = list(list_users(api_key))
    if not rows:
        print("No Quo users returned.")
        return

    print(f"{'quo_user_id':<18} {'role':<8} {'name':<28} email")
    print("-" * 80)
    for u in rows:
        name = " ".join(x for x in (u.get("firstName"), u.get("lastName")) if x) or "—"
        print(f"{u.get('id',''):<18} {u.get('role',''):<8} {name:<28} {u.get('email','')}")
    print(f"\n{len(rows)} user(s). Copy the quo_user_id (US...) for the agent you want to map.")


if __name__ == "__main__":
    main()
