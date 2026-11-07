

import os
import secrets
import sqlite3
from functools import wraps
from decimal import Decimal, InvalidOperation

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session
)

from database import get_connection

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)


app = Flask(__name__)

app.secret_key = os.environ.get(
    "LEDGERLINE_SECRET_KEY",
    "local-development-only-secret"
)


# -----------------------------------------
# ROLE-BASED ACCESS CONTROL
# -----------------------------------------

def require_roles(*allowed_roles):

    def decorator(function):

        @wraps(function)
        def wrapper(*args, **kwargs):

            if "user_id" not in session:
                return redirect(url_for("login"))

            connection = get_connection()

            try:
                user = connection.execute("""
                    SELECT role
                    FROM users
                    WHERE id = ?
                """, (session["user_id"],)).fetchone()

            finally:
                connection.close()

            if user is None:
                session.clear()
                return redirect(url_for("login"))

            if user["role"] not in allowed_roles:
                return "Access denied: insufficient permissions.", 403

            return function(*args, **kwargs)

        return wrapper

    return decorator


# -----------------------------------------
# LEDGER VALIDATION
# -----------------------------------------

def validate_ledger_transaction(connection, transaction_id):

    result = connection.execute("""
        SELECT
            SUM(CASE WHEN entry_type = 'debit'
                THEN amount_paise ELSE 0 END) AS total_debits,
            SUM(CASE WHEN entry_type = 'credit'
                THEN amount_paise ELSE 0 END) AS total_credits,
            COUNT(*) AS entry_count
        FROM ledger_entries
        WHERE transaction_id = ?
    """, (transaction_id,)).fetchone()

    if result["entry_count"] < 2:
        raise ValueError(
            "Transaction must have at least two ledger entries."
        )

    if result["total_debits"] != result["total_credits"]:
        raise ValueError("Ledger transaction is not balanced.")

    return True


# -----------------------------------------
# HOME
# -----------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


# -----------------------------------------
# REGISTER
# -----------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():

    message = ""

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            message = "Please fill in all fields."

        elif len(password) < 8:
            message = "Password must contain at least 8 characters."

        else:

            password_hash = generate_password_hash(password)
            connection = get_connection()

            try:
                connection.execute("""
                    INSERT INTO users (name, email, password_hash)
                    VALUES (?, ?, ?)
                """, (name, email, password_hash))

                connection.commit()

                return redirect(url_for("login", registered=1))

            except sqlite3.IntegrityError:
                message = "This email is already registered."

            finally:
                connection.close()

    return render_template("register.html", message=message)


# -----------------------------------------
# LOGIN
# -----------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    message = ""

    if request.method == "GET" and request.args.get("registered"):
        message = "Registration successful! Please log in."

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        connection = get_connection()

        try:
            user = connection.execute(
                "SELECT * FROM users WHERE email = ?",
                (email,)
            ).fetchone()
        finally:
            connection.close()

        if user and check_password_hash(user["password_hash"], password):

            session.clear()
            session["user_id"] = user["id"]
            session["user_role"] = user["role"]

            return redirect(url_for("dashboard"))

        else:
            message = "Invalid email or password."

    return render_template("login.html", message=message)


# -----------------------------------------
# DASHBOARD
# -----------------------------------------

@app.route("/dashboard")
@require_roles("admin", "account_holder", "auditor")
def dashboard():

    connection = get_connection()

    try:
        user = connection.execute("""
            SELECT name, role
            FROM users
            WHERE id = ?
        """, (session["user_id"],)).fetchone()

        if user is None:
            session.clear()
            return redirect(url_for("login"))

        account = connection.execute("""
            SELECT account_number, balance_paise, status
            FROM accounts
            WHERE user_id = ?
            ORDER BY id
            LIMIT 1
        """, (session["user_id"],)).fetchone()

        transactions = connection.execute("""
            SELECT
                t.transaction_type,
                t.amount_paise,
                t.description,
                t.created_at
            FROM transactions t
            JOIN accounts a
            ON a.id = t.to_account OR a.id = t.from_account
            WHERE a.user_id = ?
            ORDER BY t.id DESC
            LIMIT 10
        """, (session["user_id"],)).fetchall()

    finally:
        connection.close()

    account_error = session.pop("account_creation_error", "")

    return render_template(
        "dashboard.html",
        name=user["name"],
        role=user["role"],
        account=account,
        account_error=account_error,
        transactions=transactions
    )


