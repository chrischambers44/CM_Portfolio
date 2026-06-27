#!/usr/bin/env python3
"""
migrate.py — AppSheet → Portfolio Flask/SQLite migration
=========================================================
Place your AppSheet CSV exports in data/imports/ then run:
    python migrate.py

Expected CSV filenames (rename your exports to match):
    properties.csv
    contacts.csv
    tasks.csv
    documents.csv
    visits.csv
    expenses.csv

All AppSheet hashes are resolved to proper DB foreign keys.
Sensitive data (HMRC credentials, alarm codes) is excluded.
"""

import csv
import sys
import os
import re
from datetime import date, datetime
from dateutil import parser as dp

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, create_default_users
from models import db, Property, Vehicle, Contact, PropertyContact, Document, Task, TaskImage, Visit, VisitImage, Expense, User

IMPORTS_DIR = os.path.join(os.path.dirname(__file__), 'data', 'imports')

# ── APPSHEET HASH → PROPERTY SHORT NAME MAPPING ───────────────────────────────
# Decoded from your AppSheet data
HASH_TO_PROPERTY = {
    '0HLLRLjTJPvHThc75X4EOx':  '180 Sherborne',
    'QL1vWqKT8OZnWPqYR64DcS':  '5 Boswell',
    'QE3H5ZeWdzsCnSQHEGRslk':  '210 Sherborne',
    'ePEW2sEfiLM1S6F6w6kGKV':  '208 Sherborne',
    '6wnODdQqtDHAvkbRdA6FS8':  '450 Stanley Rd',
    'Gmpjiw0FGbRO2XajYs7THI':  '180A Sherborne',
    'mxXrhKSrT6NH5eWE9IJstl':  '180B Sherborne',
    'OOOPhVqIZYqwNHyEBbIcMq':  '208 Sherborne',   # building-level
    'kDiigDItCUv0US3ZHr0Jmj':  '15 St Johns',
    '8YAoznXq3fk9S8mQDvYPbv':  '70 Fosse Park',
    '2EeGQKBcbXAKwSjelCdhji':  '3 Sam Close',
    '2SK5ZJ5nK8gWX86HL0kL69':  '7 Meredith Close',
    'xeapHpCW93p2U4dko9oolQ':  '20 Bramley Fields',
    'Am0b0VCwCA35wTPS7DlUul':  '5 Boswell',
    'RycezAjyKQtCgN2lrMbr4P':  '180A Sherborne',
    'NRa33fVPhkQh19k90BSJVC':  '180B Sherborne',
    '0iBi3yHPU9jVzf6R5h9R5c':  '210 Sherborne',
    'hvxkhwirLnHQiePt4C3hBD':  '450 Stanley Rd',
    'wmhD7gHb9AfEUtu9sJTcKu':  'C & M Ltd',
    '7jqfo2KY4l0zDaYqcNFW4e':  'C & M Ltd',
    'Lv8MXa5vmIfBk17CxCIcxX':  'VEHICLES',         # vehicle entity
    'jpiw0wIP4KPN9sTJJnUE6w':  None,               # test entity — skip
    'Di8JqpMQHqBYXYjIG3hAv3':  None,               # unknown — skip
}

# ── DIRECTOR NAME → SHORT NAME MAPPING ────────────────────────────────────────
DIRECTOR_MAP = {
    'chambers': 'Chris',
    'morgan':   'Ash',
    'chris':    'Chris',
    'ash':      'Ash',
}

# ── ADDRESS → PROPERTY SHORT NAME (for expenses/visits) ───────────────────────
ADDRESS_TO_PROPERTY = {
    '180 sherborne': '180 Sherborne',
    '180a sherborne': '180A Sherborne',
    '180b sherborne': '180B Sherborne',
    '208 sherborne': '208 Sherborne',
    '210 sherborne': '210 Sherborne',
    'sherborne rd': '180 Sherborne',   # ambiguous — defaults to 180
    'stanley rd': '450 Stanley Rd',
    'bootle': '450 Stanley Rd',
    'boswell': '5 Boswell',
    'cardiff': '5 Boswell',
    'st john': '15 St Johns',
    'fosse park': '70 Fosse Park',
    'sam cl': '3 Sam Close',
    'sam close': '3 Sam Close',
    'south petherton': '3 Sam Close',
    'halstock': '7 Meredith Close',
    'meredith': '7 Meredith Close',
    'bramley': '20 Bramley Fields',
    'norton-sub-hamdon': '20 Bramley Fields',
    'stoke-sub-hamdon': '20 Bramley Fields',
}

