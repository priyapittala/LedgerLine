


import unittest
import sqlite3
import os
import tempfile

import database


class LedgerLineDatabaseTests(unittest.TestCase):

    def setUp(self):
        self.original_database = database.DATABASE

        temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.test_database = temp_file.name
        temp_file.close()

        database.DATABASE = self.test_database
        database.create_database()

    def tearDown(self):
        database.DATABASE = self.original_database

        if os.path.exists(self.test_database):
            os.remove(self.test_database)

    def create_test_accounts(self, connection):

        connection.execute("""
            INSERT INTO users (name, email, password_hash)
            VALUES (?, ?, ?)
        """, ("Sender", "sender@example.com", "test_hash"))

        connection.execute("""
            INSERT INTO users (name, email, password_hash)
            VALUES (?, ?, ?)
        """, ("Recipient", "recipient@example.com", "test_hash"))

        connection.execute("""
            INSERT INTO accounts (account_number, user_id)
            VALUES (?, ?)
        """, ("LLSENDER001", 1))

        connection.execute("""
            INSERT INTO accounts (account_number, user_id)
            VALUES (?, ?)
        """, ("LLRECIPIENT01", 2))

    def test_duplicate_idempotency_key(self):

        connection = database.get_connection()

        try:
            self.create_test_accounts(connection)

            connection.execute("""
                INSERT INTO transactions (
                    transaction_type,
                    amount_paise,
                    from_account,
                    to_account,
                    idempotency_key,
                    description
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                "transfer", 100, 1, 2,
                "test_unique_key", "Test transfer"
            ))

            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("""
                    INSERT INTO transactions (
                        transaction_type,
                        amount_paise,
                        from_account,
                        to_account,
                        idempotency_key,
                        description
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    "transfer", 100, 1, 2,
                    "test_unique_key", "Duplicate transfer"
                ))

        finally:
            connection.close()

    def test_negative_balance_not_allowed(self):

        connection = database.get_connection()

        try:
            connection.execute("""
                INSERT INTO users (name, email, password_hash)
                VALUES (?, ?, ?)
            """, ("Test User", "balance@example.com", "test_hash"))

            connection.execute("""
                INSERT INTO accounts (account_number, user_id)
                VALUES (?, ?)
            """, ("LLTEST002", 1))

            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("""
                    UPDATE accounts
                    SET balance_paise = -100
                    WHERE account_number = ?
                """, ("LLTEST002",))

        finally:
            connection.close()

    def test_balanced_transfer_ledger_entries(self):

        connection = database.get_connection()

        try:
            self.create_test_accounts(connection)

            cursor = connection.execute("""
                INSERT INTO transactions (
                    transaction_type,
                    amount_paise,
                    from_account,
                    to_account,
                    idempotency_key,
                    description
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                "transfer", 2000, 1, 2,
                "balanced_transfer_001", "Test transfer"
            ))

            transaction_id = cursor.lastrowid

            connection.execute("""
                INSERT INTO ledger_entries (
                    transaction_id,
                    account_id,
                    entry_type,
                    amount_paise
                )
                VALUES (?, ?, ?, ?)
            """, (transaction_id, 1, "debit", 2000))

            connection.execute("""
                INSERT INTO ledger_entries (
                    transaction_id,
                    account_id,
                    entry_type,
                    amount_paise
                )
                VALUES (?, ?, ?, ?)
            """, (transaction_id, 2, "credit", 2000))

            totals = connection.execute("""
                SELECT
                    SUM(CASE WHEN entry_type = 'debit'
                        THEN amount_paise ELSE 0 END) AS total_debits,
                    SUM(CASE WHEN entry_type = 'credit'
                        THEN amount_paise ELSE 0 END) AS total_credits
                FROM ledger_entries
                WHERE transaction_id = ?
            """, (transaction_id,)).fetchone()

            self.assertEqual(totals["total_debits"], 2000)
            self.assertEqual(totals["total_credits"], 2000)
            self.assertEqual(
                totals["total_debits"],
                totals["total_credits"]
            )

        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
