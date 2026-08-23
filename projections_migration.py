#!/usr/bin/env python3
"""
Add display_order and hidden fields to properties table.
Run once: docker exec portfolio python3 projections_migration.py
"""
import sys
sys.path.insert(0, '/app')
from app import app, db
from sqlalchemy import text

with app.app_context():
    fields = [
        ('display_order', 'INTEGER DEFAULT 0'),
        ('hidden',        'BOOLEAN DEFAULT 0'),
    ]
    conn = db.engine.connect()
    for col, typedef in fields:
        try:
            conn.execute(text(f'ALTER TABLE properties ADD COLUMN {col} {typedef}'))
            conn.commit()
            print(f'  Added: {col}')
        except Exception as e:
            if 'duplicate column' in str(e).lower():
                print(f'  Already exists: {col}')
            else:
                print(f'  Error: {e}')
    # Set initial display order from current id order
    conn.execute(text('UPDATE properties SET display_order = id WHERE display_order = 0'))
    conn.commit()
    conn.close()
    print('Done.')