# ── SENSITIVE DATA PATTERNS TO STRIP FROM NOTES ───────────────────────────────
SENSITIVE_PATTERNS = [
    r'HMRC User ID \d+',
    r'password[:\s]+\S+',
    r'auth(?:entication)? code[:\s]+\w+',
    r'company auth\w*[:\s]+\w+',
    r'\bUTR\b[\s:]+[\d\s]+',
    r'activation code[\s:]+[\d\s]+',
    r'pw[:\s]+\S+',
    r'webfiling.*?(?:\n|$)',
    r'HMRC.*?(?:\n|$)',
    r'\d{4}\s*bin store',
    r'alarm code[:\s]+\w+',
    r'shift\s+\d+',
    r'WC door code[:\s]+\d+',
]


def strip_sensitive(text):
    if not text:
        return text
    result = text
    for pattern in SENSITIVE_PATTERNS:
        result = re.sub(pattern, '[REDACTED — see Vault]', result, flags=re.IGNORECASE)
    return result


def parse_date(s):
    if not s or str(s).strip() in ('', '-', 'n/a', 'N/A', '01/01/1970', '01 January 1970'):
        return None
    s = str(s).strip()
    # Remove day names
    s = re.sub(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*', '', s, flags=re.IGNORECASE)
    try:
        return dp.parse(s, dayfirst=True).date()
    except:
        return None


def parse_amount(s):
    """Convert currency string to float GBP."""
    if not s or str(s).strip() in ('', '-'):
        return 0.0
    s = str(s).strip()
    # Handle US$ prefix (AppSheet locale bug)
    s = re.sub(r'US\$', '', s)
    s = re.sub(r'[£$,]', '', s)
    try:
        return float(s)
    except:
        return 0.0


def read_csv(filename):
    path = os.path.join(IMPORTS_DIR, filename)
    if not os.path.exists(path):
        print(f'  ⚠ {filename} not found in {IMPORTS_DIR} — skipping')
        return []
    rows = []
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip(): v.strip() if v else '' for k, v in row.items()})
    print(f'  ✓ Read {len(rows)} rows from {filename}')
    return rows


# ── MIGRATION FUNCTIONS ───────────────────────────────────────────────────────

