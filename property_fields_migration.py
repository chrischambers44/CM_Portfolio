#!/usr/bin/env python3
"""
Add financial fields to properties table.
Run once on the Pi after deploying updated models.py:
    docker exec portfolio python3 property_fields_migration.py
"""
import sys
sys.path.insert(0, '/app')

from app import app, db
from sqlalchemy import text

with app.app_context():
    fields = [
        ('value',    'REAL DEFAULT 0'),
        ('mortgage', 'REAL DEFAULT 0'),
        ('rate',     'REAL DEFAULT 0'),
        ('term',     'INTEGER DEFAULT 25'),
        ('rent',     'REAL DEFAULT 0'),
        ('costs',    'REAL DEFAULT 0'),
    ]
    conn = db.engine.connect()
    for col, typedef in fields:
        try:
            conn.execute(text(f'ALTER TABLE properties ADD COLUMN {col} {typedef}'))
            conn.commit()
            print(f'  Added column: {col}')
        except Exception as e:
            if 'duplicate column' in str(e).lower():
                print(f'  Already exists: {col}')
            else:
                print(f'  Error on {col}: {e}')
    conn.close()
    print('\nDone — property financial fields ready.')
