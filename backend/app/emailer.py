"""Sends password-reset and invite emails: Gmail SMTP (App Password) or the Resend HTTPS API.
Resend is the fallback when the host blocks SMTP ports (DigitalOcean blocks them on Droplets)."""
import html
import json
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage

from . import config


def enabled() -> bool:
    if config.EMAIL_PROVIDER == "resend":
        return bool(config.RESEND_API_KEY and config.EMAIL_FROM)
    return bool(config.SMTP_USER and config.SMTP_PASSWORD)


def _content(name, link, minutes, invite):
    hello = f"Hello {name}," if name else "Hello,"
    valid = f"{minutes // (24 * 60)} days" if minutes >= 24 * 60 else f"{minutes} minutes"
    if invite:
        subject = "Your Damodara KPI dashboard account"
        lead = "An account has been created for you on the Damodara Oil Mill KPI dashboard. Set your password here:"
    else:
        subject = "Reset your Damodara KPI dashboard password"
        lead = "We received a request to reset your password. Choose a new one here:"
    tail = f"This link works once and expires in {valid}. If you did not expect this email, ignore it."
    text = f"{hello}\n\n{lead}\n{link}\n\n{tail}\n"
    body = (f"<p>{html.escape(hello)}</p><p>{html.escape(lead)}</p>"
            f'<p><a href="{html.escape(link)}" style="background:#2563eb;color:#fff;padding:10px 16px;'
            f'border-radius:6px;text-decoration:none;display:inline-block">'
            f'{"Set password" if invite else "Reset password"}</a></p>'
            f'<p style="color:#6b7280;font-size:13px">{html.escape(tail)}<br>{html.escape(link)}</p>')
    return subject, text, body


def send_reset(to, name, link, minutes, invite=False):
    if not enabled():
        raise RuntimeError("Email is not configured.")
    subject, text, body = _content(name, link, minutes, invite)
    if config.EMAIL_PROVIDER == "resend":
        _send_resend(to, subject, text, body)
    else:
        _send_smtp(to, subject, text, body)


def _send_smtp(to, subject, text, body):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, config.EMAIL_FROM, to
    msg.set_content(text)
    msg.add_alternative(body, subtype="html")
    ctx = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=ctx, timeout=20) as s:
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.starttls(context=ctx)
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)


def _send_resend(to, subject, text, body):
    req = urllib.request.Request(
        "https://api.resend.com/emails", method="POST",
        data=json.dumps({"from": config.EMAIL_FROM, "to": [to], "subject": subject,
                         "text": text, "html": body}).encode(),
        headers={"Authorization": f"Bearer {config.RESEND_API_KEY}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        if r.status >= 300:
            raise RuntimeError(f"Resend returned HTTP {r.status}")