# -----------------------------------------
# CREATE BANK ACCOUNT
# -----------------------------------------

@app.route("/create-account", methods=["POST"])
@require_roles("account_holder")
def create_account():

    connection = get_connection()

    try:
        existing_account = connection.execute("""
            SELECT id
            FROM accounts
            WHERE user_id = ?
        """, (session["user_id"],)).fetchone()

        if existing_account:
            return redirect(url_for("dashboard"))

        account_created = False

        for attempt in range(5):

            account_number = "LL" + secrets.token_hex(5).upper()

            try:
                connection.execute("""
                    INSERT INTO accounts (account_number, user_id)
                    VALUES (?, ?)
                """, (account_number, session["user_id"]))

                connection.commit()
                account_created = True
                break

            except sqlite3.IntegrityError:
                connection.rollback()

    finally:
        connection.close()

    if not account_created:
        session["account_creation_error"] = (
            "Unable to create your account. Please try again."
        )

    return redirect(url_for("dashboard"))


# -----------------------------------------
# DEPOSIT
# -----------------------------------------

@app.route("/deposit", methods=["GET", "POST"])
@require_roles("account_holder")
def deposit():

    message = ""

    if request.method == "POST":

        raw_amount = request.form.get("amount", "").strip()

        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            message = "Please enter a valid amount."
            return render_template("deposit.html", message=message)

        if not amount.is_finite() or amount <= 0:
            message = "Please enter a valid amount."
            return render_template("deposit.html", message=message)

        if amount.as_tuple().exponent < -2:
            message = "Maximum two decimal places are allowed."
            return render_template("deposit.html", message=message)

        amount_paise = int(amount * 100)
        connection = get_connection()

        try:
            connection.execute("BEGIN IMMEDIATE")

            account = connection.execute("""
                SELECT id
                FROM accounts
                WHERE user_id = ?
                AND status = 'active'
                ORDER BY id
                LIMIT 1
            """, (session["user_id"],)).fetchone()

            if account is None:
                raise ValueError("No active account found.")

            system_account = connection.execute("""
                SELECT id
                FROM accounts
                WHERE account_number = ?
                AND status = 'active'
            """, ("LLSYSTEM0001",)).fetchone()

            if system_account is None:
                raise ValueError("System account not found.")

            idempotency_key = secrets.token_hex(16)

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
                "deposit",
                amount_paise,
                system_account["id"],
                account["id"],
                idempotency_key,
                "Money deposited"
            ))

            transaction_id = cursor.lastrowid

            update = connection.execute("""
                UPDATE accounts
                SET balance_paise = balance_paise + ?
                WHERE id = ?
                AND status = 'active'
            """, (amount_paise, account["id"]))

            if update.rowcount != 1:
                raise ValueError("Customer balance update failed.")

            connection.execute("""
                INSERT INTO ledger_entries (
                    transaction_id, account_id, entry_type, amount_paise
                )
                VALUES (?, ?, ?, ?)
            """, (
                transaction_id,
                system_account["id"],
                "debit",
                amount_paise
            ))

            connection.execute("""
                INSERT INTO ledger_entries (
                    transaction_id, account_id, entry_type, amount_paise
                )
                VALUES (?, ?, ?, ?)
            """, (
                transaction_id,
                account["id"],
                "credit",
                amount_paise
            ))

            connection.execute("""
                INSERT INTO audit_logs (user_id, action, details)
                VALUES (?, ?, ?)
            """, (
                session["user_id"],
                "DEPOSIT",
                f"Deposited Rs. {amount:.2f}"
            ))

            validate_ledger_transaction(connection, transaction_id)

            connection.commit()

            return redirect(url_for("dashboard"))

        except Exception as error:
            connection.rollback()
            print("DEPOSIT ERROR:", error)
            message = "Deposit failed. Please try again."

        finally:
            connection.close()

    return render_template("deposit.html", message=message)


