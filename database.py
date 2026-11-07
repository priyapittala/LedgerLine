

import sqlite3

DATABASE = "ledgerline.db"


def get_connection():

    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def create_database():

    connection = get_connection()

    connection.executescript("""

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'account_holder'
            CHECK(role IN ('admin', 'account_holder', 'auditor')),
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_number TEXT NOT NULL UNIQUE,
        user_id INTEGER NOT NULL,
        balance_paise INTEGER NOT NULL DEFAULT 0
            CHECK(balance_paise >= 0),
        status TEXT NOT NULL DEFAULT 'active'
            CHECK(status IN ('active', 'frozen', 'closed')),
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_type TEXT NOT NULL
            CHECK(transaction_type IN ('deposit', 'withdrawal', 'transfer')),
        amount_paise INTEGER NOT NULL CHECK(amount_paise > 0),
        from_account INTEGER,
        to_account INTEGER,
        idempotency_key TEXT NOT NULL UNIQUE,
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(from_account) REFERENCES accounts(id),
        FOREIGN KEY(to_account) REFERENCES accounts(id)
    );

    CREATE TABLE IF NOT EXISTS ledger_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        entry_type TEXT NOT NULL CHECK(entry_type IN ('debit', 'credit')),
        amount_paise INTEGER NOT NULL CHECK(amount_paise > 0),
        FOREIGN KEY(transaction_id) REFERENCES transactions(id),
        FOREIGN KEY(account_id) REFERENCES accounts(id)
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT NOT NULL,
        details TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE INDEX IF NOT EXISTS idx_accounts_user
    ON accounts(user_id);

    CREATE INDEX IF NOT EXISTS idx_ledger_account
    ON ledger_entries(account_id);

    CREATE INDEX IF NOT EXISTS idx_audit_user
    ON audit_logs(user_id);

    """)

        # Create an internal system user
    connection.execute("""
        INSERT OR IGNORE INTO users (
            name,
            email,
            password_hash,
            role
        )
        VALUES (?, ?, ?, ?)
    """, (
        "LedgerLine System",
        "system@ledgerline.internal",
        "SYSTEM_ACCOUNT_NO_LOGIN",
        "admin"
    ))

    # Find the internal system user
    system_user = connection.execute("""
        SELECT id
        FROM users
        WHERE email = ?
    """, ("system@ledgerline.internal",)).fetchone()

    # Create the internal system account
    connection.execute("""
        INSERT OR IGNORE INTO accounts (
            account_number,
            user_id,
            balance_paise,
            status
        )
        VALUES (?, ?, 0, 'active')
    """, ("LLSYSTEM0001", system_user["id"]))

    connection.commit()
    connection.close()

    print("LedgerLine database created successfully!")

if __name__ == "__main__":
    create_database()
