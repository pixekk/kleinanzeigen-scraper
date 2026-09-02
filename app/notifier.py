from __future__ import annotations

import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Iterable

from .config import SearchConfig, SmtpConfig
from .models import Listing

log = logging.getLogger(__name__)


def _card(listing: Listing) -> str:
    title = html.escape(listing.title)
    url = html.escape(listing.url, quote=True)
    price = html.escape(listing.price_display)
    location = html.escape(listing.location)
    posted = html.escape(listing.posted_text)
    description = html.escape((listing.description or listing.detail_description)[:280])
    image = (
        f'<img src="{html.escape(listing.image_url, quote=True)}" width="120" '
        f'style="border-radius:6px;display:block;object-fit:cover" alt="">'
        if listing.image_url.startswith("http")
        else ""
    )
    meta = " &middot; ".join(part for part in (location, posted) if part)
    return f"""
      <tr>
        <td style="padding:12px 0;border-bottom:1px solid #e5e7eb;vertical-align:top;width:132px">{image}</td>
        <td style="padding:12px 0 12px 12px;border-bottom:1px solid #e5e7eb;vertical-align:top">
          <a href="{url}" style="font-size:16px;font-weight:600;color:#1f2937;text-decoration:none">{title}</a>
          <div style="margin:6px 0;font-size:18px;font-weight:700;color:#047857">{price}</div>
          <div style="font-size:12px;color:#6b7280">{meta}</div>
          <div style="margin-top:6px;font-size:13px;color:#4b5563;line-height:1.45">{description}</div>
          <a href="{url}" style="display:inline-block;margin-top:10px;padding:7px 14px;background:#1f6feb;
             color:#ffffff;border-radius:6px;font-size:13px;text-decoration:none">Anzeige öffnen</a>
        </td>
      </tr>"""


def render_html(search: SearchConfig, listings: list[Listing], search_url: str) -> str:
    rows = "".join(_card(listing) for listing in listings)
    return f"""<!doctype html>
<html lang="de"><body style="margin:0;padding:24px;background:#f3f4f6;
  font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
  <table role="presentation" width="100%" style="max-width:640px;margin:0 auto;background:#ffffff;
    border-radius:10px;padding:24px;border-collapse:collapse">
    <tr><td>
      <div style="font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#6b7280">Kleinanzeigen Scanner</div>
      <h1 style="margin:6px 0 2px;font-size:20px;color:#111827">{html.escape(search.name)}</h1>
      <div style="font-size:13px;color:#6b7280">{len(listings)} neue Treffer</div>
    </td></tr>
    <tr><td><table role="presentation" width="100%" style="border-collapse:collapse">{rows}</table></td></tr>
    <tr><td style="padding-top:18px;font-size:12px;color:#9ca3af">
      <a href="{html.escape(search_url, quote=True)}" style="color:#6b7280">Suche im Browser öffnen</a>
    </td></tr>
  </table>
</body></html>"""


def render_text(search: SearchConfig, listings: list[Listing]) -> str:
    lines = [f"{search.name}: {len(listings)} neue Treffer", ""]
    for listing in listings:
        lines += [
            listing.title,
            f"  {listing.price_display}",
            f"  {listing.location} {listing.posted_text}".strip(),
            f"  {listing.url}",
            "",
        ]
    return "\n".join(lines)


class EmailNotifier:
    def __init__(self, config: SmtpConfig) -> None:
        self.config = config

    def _send(self, message: EmailMessage) -> None:
        cfg = self.config
        if not cfg.host:
            raise RuntimeError("SMTP host is not configured (check SMTP_HOST or smtp.host)")
        if not cfg.from_address:
            raise RuntimeError("SMTP sender is not configured (check SMTP_FROM or smtp.from_address)")
        context = ssl.create_default_context()
        if cfg.security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=30, context=context)
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=30)
        with server:
            server.ehlo()
            if cfg.security == "starttls":
                server.starttls(context=context)
                server.ehlo()
            if cfg.user:
                server.login(cfg.user, cfg.password)
            server.send_message(message)

    def _build(self, subject: str, recipients: Iterable[str], text: str, html_body: str) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((self.config.from_name, self.config.from_address))
        message["To"] = ", ".join(recipients)
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain="kleinanzeigen-scanner.local")
        message.set_content(text)
        message.add_alternative(html_body, subtype="html")
        return message

    def send_results(self, search: SearchConfig, listings: list[Listing], search_url: str) -> None:
        if not listings:
            return
        subject = f"[Kleinanzeigen] {len(listings)} neue Treffer – {search.name}"
        message = self._build(
            subject,
            search.recipients,
            render_text(search, listings),
            render_html(search, listings, search_url),
        )
        self._send(message)
        log.info("mail sent to %s (%d listings)", ", ".join(search.recipients), len(listings))

    def send_test(self, recipients: list[str]) -> None:
        message = self._build(
            "[Kleinanzeigen] Testmail",
            recipients,
            "SMTP-Konfiguration funktioniert.",
            "<p style='font-family:sans-serif'>SMTP-Konfiguration funktioniert. ✅</p>",
        )
        self._send(message)
        log.info("test mail sent to %s", ", ".join(recipients))
