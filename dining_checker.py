import smtplib
import os

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
_email_port_str = os.getenv("EMAIL_PORT") or "587"
EMAIL_PORT = int(_email_port_str)
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")


def send_email(to_email: str, subject: str, body: str) -> None:
    if not EMAIL_USER or not EMAIL_PASSWORD:
        raise RuntimeError("EMAIL_USER or EMAIL_PASSWORD not set")

    # Simple RFC 822 style message
    msg = (
        f"From: {EMAIL_USER}\r\n"
        f"To: {to_email}\r\n"
        f"Subject: {subject}\r\n"
        "\r\n"
        f"{body}"
    )

    # Open a real connection to Gmail
    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_USER, [to_email], msg)
