"""One-process deployment boot: migrate, restrict DB role, seed and serve."""
import os

import psycopg
from psycopg.rows import dict_row
import uvicorn

from scripts.migrate import main as migrate
from scripts.provision_runtime import provision
from scripts.seed_demo import seed


def main():
    migrate()
    # Provision demo passwords with the migration owner, before switching to the
    # runtime role (which deliberately cannot change agent credentials).
    if os.environ.get('FRONTDESK_SEED_DEMO', 'false').lower() == 'true':
        with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as db:
            seed(db)
    password = os.environ.get('FRONTDESK_DB_PASSWORD')
    if password:
        os.environ['DATABASE_URL'] = provision(os.environ['DATABASE_URL'], password)
    elif os.environ.get('RENDER'):
        raise RuntimeError('FRONTDESK_DB_PASSWORD is required for hosted deployment')
    uvicorn.run('frontdesk.api:app', host='0.0.0.0', port=int(os.environ.get('PORT', '8000')))


if __name__ == '__main__':
    main()
