Extend the supplied Python 3 CLI. Return only the full updated contents of ledger.py.

Keep `python ledger.py show LEDGER` compatible with existing ledgers. A ledger is a
UTF-8 JSON array of transactions. Show prints one JSON object mapping account
names to their signed integer balances in cents.

Add `python ledger.py apply LEDGER BATCH`. LEDGER and BATCH are file paths.
For example, `python ledger.py apply ledger.json batch.json` reads both files.
The ledger stores transaction rows and stdout reports balances. BATCH has
the same JSON array format. Negative integers and zero are valid amounts. Each
transaction must have exactly three fields: a nonempty string id, a nonempty
string account, and an integer amount_cents (a JSON boolean is invalid).
Preserve existing rows and their order. Append new rows in first-seen batch order.
A repeated id with the same account and amount is a no-op, including across
invocations. A repeated id with different content is a conflict. An empty batch
is valid. On success, exit zero and print the same JSON balance object as show.
On a conflict or malformed batch, exit nonzero and leave the ledger byte-for-byte
unchanged, even if earlier rows in the same batch were valid. Use the standard
library and leave the batch and unrelated files untouched.
