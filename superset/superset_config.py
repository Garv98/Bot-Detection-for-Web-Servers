"""Superset runtime configuration for the BotDefense dashboard.

Mounted into the official Superset container at
``/app/pythonpath/superset_config.py`` via docker-compose.
"""

import os

# Honour the secret key set in docker-compose. Required by Flask/Superset.
SECRET_KEY = os.environ.get(
    "SUPERSET_SECRET_KEY",
    "change_me_in_prod_at_least_42_chars_long_aaaa",
)

# Superset 3.x blocks SQLite as a *data source* by default ("for security
# reasons"). The BotDefense analytics log is SQLite (intentional — it's a
# lab demo, not production), so opt back in.
PREVENT_UNSAFE_DB_CONNECTIONS = False
