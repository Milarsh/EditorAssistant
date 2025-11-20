import os, smtplib, ssl, threading
from email.message import EmailMessage

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "") or SMTP_USER or "no-reply@example.com"
SMTP_TLS  = os.getenv("SMTP_TLS", "true").lower() == "true"
SMTP_TIMEOUT = float(os.getenv("SMTP_TIMEOUT_SEC", "10"))
MAIL_STRICT = os.getenv("SMTP_STRICT", "false").lower() == "true"
MAIL_ASYNC  = os.getenv("SMTP_ASYNC",  "false").lower() == "true"

APP_NAME = os.getenv("APP_NAME", "Editor Assistant")

def _configured() -> bool:
    return bool(SMTP_HOST and SMTP_FROM)

def _send(msg: EmailMessage) -> None:
    if not _configured():
        print(f"[MAIL/DEV] To: {msg['To']} | Subject: {msg['Subject']}\n{msg.get_body(preferencelist=('plain',)).get_content()}")
        return

    try:
        if SMTP_TLS:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                if SMTP_USER:
                    smtp.login(SMTP_USER, SMTP_PASS)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT, context=ssl.create_default_context()) as smtp:
                if SMTP_USER:
                    smtp.login(SMTP_USER, SMTP_PASS)
                smtp.send_message(msg)
    except Exception as exception:
        print(f"[MAIL/ERROR] {type(exception).__name__}: {exception}")
        if MAIL_STRICT:
            raise

def send_email(to: str, subject: str, text: str, html: str | None = None) -> None:
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject

    if html:
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(text)

    if MAIL_ASYNC:
        threading.Thread(target=_send, args=(msg,), daemon=True).start()
    else:
        _send(msg)

# Email templates
def build_confirm_email(code: str, ttl_min: int) -> tuple[str, str, str]:
    subject = f"{APP_NAME}: код подтверждения почты"
    text = (
        f"Здравствуйте!\n\n"
        f"Ваш код подтверждения: {code}\n"
        f"Он истечёт через {ttl_min} минут.\n\n"
        f"Если вы не запрашивали этот код, просто игнорируйте письмо."
    )
    html = f"""
      <div style="font:14px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial">
        <h2 style="margin:0 0 12px">{APP_NAME}: код подтверждения</h2>
        <p>Ваш код:</p>
        <div style="font-size:24px;font-weight:700;letter-spacing:2px">{code}</div>
        <p style="color:#475569">Код истечёт через {ttl_min} минут.</p>
        <hr style="border:none;border-top:1px solid #e2e8f0;margin:16px 0">
        <p style="color:#64748b">Если вы не запрашивали этот код, просто игнорируйте письмо.</p>
      </div>
    """
    return subject, text, html

def build_reset_email(code: str, ttl_min: int) -> tuple[str, str, str]:
    subject = f"{APP_NAME}: код для сброса пароля"
    text = (
        f"Здравствуйте!\n\n"
        f"Код для сброса пароля: {code}\n"
        f"Он истечёт через {ttl_min} минут.\n\n"
        f"Если вы не запрашивали сброс, ничего не делайте."
    )
    html = f"""
      <div style="font:14px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial">
        <h2 style="margin:0 0 12px">{APP_NAME}: сброс пароля</h2>
        <p>Код для сброса:</p>
        <div style="font-size:24px;font-weight:700;letter-spacing:2px">{code}</div>
        <p style="color:#475569">Код истечёт через {ttl_min} минут.</p>
        <hr style="border:none;border-top:1px solid #e2e8f0;margin:16px 0">
        <p style="color:#64748b">Если вы не запрашивали сброс, ничего не делайте.</p>
      </div>
    """
    return subject, text, html