"""Send one message from a connected mailbox.

Replace the placeholders before running. Keys from Home start with ``afx_dev_``.
Connected-apps keys start with ``afx_live_``.
"""
from aifluxx_sdk import AifluxxClient

# Placeholder only. Paste the key Home showed you.
API_KEY = "afx_live_…"


def main() -> None:
    with AifluxxClient(api_key=API_KEY) as client:
        client.mail.send(
            from_="owner@example.com",
            to="colleague@example.com",
            subject="Q4 stock",
            body="Please find the note below.",
            business_id="<company uuid>",
        )


if __name__ == "__main__":
    main()
