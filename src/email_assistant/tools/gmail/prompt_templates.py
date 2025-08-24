"""Tool prompt templates for Gmail integration."""

# Gmail tools prompt for insertion into agent system prompts
GMAIL_TOOLS_PROMPT = """
1. fetch_emails_tool(email_address, minutes_since) - Fetch recent emails from Gmail
2. send_email_tool(email_id, response_text, email_address, additional_recipients) - Send a reply to an email thread
3. check_calendar_tool(dates) - Check Google Calendar availability for specific dates
4. schedule_meeting_tool(attendees, title, start_time, end_time, organizer_email, timezone) - Schedule a meeting and send invites
5. triage_email(ignore, notify, respond) - Triage emails into one of three categories
6. Done - E-mail has been sent
"""

TOOLS_TWEEDEKAMER_PROMPT = """
1. fetch_emails_tool(email_address, minutes_since) - Fetch recent emails from Gmail for the given address and lookback window (minutes).
2. send_email_tool(email_id, response_text, email_address, additional_recipients) - Send a reply to an email thread; provide the thread `email_id`, the `response_text`, and the `email_address` of the sender (optional additional_recipients).
3. triage_email(action) - Triage an email; `action` should be one of: `ignore`, `notify`, or `respond`.
4. Done - Indicates the email has been handled / a reply has been sent.
5. search_kamerleden(naam, functie, actief, limit) - Search parliament members by partial `naam`, `functie` (role), filter `actief` members, limit results.
6. get_kamerstukken(soort, dagen_terug, zoekterm, limit) - Retrieve recent parliamentary documents (by `soort`), search back `dagen_terug`, optional `zoekterm`, and `limit`.
7. search_vergaderingen(commissie, dagen_vooruit, dagen_terug, limit) - Find meetings/activities filtered by `commissie` and date window (uses `Aanvangstijd`).
8. get_stemmingen(dagen_terug, zaak_onderwerp, limit) - Get recent voting records; filter by `zaak_onderwerp` and lookback `dagen_terug`.
9. search_commissies(naam, actief, limit) - Search committees by `naam`; `actief` filters active committees; `limit` caps results.
10. clarification_tool(target_tool, missing_or_unclear_params, user_request_context, suggestions) - Ask user for clarification when parameters are missing or unclear; helps improve API call success rate.
"""

# Combined tools prompt (default + Gmail) for full integration
COMBINED_TOOLS_PROMPT = """
1. fetch_emails_tool(email_address, minutes_since) - Fetch recent emails from Gmail
2. send_email_tool(email_id, response_text, email_address, additional_recipients) - Send a reply to an email thread
3. check_calendar_tool(dates) - Check Google Calendar availability for specific dates
4. schedule_meeting_tool(attendees, title, start_time, end_time, organizer_email, timezone) - Schedule a meeting and send invites
5. write_email(to, subject, content) - Draft emails to specified recipients
6. triage_email(ignore, notify, respond) - Triage emails into one of three categories
7. check_calendar_availability(day) - Check available time slots for a given day
8. Done - E-mail has been sent
"""