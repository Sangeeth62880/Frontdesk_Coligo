"""Provision one agent. Email and password are read from stdin, never argv."""
import getpass
import os
import sys

import psycopg

from frontdesk.auth import hash_password


def set_password(db, email, password):
    if not password:
        raise ValueError('Password must not be empty')
    row = db.execute('UPDATE agents SET password_hash=%s WHERE email=%s RETURNING id',
                     (hash_password(password), email.strip().lower())).fetchone()
    if not row:
        raise ValueError('Unknown agent email')
    db.execute('UPDATE agent_sessions SET revoked_at=clock_timestamp() WHERE agent_id=%s AND revoked_at IS NULL', (row[0],))


def main():
    email = input('Agent email: ') if sys.stdin.isatty() else sys.stdin.readline().rstrip('\n')
    password = getpass.getpass('Password: ') if sys.stdin.isatty() else sys.stdin.readline().rstrip('\n')
    with psycopg.connect(os.environ['DATABASE_URL']) as db:
        set_password(db, email, password)
    print('Agent password set; existing sessions revoked')


if __name__ == '__main__':
    main()
