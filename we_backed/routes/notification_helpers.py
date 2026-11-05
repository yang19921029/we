def add_notification(cursor, recipient, title, body, link=""):
    if recipient:
        cursor.execute(
            """
            INSERT INTO notifications (recipient, title, body, link)
            VALUES (%s, %s, %s, %s)
            """,
            (recipient, title, body, link),
        )