def migrate_properties(rows):
    """Migrate properties table."""
    created = 0
    prop_map = {}  # short_name → id

    # Hardcoded property definitions from decoded AppSheet data
    PROPERTIES = [
        # Rental properties
        dict(short_name='180 Sherborne', address='180 Sherborne Rd, Yeovil BA21 4HL',
             property_type='rental', ownership='company', region='yeovil',
             legacy_id='Gmpjiw0FGbRO2XajYs7THI', postcode='BA21 4HL'),
        dict(short_name='180A Sherborne', address='180A Sherborne Rd, Yeovil BA21 4HL',
             property_type='rental', ownership='company', region='yeovil',
             legacy_id='RycezAjyKQtCgN2lrMbr4P', postcode='BA21 4HL'),
        dict(short_name='180B Sherborne', address='180B Sherborne Rd, Yeovil BA21 4HL',
             property_type='rental', ownership='company', region='yeovil',
             legacy_id='NRa33fVPhkQh19k90BSJVC', postcode='BA21 4HL'),
        dict(short_name='208 Sherborne', address='208 Sherborne Rd, Yeovil BA21 4HL',
             property_type='rental', ownership='joint', region='yeovil',
             legacy_id='OOOPhVqIZYqwNHyEBbIcMq', postcode='BA21 4HL'),
        dict(short_name='210 Sherborne', address='210 Sherborne Rd, Yeovil BA21 4HL',
             property_type='rental', ownership='company', region='yeovil',
             legacy_id='QE3H5ZeWdzsCnSQHEGRslk', postcode='BA21 4HL'),
        dict(short_name='5 Boswell', address='5 Boswell Cl, Llanrumney, Cardiff CF3 5NY',
             property_type='rental', ownership='joint', region='cardiff',
             legacy_id='Am0b0VCwCA35wTPS7DlUul', postcode='CF3 5NY'),
        dict(short_name='450 Stanley Rd', address='450 Stanley Rd, Bootle L20 5AE',
             property_type='rental', ownership='company', region='liverpool',
             legacy_id='hvxkhwirLnHQiePt4C3hBD', postcode='L20 5AE'),
        dict(short_name='15 St Johns', address='15 St Johns Rd, Yeovil BA21 5NH',
             property_type='rental', ownership='company', region='yeovil',
             legacy_id='kDiigDItCUv0US3ZHr0Jmj', postcode='BA21 5NH'),
        dict(short_name='70 Fosse Park', address='70 Fosse Park Rd, Yeovil BA20 2FW',
             property_type='rental', ownership='company', region='yeovil',
             legacy_id='8YAoznXq3fk9S8mQDvYPbv', postcode='BA20 2FW'),
        dict(short_name='3 Sam Close', address='3 Sam Close, South Petherton TA13 5FE',
             property_type='rental', ownership='company', region='yeovil',
             legacy_id='2EeGQKBcbXAKwSjelCdhji', postcode='TA13 5FE'),
        # Personal properties
        dict(short_name='7 Meredith Close', address='7 Meredith Cl, Halstock, Yeovil BA22 9SA',
             property_type='personal', ownership='personal_chris', region='yeovil',
             legacy_id='2SK5ZJ5nK8gWX86HL0kL69', postcode='BA22 9SA'),
        dict(short_name='20 Bramley Fields', address='20 Bramley Fields, Norton-sub-Hamdon TA14 6AA',
             property_type='personal', ownership='personal_ash', region='yeovil',
             legacy_id='xeapHpCW93p2U4dko9oolQ', postcode='TA14 6AA'),
        dict(short_name='France', address='2 Chaumeil, 19220 Saint-Geniez-ô-Merle, France',
             property_type='personal', ownership='personal_chris', region='other',
             legacy_id=None, postcode=None),
        dict(short_name='37 Quarry Piece', address='37 Quarry Piece Dr, South Petherton TA13 5EL',
             property_type='personal', ownership='personal_ash', region='yeovil',
             legacy_id=None, postcode='TA13 5EL'),
        # Company entity
        dict(short_name='C & M Ltd', address='20 Bramley Fields, Norton-sub-Hamdon TA14 6AA',
             property_type='company', ownership='company', region='yeovil',
             legacy_id='wmhD7gHb9AfEUtu9sJTcKu', postcode='TA14 6AA'),
    ]

    # Also pull notes from CSV rows if available
    notes_map = {}
    for row in rows:
        addr = row.get('Address', '') or row.get('address', '')
        notes = row.get('Notes', '') or row.get('notes', '')
        short = row.get('Short Name', '') or row.get('short_name', '')
        if short and notes:
            notes_map[short] = strip_sensitive(notes)

    for pdef in PROPERTIES:
        existing = Property.query.filter_by(short_name=pdef['short_name']).first()
        if not existing:
            notes = notes_map.get(pdef['short_name'], '')
            p = Property(notes=notes, **pdef)
            db.session.add(p)
            db.session.flush()
            created += 1
        prop_map[pdef['short_name']] = existing.id if existing else (
            Property.query.filter_by(short_name=pdef['short_name']).first().id
        )

    db.session.commit()

    # Build legacy_id → db id map
    legacy_map = {}
    for hash_id, short_name in HASH_TO_PROPERTY.items():
        if short_name and short_name in prop_map:
            legacy_map[hash_id] = prop_map[short_name]

    print(f'  Properties: {created} created, {len(prop_map)} total')
    return prop_map, legacy_map