# -----------------------------------------
# WITHDRAW
# -----------------------------------------

@app.route("/withdraw", methods=["GET", "POST"])
@require_roles("account_holder")
def withdraw():

    message = ""

    if request.method == "POST":

        raw_amount = request.form.get("amount", "").strip()

        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            message = "Please enter a valid amount."
            return render_template("withdraw.html", message=message)

        if not amount.is_finite() or amount <= 0:
            message = "Please enter a valid amount."
            return render_template("withdraw.html", message=message)

        if amount.as_tuple().exponent < -2:
            message = "Maximum two decimal places are allowed."
            return render_template("withdraw.html", message=message)

        amount_paise = int(amount * 100)
        connection = get_connection()

        try:
            connection.execute("BEGIN IMMEDIATE")

            account = connection.execute("""
                SELECT id
                FROM accounts
                WHERE user_id = ?
                AND status = 'active'
                ORDER BY id
                LIMIT 1
            """, (session["user_id"],)).fetchone()

            if account is None:
                raise ValueError("No active account found.")

            system_account = connection.execute("""
                SELECT id
                FROM accounts
                WHERE account_number = ?
                AND status = 'active'
            """, ("LLSYSTEM0001",)).fetchone()

            if system_account is None:
                raise ValueError("System account not found.")

            update = connection.execute("""
                UPDATE accounts
                SET balance_paise = balance_paise - ?
                WHERE id = ?
                AND status = 'active'
                AND balance_paise >= ?
            """, (amount_paise, account["id"], amount_paise))

            if update.rowcount != 1:
                raise ValueError("Insufficient balance.")

            idempotency_key = secrets.token_hex(16)

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
                "withdrawal",
                amount_paise,
                account["id"],
                system_account["id"],
                idempotency_key,
                "Money withdrawn"
            ))

            transaction_id = cursor.lastrowid

            connection.execute("""
                INSERT INTO ledger_entries (
                    transaction_id, account_id, entry_type, amount_paise
                )
                VALUES (?, ?, ?, ?)
            """, (
                transaction_id,
                account["id"],
                "debit",
                amount_paise
            ))

            connection.execute("""
                INSERT INTO ledger_entries (
                    transaction_id, account_id, entry_type, amount_paise
                )
                VALUES (?, ?, ?, ?)
            """, (
                transaction_id,
                system_account["id"],
                "credit",
                amount_paise
            ))

            connection.execute("""
                INSERT INTO audit_logs (user_id, action, details)
                VALUES (?, ?, ?)
            """, (
                session["user_id"],
                "WITHDRAWAL",
                f"Withdrawn Rs. {amount:.2f}"
            ))

            validate_ledger_transaction(connection, transaction_id)

            connection.commit()

            return redirect(url_for("dashboard"))

        except Exception as error:
            connection.rollback()
            print("WITHDRAWAL ERROR:", error)

            if str(error) == "Insufficient balance.":
                message = "Insufficient balance."
            else:
                message = "Withdrawal failed. Please try again."

        finally:
            connection.close()

    return render_template("withdraw.html", message=message)


# -----------------------------------------
# TRANSFER
# -----------------------------------------

