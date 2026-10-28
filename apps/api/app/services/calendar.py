"""
Calendar integration — stub.

TODO (week 4): connect Google Calendar.
  1. In Google Cloud console, enable the Calendar API and create OAuth
     credentials (Desktop app type is easiest for a personal project).
  2. Run a one-off local script to get a refresh token for your account and
     store it as an env var (GOOGLE_REFRESH_TOKEN) on Render.
  3. Here, exchange the refresh token for an access token and call
     GET https://www.googleapis.com/calendar/v3/calendars/primary/events
     with timeMin / timeMax for the day, singleEvents=true, orderBy=startTime.

Until then the brief simply has no meetings in it.
"""


async def events_for(date: str) -> list[dict]:
    """Return [{"title": str, "start": iso, "end": iso}] for the given day."""
    return []
