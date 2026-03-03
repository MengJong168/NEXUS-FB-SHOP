import imaplib
import email
from email.header import decode_header

class YandexMailClient:
    def __init__(self, username, password, target_email):
        self.username = username
        self.password = password
        self.target_email = target_email
        self.imap_server = "imap.yandex.ru"
        self.port = 993

    def get_code(self):
        GET_CODE = None
        try:
            mail = imaplib.IMAP4_SSL(self.imap_server, self.port)
            mail.login(self.username, self.password)
            mail.select("INBOX")

            status, messages = mail.search(None, f'(TO "{self.target_email}")')
            email_ids = messages[0].split()
            if not email_ids:
                return None

            latest_email_id = email_ids[-1]
            status, msg_data = mail.fetch(latest_email_id, "(RFC822)")

            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding if encoding else "utf-8")

                    GET_CODE = subject.split(' is your')[0].strip()

            mail.close()
            mail.logout()
        except Exception as e:
            print(f"Error in YandexMailClient.get_code: {e}")
            GET_CODE = None

        return GET_CODE