@app.route("/transfer", methods=["GET", "POST"])
@require_roles("account_holder")
def transfer():

    message = ""

    if request.method == "GET":
        idempotency_key = secrets.token_hex(16)

        return render_template(
            "transfer.html",
            message=message,
            idempotency_key=idempotency_key
        )

    submitted_key = request.form.get(
        "idempotency_key", ""
    ).strip()

    if len(submitted_key) != 32:
        return render_template(
            "transfer.html",
            message="Invalid transfer request. Please try again.",
            idempotency_key=secrets.token_hex(16)
        )

    recipient_account = request.form.get(
        "recipient_account", ""
    ).strip().upper()

    raw_amount = request.form.get("amount", "").strip()

    if not recipient_account:
        return render_template(
            "transfer.html",
            message="Please enter the recipient account number.",
            idempotency_key=secrets.token_hex(16)
        )

    try:
        amount = Decimal(raw_amount)

        if not amount.is_finite() or amount <= 0:
            raise ValueError("Invalid amount")

        if amount.as_tuple().exponent < -2:
            raise ValueError("Too many decimal places")

        amount_paise = int(amount * 100)

    except (InvalidOperation, ValueError):
        return render_template(
            "transfer.html",
            message="Please enter a valid amount.",
            idempotency_key=secrets.token_hex(16)
        )

    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        existing_transaction = connection.execute("""
            SELECT id
            FROM transactions
            WHERE idempotency_key = ?
        """, (submitted_key,)).fetchone()

        if existing_transaction:
            connection.rollback()

            return render_template(
                "transfer.html",
                message="This transfer has already been processed.",
                idempotency_key=secrets.token_hex(16)
            )

        sender = connection.execute("""
            SELECT id, account_number, user_id
            FROM accounts
            WHERE user_id = ?
            AND status = 'active'
            ORDER BY id
            LIMIT 1
        """, (session["user_id"],)).fetchone()

        recipient = connection.execute("""
            SELECT id, account_number, user_id
            FROM accounts
            WHERE account_number = ?
            AND status = 'active'
        """, (recipient_account,)).fetchone()

        if sender is None:
            raise ValueError("No active sender account found.")

        if recipient is None:
            raise ValueError("Recipient account not found.")

        if sender["id"] == recipient["id"]:
            raise ValueError("You cannot transfer money to your own account.")

        debit = connection.execute("""
            UPDATE accounts
            SET balance_paise = balance_paise - ?
            WHERE id = ?
            AND status = 'active'
            AND balance_paise >= ?
        """, (amount_paise, sender["id"], amount_paise))

        if debit.rowcount != 1:
            raise ValueError("Insufficient balance.")

        credit = connection.execute("""
            UPDATE accounts
            SET balance_paise = balance_paise + ?
            WHERE id = ?
            AND status = 'active'
        """, (amount_paise, recipient["id"]))

        if credit.rowcount != 1:
            raise ValueError("Recipient credit failed.")

        transaction = connection.execute("""
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
            "transfer",
            amount_paise,
            sender["id"],
            recipient["id"],
            submitted_key,
            "Money transferred"
        ))

        transaction_id = transaction.lastrowid

        connection.execute("""
            INSERT INTO ledger_entries (
                transaction_id, account_id, entry_type, amount_paise
            )
            VALUES (?, ?, ?, ?)
        """, (
            transaction_id,
            sender["id"],
            "debit",
            amount_paise
        ))

        connection.execute("""
            INSERT INTO ledger_entries (
                transaction_id, account_id, entry_type, amount_paise
            )
            VALUES (?, ?, ?, ?)
        """, (
            transaction_id,
            recipient["id"],
            "credit",
            amount_paise
        ))

        connection.execute("""
            INSERT INTO audit_logs (user_id, action, details)
            VALUES (?, ?, ?)
        """, (
            session["user_id"],
            "TRANSFER",
            f"Transferred Rs. {amount:.2f} to {recipient_account}"
        ))

        validate_ledger_transaction(connection, transaction_id)

        connection.commit()

        return redirect(url_for("dashboard"))

    except Exception as error:
        connection.rollback()
        print("TRANSFER ERROR:", error)

        return render_template(
            "transfer.html",
            message=str(error),
            idempotency_key=secrets.token_hex(16)
        )

    finally:
        connection.close()


# -----------------------------------------
# LOGOUT
# -----------------------------------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# -----------------------------------------
# RUN APPLICATION
# -----------------------------------------

if __name__ == "__main__":
    app.run(debug=False)