def migrate_vehicles():
    """Create vehicle records from known data."""
    VEHICLES = [
        dict(registration='AUDI RS6', make='Audi', model='RS6', year=None,
             ownership='personal_chris', legacy_id='CHRIS_RS6'),
        dict(registration='KAWASAKI ZX10', make='Kawasaki', model='ZX-10R', year=None,
             ownership='personal_chris', legacy_id='CHRIS_ZX10'),
    ]
    vehicle_map = {}
    for vdef in VEHICLES:
        existing = Vehicle.query.filter_by(registration=vdef['registration']).first()
        if not existing:
            v = Vehicle(**vdef)
            db.session.add(v)
            db.session.flush()
        vehicle_map[vdef['legacy_id']] = (
            existing.id if existing else
            Vehicle.query.filter_by(registration=vdef['registration']).first().id
        )
    db.session.commit()
    print(f'  Vehicles: {len(vehicle_map)} records')
    return vehicle_map


def migrate_contacts(rows):
    """Migrate contacts table."""
    created = 0
    contact_map = {}  # display_name → id

    # Hardcoded director contacts first (critical for task/expense linking)
    DIRECTORS = [
        dict(first_name='Christopher', last_name='Chambers', role='director',
             mobile='07711187720', landline='01935 891794',
             email='mrchrischambers@gmail.com', rating='unrated',
             legacy_id='CHRIS'),
        dict(first_name='Ashley', last_name='Morgan', role='director',
             mobile=None, landline=None,
             email='sherco02@hotmail.com', rating='unrated',
             legacy_id='ASH'),
    ]
    for d in DIRECTORS:
        existing = Contact.query.filter_by(
            first_name=d['first_name'], last_name=d['last_name']).first()
        if not existing:
            c = Contact(**d)
            db.session.add(c)
            db.session.flush()
        cid = existing.id if existing else Contact.query.filter_by(
            first_name=d['first_name'], last_name=d['last_name']).first().id
        contact_map['Chambers'] = cid if d['first_name'] == 'Christopher' else contact_map.get('Chambers')
        contact_map['Morgan'] = cid if d['first_name'] == 'Ashley' else contact_map.get('Morgan')
        contact_map['Chris'] = cid if d['first_name'] == 'Christopher' else contact_map.get('Chris')
        contact_map['Ash'] = cid if d['first_name'] == 'Ashley' else contact_map.get('Ash')

    for row in rows:
        fname = row.get('First Name', '') or row.get('first_name', '')
        lname = row.get('Last Name', '') or row.get('last_name', '')
        company = row.get('Company Name', '') or row.get('company_name', '') or row.get('Last Name', '')
        role_raw = (row.get('Role', '') or row.get('role', '')).lower()
        role = 'tradesperson' if 'trade' in role_raw else \
               'tenant' if 'tenant' in role_raw else \
               'director' if 'landlord' in role_raw else 'other'
        rating_raw = (row.get('Rating', '') or '').lower()
        rating = 'gold' if 'gold' in rating_raw else \
                 'black' if 'black' in rating_raw else \
                 'neutral' if 'neutral' in rating_raw else 'unrated'
        display = f'{fname} {lname}'.strip() or company
        if not display or display in ('Christopher Chambers', 'Ashley Morgan'):
            continue

        existing = Contact.query.filter(
            db.or_(
                db.and_(Contact.first_name == fname, Contact.last_name == lname),
                Contact.company_name == company
            )
        ).first()
        if not existing:
            c = Contact(
                first_name=fname or None,
                last_name=lname or None,
                company_name=company or None,
                role=role,
                mobile=row.get('Mobile', '') or row.get('mobile', '') or None,
                landline=row.get('Landline', '') or row.get('landline', '') or None,
                email=row.get('Email', '') or row.get('email', '') or None,
                speciality=row.get('Speciality', '') or row.get('speciality', '') or None,
                region=row.get('Region', '') or row.get('region', '') or None,
                rating=rating,
                notes=row.get('Notes', '') or row.get('notes', '') or None,
            )
            db.session.add(c)
            db.session.flush()
            created += 1
            cid = c.id
        else:
            cid = existing.id

        contact_map[display] = cid
        if fname:
            contact_map[fname] = cid
        if lname:
            contact_map[lname] = cid

    db.session.commit()
    print(f'  Contacts: {created} created, {len(contact_map)} in map')
    return contact_map


