"""One-process deployment boot: migrate, restrict DB role, seed and serve."""
import json
import logging
import os

import psycopg
import uvicorn
from psycopg.rows import dict_row

from scripts.maintain_demo import from_environment as maintain_demo
from scripts.migrate import main as migrate
from scripts.provision_runtime import provision, verify_runtime
from scripts.seed_demo import seed


def main():
    required = ["DATABASE_URL"]
    if os.environ.get("RENDER"):
        required.extend(["FRONTDESK_DB_PASSWORD", "FRONTDESK_SWEEP_TOKEN"])
    if os.environ.get("FRONTDESK_SEED_DEMO", "false").lower() == "true":
        required.append("FRONTDESK_DEMO_PASSWORD")
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError("Missing required settings: " + ", ".join(missing))
    logging.basicConfig(level=os.environ.get("FRONTDESK_LOG_LEVEL", "INFO"), format="%(message)s")
    maintain_demo()
    migrate()
    # Provision demo passwords with the migration owner, before switching to the
    # runtime role (which deliberately cannot change agent credentials).
    if os.environ.get('FRONTDESK_SEED_DEMO', 'false').lower() == 'true':
        with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as db:
            seed(db)
    password = os.environ.get('FRONTDESK_DB_PASSWORD')
    if password:
        os.environ['DATABASE_URL'] = provision(os.environ['DATABASE_URL'], password)
        logging.getLogger('frontdesk.startup').info(json.dumps(verify_runtime(os.environ['DATABASE_URL'])))
    elif os.environ.get('RENDER'):
        raise RuntimeError('FRONTDESK_DB_PASSWORD is required for hosted deployment')
    uvicorn.run('frontdesk.api:app', host='0.0.0.0', port=int(os.environ.get('PORT', '8000')), access_log=False)


if __name__ == '__main__':
    main()
