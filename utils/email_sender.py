"""
Send an HTML email via SMTP (defaults to Gmail/TLS on port 587).

"""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class EmailSender:
    def __init__(
        self,
        *,
        sender: str | None = None,
        password: str | None = None,
        smtp_host: str | None = 'smtp.gmail.com',
        smtp_port: int | None = 587,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.sender = sender
        self.password = password

    def send(
        self,
        *,
        to: str | list[str],
        subject: str,
        html: str,
        plain_text: str | None = None,
    ) -> None:
        """Send an HTML email. ``to`` may be a single address or a list."""
        recipients = [to] if isinstance(to, str) else to

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = ", ".join(recipients)

        if plain_text:
            msg.attach(MIMEText(plain_text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        if not self.sender or not self.password:
            raise ValueError(
                "SMTP sender and password are required (e.g. set EMAIL_SENDER and "
                "EMAIL_PASSWORD and pass them into EmailSender)."
            )

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(self.sender, self.password)
            server.sendmail(self.sender, recipients, msg.as_string())