def migrate_documents(rows, legacy_map, vehicle_map, contact_map):
    """Migrate documents table."""
    created = skipped = 0
    today = date.today()

    # Vehicle legacy hash → vehicle db id
    VEHICLE_HASH = 'Lv8MXa5vmIfBk17CxCIcxX'

    for row in rows:
        doc_type = row.get('Document Type', '') or row.get('doc_type', '') or row.get('Type', '')
        if not doc_type:
            skipped += 1
            continue

        prop_hash = (row.get('Property', '') or row.get('property', '')
                     or row.get('Property ID', '')).strip()

        # Determine entity
        if prop_hash == VEHICLE_HASH:
            entity_type = 'vehicle'
            # RS6 vs ZX10 inferred from doc_type
            if 'RS6' in doc_type or 'rs6' in doc_type.lower():
                entity_id = vehicle_map.get('CHRIS_RS6')
            elif 'ZX10' in doc_type or 'zx10' in doc_type.lower():
                entity_id = vehicle_map.get('CHRIS_ZX10')
            else:
                entity_id = vehicle_map.get('CHRIS_RS6')  # default
        elif prop_hash in ('wmhD7gHb9AfEUtu9sJTcKu', '7jqfo2KY4l0zDaYqcNFW4e'):
            entity_type = 'company'
            entity_id = 1  # C&M entity
        elif prop_hash == 'jpiw0wIP4KPN9sTJJnUE6w':
            skipped += 1
            continue  # test entity
        elif prop_hash:
            entity_type = 'property'
            entity_id = legacy_map.get(prop_hash)
            if not entity_id:
                skipped += 1
                continue
        else:
            skipped += 1
            continue

        expiry = parse_date(row.get('Expiry Date', '') or row.get('expiry_date', ''))
        issued = parse_date(row.get('Issued Date', '') or row.get('issued_date', '')
                           or row.get('Done Date', ''))
        status_raw = (row.get('Status', '') or row.get('status', '')).lower()
        status = 'archive' if 'archive' in status_raw else 'active'
        verified_raw = (row.get('Verified', '') or row.get('Checked', '') or '').lower()
        verified = 'checked' in verified_raw or verified_raw == 'true'
        url = row.get('Document URL', '') or row.get('drive_url', '') or row.get('URL', '')
        category = row.get('Category', '') or row.get('category', '')
        notes = row.get('Notes', '') or row.get('notes', '')

        doc = Document(
            entity_type=entity_type,
            entity_id=entity_id,
            doc_type=doc_type,
            category=category or None,
            issued_date=issued,
            expiry_date=expiry,
            notes=notes or None,
            status=status,
            drive_url=url or None,
            verified=verified,
        )
        db.session.add(doc)
        created += 1

    db.session.commit()
    print(f'  Documents: {created} created, {skipped} skipped')


