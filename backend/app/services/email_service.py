import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        self.smtp_host = None
        self.smtp_port = 587
        self.smtp_user = None
        self.smtp_pass = None
        self.from_email = "noreply@witnessreplay.com"
        self._configured = False
    
    def configure(self, host: str, port: int, user: str, password: str, from_email: str = None):
        self.smtp_host = host
        self.smtp_port = port
        self.smtp_user = user
        self.smtp_pass = password
        if from_email: self.from_email = from_email
        self._configured = True
        logger.info(f"Email service configured: {host}:{port}")
    
    @property
    def is_configured(self):
        return self._configured
    
    async def send_email(self, to: str, subject: str, body: str, html_body: str = None) -> bool:
        if not self._configured:
            logger.warning(f"Email not configured. Would send to {to}: {subject}")
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_email
            msg["To"] = to
            msg.attach(MIMEText(body, "plain"))
            if html_body: msg.attach(MIMEText(html_body, "html"))
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            logger.info(f"Email sent to {to}: {subject}")
            return True
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return False

email_service = EmailService()
