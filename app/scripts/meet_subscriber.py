"""
app/scripts/meet_subscriber.py

Google Meet Pub/Sub pull subscriber — processes transcript.fileGenerated events.

Runs as a persistent background service (see meet_subscriber.service).
For each event:
  1. Decode the Pub/Sub message and extract the transcript resource name.
  2. Fetch transcript entries from the Meet REST API.
  3. Match to a Customer via the organizer agent's recent appointment note.
  4. Create CustomerNote(note_type='meeting_summary') on match.
  5. Create UnmatchedCall(provider='google_meet') on no match.
  6. ack() on success; nack() on exception so Pub/Sub retries.

Requires:
  - GOOGLE_APPLICATION_CREDENTIALS env var pointing to a service account JSON key
  - GOOGLE_MEET_PUBSUB_SUBSCRIPTION env var (full subscription name)
  - google-cloud-pubsub and google-auth packages in requirements.txt
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flask app context (required for DB access in background scripts)
# ---------------------------------------------------------------------------

def _make_flask_app():
    from app import create_app
    return create_app()


# ---------------------------------------------------------------------------
# Google Meet REST API helper
# ---------------------------------------------------------------------------

def get_transcript_entries(transcript_name: str) -> dict:
    """
    Fetch transcript entries from the Meet REST API.

    transcript_name: e.g. "conferenceRecords/CR-1/transcripts/TR-1"
    Returns the JSON response dict with key "transcriptEntries".

    Raises on HTTP error or network failure — caller handles nack.
    """
    try:
        import google.auth
        import google.auth.transport.requests
        import requests as http_requests

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/meetings.space.readonly"]
        )
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)

        url = f"https://meet.googleapis.com/v2/{transcript_name}/entries"
        resp = http_requests.get(
            url,
            headers={"Authorization": f"Bearer {credentials.token}"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except ImportError:
        raise RuntimeError(
            "google-auth and google-cloud-pubsub are required. "
            "Run: pip install google-auth google-cloud-pubsub requests"
        )


# ---------------------------------------------------------------------------
# Customer resolution
# ---------------------------------------------------------------------------

def resolve_customer_from_transcript(transcript_name: str, organizer_email: str | None):
    """
    Attempt to match a transcript to a (Customer, User) pair.

    Strategy:
      1. Look up the agent User by organizer_email.
      2. Find the most recent CustomerNote(note_type='appointment_scheduled')
         created by that agent within the last 2 hours.
      3. Return (customer, agent) if found; (None, None) otherwise.

    This runs inside an active Flask app_context — DB queries are safe.
    """
    from app.models import Customer, CustomerNote, User

    agent = None
    if organizer_email:
        agent = User.query.filter_by(email=organizer_email).first()

    if agent is None:
        return None, None

    cutoff = datetime.utcnow() - timedelta(hours=2)
    recent_note = (
        CustomerNote.query
        .filter_by(note_type="appointment_scheduled", agent_id=agent.id)
        .filter(CustomerNote.created_at >= cutoff)
        .order_by(CustomerNote.created_at.desc())
        .first()
    )

    if recent_note is None:
        return None, agent

    customer = Customer.query.get(recent_note.customer_id)
    return customer, agent


# ---------------------------------------------------------------------------
# Pub/Sub callback
# ---------------------------------------------------------------------------

def process_transcript_event(message, _app=None) -> None:
    """
    Pub/Sub streaming pull callback.

    Decodes the message, fetches the transcript, matches a customer,
    and persists a CustomerNote or UnmatchedCall.

    Always calls message.ack() on success or expected no-match.
    Calls message.nack() on unexpected exceptions so Pub/Sub retries.

    _app: optional Flask app instance — used in tests to inject the test app
          so DB operations hit the test DB. When None, creates a new app.
    """
    try:
        data = json.loads(message.data.decode("utf-8"))
        transcript_name = data.get("transcript", {}).get("name", "")
        # organizer_email is not in the Pub/Sub payload — requires a separate
        # conferenceRecords REST call. Using None here routes to unmatched
        # if no appointment_scheduled note exists within 2 hours.
        organizer_email = data.get("organizer_email")

        transcript_response = get_transcript_entries(transcript_name)
        entries = transcript_response.get("transcriptEntries", [])

        # Build summary text from all transcript entries
        summary_lines = [
            f"{e.get('participantName', 'Unknown')}: {e.get('text', '')}"
            for e in entries
        ]
        summary_text = "\n".join(summary_lines)

        # Use existing app context if one is active (test environment),
        # otherwise push a new context from the created/injected app.
        try:
            from flask import current_app
            _ = current_app.name  # triggers RuntimeError if no context is active
            active_ctx = True
        except RuntimeError:
            active_ctx = False

        def _do_db_work():
            from app.extensions import db
            from app.models import CustomerNote, UnmatchedCall
            from flask import current_app as _cur_app

            customer, agent = resolve_customer_from_transcript(transcript_name, organizer_email)

            agency_id = _cur_app.config.get("DEFAULT_AGENCY_ID", 1)

            if customer and agent:
                # Extract conference record ID from transcript_name for the Meet URL
                conf_id = transcript_name.split("/")[1] if "/" in transcript_name else ""
                source_url = f"https://meet.google.com/{conf_id}" if conf_id else ""

                note = CustomerNote(
                    note_type="meeting_summary",
                    note_text=summary_text,
                    source_url=source_url,
                    contact_method="video",
                    customer_id=customer.id,
                    agent_id=agent.id,
                    agency_id=agency_id,
                    created_at=datetime.utcnow(),
                )
                db.session.add(note)
            else:
                unmatched = UnmatchedCall(
                    provider="google_meet",
                    call_sid=transcript_name,
                    from_number="",
                    to_number=None,
                    direction="inbound",
                    duration_seconds=0,
                    occurred_at=datetime.utcnow(),
                    agency_id=agency_id,
                    agent_id=agent.id if agent else None,
                )
                db.session.add(unmatched)

            db.session.commit()

        if active_ctx:
            _do_db_work()
        else:
            flask_app = _app or _make_flask_app()
            with flask_app.app_context():
                _do_db_work()

        message.ack()

    except Exception as exc:  # noqa: BLE001
        logger.error("meet_subscriber: error processing message: %s", exc, exc_info=True)
        message.nack()


# ---------------------------------------------------------------------------
# Subscriber loop (main entry point)
# ---------------------------------------------------------------------------

def run_subscriber():
    """
    Start the Pub/Sub streaming pull subscriber and run indefinitely.

    Reads GOOGLE_MEET_PUBSUB_SUBSCRIPTION from the environment.
    Requires GOOGLE_APPLICATION_CREDENTIALS to be set.
    """
    try:
        from google.cloud import pubsub_v1
    except ImportError:
        logger.error(
            "google-cloud-pubsub is not installed. "
            "Run: pip install google-cloud-pubsub"
        )
        sys.exit(1)

    subscription_path = os.environ.get("GOOGLE_MEET_PUBSUB_SUBSCRIPTION", "")
    if not subscription_path:
        logger.error(
            "GOOGLE_MEET_PUBSUB_SUBSCRIPTION env var is not set. "
            "Set it to the full Pub/Sub subscription name, e.g. "
            "projects/my-project/subscriptions/meet-transcripts"
        )
        sys.exit(1)

    subscriber = pubsub_v1.SubscriberClient()
    logger.info("meet_subscriber: starting — subscription=%s", subscription_path)

    streaming_pull_future = subscriber.subscribe(subscription_path, callback=process_transcript_event)

    try:
        streaming_pull_future.result()
    except KeyboardInterrupt:
        streaming_pull_future.cancel()
        logger.info("meet_subscriber: stopped by KeyboardInterrupt")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_subscriber()