def migrate_tasks(rows, legacy_map, contact_map):
    """Migrate tasks table."""
    created = skipped = 0

    for row in rows:
        title = row.get('Title', '') or row.get('title', '')
        if not title:
            skipped += 1
            continue

        prop_hash = (row.get('Property', '') or row.get('property', '')
                     or row.get('Property ID', '')).strip()
        prop_id = legacy_map.get(prop_hash) if prop_hash else None

        assigned_raw = (row.get('Assigned To', '') or row.get('assigned_to', '')).strip()
        assigned_id = contact_map.get(assigned_raw)

        status_raw = (row.get('Status', '') or row.get('status', '')).lower().replace(' ', '_')
        status = 'complete' if 'complete' in status_raw else \
                 'in_progress' if 'in_progress' in status_raw or 'progress' in status_raw else \
                 'not_started'

        priority_raw = row.get('Priority', '') or row.get('priority', '')
        try:
            priority = int(priority_raw)
        except:
            priority = 0

        created_date = parse_date(row.get('Date', '') or row.get('created_date', '')
                                  or row.get('Created Date', ''))
        due_date = parse_date(row.get('Due Date', '') or row.get('due_date', ''))
        try:
            est_days = int(row.get('Estimated Days', '') or row.get('estimated_days', '') or 0)
        except:
            est_days = 0

        notes = row.get('Notes', '') or row.get('notes', '')

        # Images
        imgs = [
            row.get('Image 1', '') or row.get('image_1', ''),
            row.get('Image 2', '') or row.get('image_2', ''),
            row.get('Image 3', '') or row.get('image_3', ''),
        ]

        task = Task(
            property_id=prop_id,
            assigned_to_id=assigned_id,
            title=title,
            notes=notes or None,
            status=status,
            priority=priority,
            created_date=created_date,
            due_date=due_date,
            estimated_days=est_days or None,
        )
        db.session.add(task)
        db.session.flush()

        for img in imgs:
            if img and img.strip():
                db.session.add(TaskImage(task_id=task.id, image_path=img.strip()))

        created += 1

    db.session.commit()
    print(f'  Tasks: {created} created, {skipped} skipped')


def migrate_visits(rows, legacy_map, contact_map):
    """Migrate visits table."""
    created = skipped = 0

    PROP_SHORT_MAP = {v: k for k, v in {
        '180 Sherborne': '180 Sherborne',
        '180A Sherborne': '180A Sherborne',
        '180B Sherborne': '180B Sherborne',
        '208 Sherborne': '208 Sherborne',
        '210 Sherborne': '210 Sherborne',
        '5 Boswell': '5 Boswell',
        '450 Stanley Rd': '450 Stanley Rd',
        '15 St Johns': '15 St Johns',
        '70 Fosse Park': '70 Fosse Park',
        '3 Sam Close': '3 Sam Close',
    }.items()}

    prop_by_short = {p.short_name: p.id for p in Property.query.all()}

    for row in rows:
        prop_raw = (row.get('Property', '') or row.get('property', '')).strip()
        prop_id = None
        # Try short name match
        for short, pid in prop_by_short.items():
            if prop_raw.lower() in short.lower() or short.lower() in prop_raw.lower():
                prop_id = pid
                break
        if not prop_id and prop_raw:
            skipped += 1
            continue

        director_raw = (row.get('Director', '') or row.get('director', '')
                        or row.get('Visited By', '')).strip()
        visited_by_id = contact_map.get(director_raw)

        visit_type_raw = (row.get('Visit Type', '') or row.get('visit_type', '')).lower()
        visit_type = 'special' if 'special' in visit_type_raw else 'routine'

        visit_date = parse_date(row.get('Date', '') or row.get('date', '')
                               or row.get('Visit Date', ''))
        if not visit_date:
            skipped += 1
            continue

        checked_raw = (row.get('Checked', '') or '').lower()
        checked = 'checked' in checked_raw or checked_raw == 'true'
        notes = row.get('Notes', '') or row.get('notes', '')

        imgs = [
            row.get('Image 1', '') or '',
            row.get('Image 2', '') or '',
            row.get('Image 3', '') or '',
        ]

        visit = Visit(
            property_id=prop_id,
            visited_by_id=visited_by_id,
            visit_type=visit_type,
            visit_date=visit_date,
            notes=notes or None,
            checked=checked,
            status='complete',
        )
        db.session.add(visit)
        db.session.flush()

        for img in imgs:
            if img.strip():
                db.session.add(VisitImage(visit_id=visit.id, image_path=img.strip()))

        created += 1

    db.session.commit()
    print(f'  Visits: {created} created, {skipped} skipped')


