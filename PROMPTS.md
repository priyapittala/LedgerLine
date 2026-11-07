# LedgerLine – AI Usage Documentation

## AI Tools Used
ChatGPT was used as an assistance tool during development.

## Areas Where AI Assistance Was Used
- Understanding Flask routes and application structure.
- Designing SQLite database tables and relationships.
- Implementing registration and login with password hashing.
- Developing deposit, withdrawal and transfer functionality.
- Implementing double-entry ledger entries.
- Understanding transaction safety, commits and rollbacks.
- Debugging Python and SQL errors.
- Creating and running automated unit tests.
- Understanding Git and GitHub workflow.

## Testing and Verification
- Automated tests were executed using Python unittest.
- The test suite reported 18 passing tests.
- Deposit ledger entries were manually verified.
- Transfer ledger entries were manually verified.

## Developer Responsibility
AI suggestions were reviewed, tested and adapted during development. The developer is responsible for understanding and explaining the submitted implementation.
## Problems Encountered and Fixes

1. Fixed Git configuration and repository remote URL issues.
2. Corrected transfer test failures caused by assuming fixed database user IDs.
3. Improved amount validation using Python Decimal.
4. Added idempotency checks to prevent duplicate transfers.
5. Added double-entry ledger verification before committing transactions.

## Verification

- Automated tests executed successfully.
- Deposit transaction verified.
- Withdrawal transaction verified.
- Transfer transaction verified.
- Debit and credit entries checked for balance.