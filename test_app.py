



import unittest
import os
import tempfile

import database
import app as ledgerline_app


class LedgerLineDepositTests(unittest.TestCase):

    def setUp(self):

        self.original_database = database.DATABASE

        temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.test_database = temp_file.name
        temp_file.close()

        database.DATABASE = self.test_database
        database.create_database()

        connection = database.get_connection()

        # Create sender user
        connection.execute("""
            INSERT INTO users (name, email, password_hash)
            VALUES (?, ?, ?)
        """, ("Test User", "deposit@test.com", "test_hash"))

        sender = connection.execute("""
            SELECT id FROM users
            WHERE email = ?
        """, ("deposit@test.com",)).fetchone()

        self.sender_id = sender["id"]

        # Create sender account
        connection.execute("""
            INSERT INTO accounts (account_number, user_id)
            VALUES (?, ?)
        """, ("LLDEPOSITTEST", self.sender_id))

        # Create recipient user
        connection.execute("""
            INSERT INTO users (name, email, password_hash)
            VALUES (?, ?, ?)
        """, ("Recipient User", "recipient@test.com", "test_hash"))

        recipient = connection.execute("""
            SELECT id FROM users
            WHERE email = ?
        """, ("recipient@test.com",)).fetchone()

        self.recipient_id = recipient["id"]

        # Create recipient account
        connection.execute("""
            INSERT INTO accounts (account_number, user_id)
            VALUES (?, ?)
        """, ("LLRECIPIENT01", self.recipient_id))

        connection.commit()
        connection.close()

        ledgerline_app.app.config["TESTING"] = True
        self.client = ledgerline_app.app.test_client()

        with self.client.session_transaction() as session:
            session["user_id"] = self.sender_id

    def tearDown(self):

        database.DATABASE = self.original_database

        if os.path.exists(self.test_database):
            os.remove(self.test_database)

    def get_balance(self):

        connection = database.get_connection()

        balance = connection.execute("""
            SELECT balance_paise
            FROM accounts
            WHERE account_number = ?
        """, ("LLDEPOSITTEST",)).fetchone()["balance_paise"]

        connection.close()
        return balance

    def get_transaction_count(self):

        connection = database.get_connection()

        count = connection.execute("""
            SELECT COUNT(*) AS total
            FROM transactions
        """).fetchone()["total"]

        connection.close()
        return count

    # DEPOSIT TESTS

    def test_zero_amount_rejected(self):

        response = self.client.post(
            "/deposit", data={"amount": "0"}
        )

        self.assertIn(
            b"Please enter a valid amount.",
            response.data
        )

        self.assertEqual(self.get_balance(), 0)
        self.assertEqual(self.get_transaction_count(), 0)

    def test_negative_amount_rejected(self):

        response = self.client.post(
            "/deposit", data={"amount": "-100"}
        )

        self.assertIn(
            b"Please enter a valid amount.",
            response.data
        )

        self.assertEqual(self.get_balance(), 0)
        self.assertEqual(self.get_transaction_count(), 0)

    def test_text_amount_rejected(self):

        response = self.client.post(
            "/deposit", data={"amount": "abc"}
        )

        self.assertIn(
            b"Please enter a valid amount.",
            response.data
        )

        self.assertEqual(self.get_balance(), 0)
        self.assertEqual(self.get_transaction_count(), 0)

    def test_more_than_two_decimal_places_rejected(self):

        response = self.client.post(
            "/deposit", data={"amount": "10.555"}
        )

        self.assertIn(
            b"Maximum two decimal places are allowed.",
            response.data
        )

        self.assertEqual(self.get_balance(), 0)
        self.assertEqual(self.get_transaction_count(), 0)

    def test_valid_amount_accepted(self):

        response = self.client.post(
            "/deposit", data={"amount": "10.50"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.get_balance(), 1050)
        self.assertEqual(self.get_transaction_count(), 1)

    # WITHDRAWAL TESTS

    def test_zero_withdrawal_rejected(self):

        response = self.client.post(
            "/withdraw", data={"amount": "0"}
        )

        self.assertIn(
            b"Please enter a valid amount.",
            response.data
        )

        self.assertEqual(self.get_balance(), 0)
        self.assertEqual(self.get_transaction_count(), 0)

    def test_negative_withdrawal_rejected(self):

        response = self.client.post(
            "/withdraw", data={"amount": "-10"}
        )

        self.assertIn(
            b"Please enter a valid amount.",
            response.data
        )

        self.assertEqual(self.get_balance(), 0)
        self.assertEqual(self.get_transaction_count(), 0)

    def test_text_withdrawal_rejected(self):

        response = self.client.post(
            "/withdraw", data={"amount": "abc"}
        )

        self.assertIn(
            b"Please enter a valid amount.",
            response.data
        )

        self.assertEqual(self.get_balance(), 0)
        self.assertEqual(self.get_transaction_count(), 0)

    def test_insufficient_balance_rejected(self):

        response = self.client.post(
            "/withdraw", data={"amount": "100"}
        )

        self.assertIn(
            b"Insufficient balance.",
            response.data
        )

        self.assertEqual(self.get_balance(), 0)
        self.assertEqual(self.get_transaction_count(), 0)

    def test_valid_withdrawal_accepted(self):

        connection = database.get_connection()

        connection.execute("""
            UPDATE accounts
            SET balance_paise = 5000
            WHERE account_number = ?
        """, ("LLDEPOSITTEST",))

        connection.commit()
        connection.close()

        response = self.client.post(
            "/withdraw", data={"amount": "20"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.get_balance(), 3000)
        self.assertEqual(self.get_transaction_count(), 1)

    # TRANSFER TESTS

    def test_valid_transfer(self):

        connection = database.get_connection()

        connection.execute("""
            UPDATE accounts
            SET balance_paise = 5000
            WHERE account_number = ?
        """, ("LLDEPOSITTEST",))

        connection.commit()
        connection.close()

        response = self.client.post("/transfer", data={
            "recipient_account": "LLRECIPIENT01",
            "amount": "20",
            "idempotency_key": "a" * 32
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.get_balance(), 3000)

        connection = database.get_connection()

        recipient_balance = connection.execute("""
            SELECT balance_paise
            FROM accounts
            WHERE account_number = ?
        """, ("LLRECIPIENT01",)).fetchone()["balance_paise"]

        connection.close()

        self.assertEqual(recipient_balance, 2000)
        self.assertEqual(self.get_transaction_count(), 1)

    def test_insufficient_transfer_balance(self):

        response = self.client.post("/transfer", data={
            "recipient_account": "LLRECIPIENT01",
            "amount": "100",
            "idempotency_key": "b" * 32
        })

        self.assertIn(
            b"Insufficient balance.",
            response.data
        )

        self.assertEqual(self.get_balance(), 0)
        self.assertEqual(self.get_transaction_count(), 0)

    def test_invalid_transfer_amount(self):

        response = self.client.post("/transfer", data={
            "recipient_account": "LLRECIPIENT01",
            "amount": "abc",
            "idempotency_key": "c" * 32
        })

        self.assertIn(
            b"Please enter a valid amount.",
            response.data
        )

        self.assertEqual(self.get_transaction_count(), 0)

    def test_unknown_recipient_rejected(self):

        connection = database.get_connection()

        connection.execute("""
            UPDATE accounts
            SET balance_paise = 5000
            WHERE account_number = ?
        """, ("LLDEPOSITTEST",))

        connection.commit()
        connection.close()

        response = self.client.post("/transfer", data={
            "recipient_account": "LLUNKNOWN123",
            "amount": "10",
            "idempotency_key": "d" * 32
        })

        self.assertIn(
            b"Recipient account not found.",
            response.data
        )

        self.assertEqual(self.get_balance(), 5000)
        self.assertEqual(self.get_transaction_count(), 0)

    def test_duplicate_transfer_rejected(self):

        connection = database.get_connection()

        connection.execute("""
            UPDATE accounts
            SET balance_paise = 5000
            WHERE account_number = ?
        """, ("LLDEPOSITTEST",))

        connection.commit()
        connection.close()

        transfer_data = {
            "recipient_account": "LLRECIPIENT01",
            "amount": "20",
            "idempotency_key": "e" * 32
        }

        first_response = self.client.post(
            "/transfer", data=transfer_data
        )

        self.assertEqual(first_response.status_code, 302)

        second_response = self.client.post(
            "/transfer", data=transfer_data
        )

        self.assertIn(
            b"This transfer has already been processed.",
            second_response.data
        )

        self.assertEqual(self.get_balance(), 3000)
        self.assertEqual(self.get_transaction_count(), 1)


if __name__ == "__main__":
    unittest.main()