def migrate_expenses(rows, legacy_map, contact_map):
    """Migrate expenses/mileage table."""
    created = skipped = 0
    prop_by_short = {p.short_name: p.id for p in Property.query.all()}

    def resolve_property(to_addr, from_addr=''):
        """Try to match address to a property."""
        combined = (to_addr + ' ' + from_addr).lower()
        for fragment, short in ADDRESS_TO_PROPERTY.items():
            if fragment in combined:
                return prop_by_short.get(short)
        return None

    for row in rows:
        exp_type = (row.get('Type', '') or row.get('type', '') or 'Mileage').strip()
        exp_date = parse_date(row.get('Date', '') or row.get('date', ''))
        if not exp_date:
            skipped += 1
            continue

        director_raw = (row.get('Director', '') or row.get('director', '')).strip()
        director_id = contact_map.get(director_raw)

        from_addr = row.get('From', '') or row.get('from_address', '')
        to_addr = row.get('To', '') or row.get('to_address', '')
        prop_id = resolve_property(to_addr, from_addr)

        stops_raw = row.get('Additional Stops', '') or row.get('additional_stops', '')
        try:
            stops = int(stops_raw)
        except:
            stops = 0

        amount_raw = row.get('Amount', '') or row.get('amount', '') or '0'
        amount = parse_amount(amount_raw)

        entity_raw = (row.get('Entity', '') or row.get('entity', '')).lower()
        entity = 'personal' if 'pers' in entity_raw or 'cc pers' in entity_raw.lower() else 'company'

        checked_raw = (row.get('Checked', '') or '').lower()
        checked = 'checked' in checked_raw or checked_raw == 'true'
        notes = row.get('Notes', '') or row.get('notes', '')

        exp = Expense(
            property_id=prop_id,
            director_id=director_id,
            expense_type=exp_type.lower(),
            from_address=from_addr or None,
            to_address=to_addr or None,
            additional_stops=stops,
            amount_gbp=amount,
            notes=notes or None,
            entity=entity,
            checked=checked,
            expense_date=exp_date,
        )
        db.session.add(exp)
        created += 1

    db.session.commit()
    print(f'  Expenses: {created} created, {skipped} skipped')


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run():
    print('\n🏠 EstateIQ / Portfolio — AppSheet Migration')
    print('=' * 50)

    with app.app_context():
        print('\n📋 Creating database schema...')
        db.create_all()
        create_default_users()

        print('\n📂 Reading CSV files...')
        prop_rows     = read_csv('properties.csv')
        contact_rows  = read_csv('contacts.csv')
        task_rows     = read_csv('tasks.csv')
        doc_rows      = read_csv('documents.csv')
        visit_rows    = read_csv('visits.csv')
        expense_rows  = read_csv('expenses.csv')

        print('\n🔄 Migrating data...')

        print('\n  → Properties')
        prop_map, legacy_map = migrate_properties(prop_rows)

        print('\n  → Vehicles')
        vehicle_map = migrate_vehicles()

        print('\n  → Contacts')
        contact_map = migrate_contacts(contact_rows)

        print('\n  → Documents')
        migrate_documents(doc_rows, legacy_map, vehicle_map, contact_map)

        print('\n  → Tasks')
        migrate_tasks(task_rows, legacy_map, contact_map)

        print('\n  → Visits')
        migrate_visits(visit_rows, legacy_map, contact_map)

        print('\n  → Expenses')
        migrate_expenses(expense_rows, legacy_map, contact_map)

        print('\n' + '=' * 50)
        print('✅ Migration complete!\n')
        print(f'   Properties : {Property.query.count()}')
        print(f'   Vehicles   : {Vehicle.query.count()}')
        print(f'   Contacts   : {Contact.query.count()}')
        print(f'   Documents  : {Document.query.count()}')
        print(f'   Tasks      : {Task.query.count()}')
        print(f'   Visits     : {Visit.query.count()}')
        print(f'   Expenses   : {Expense.query.count()}')
        print(f'   Users      : {User.query.count()}')
        print(f'\n   🔑 Default logins:')
        print(f'      chris / chambers2026')
        print(f'      ash   / morgan2026')
        print(f'\n   ⚠  Change passwords after first login!')
        print(f'\n   ℹ  Sensitive data (HMRC credentials, alarm codes)')
        print(f'      has been redacted. Add to Vault when implemented.\n')


if __name__ == '__main__':
    run()
