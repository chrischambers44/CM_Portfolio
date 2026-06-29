from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, date, timedelta
from models import db, Property, Vehicle, Contact, PropertyContact, Document, Task, TaskImage, Visit, VisitImage, Expense, User
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chambers-morgan-portfolio-2026')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///portfolio.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = ''

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ─── CONTEXT PROCESSORS ───────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    today = date.today()
    in_30 = today + timedelta(days=30)
    in_90 = today + timedelta(days=90)
    red_count = Document.query.filter(
        Document.status == 'active',
        Document.expiry_date != None,
        Document.expiry_date < in_30
    ).count()
    return dict(today=today, red_count=red_count)


# ─── AUTH ──────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    users = User.query.filter_by(active=True).all()
    selected_user = None
    error = None
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        password = request.form.get('password')
        user = User.query.get(user_id)
        if user and user.check_password(password):
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=True)
            return redirect(url_for('dashboard'))
        else:
            error = 'Incorrect password'
            selected_user = user
    return render_template('login.html', users=users, selected_user=selected_user, error=error)

@app.route('/login/select/<int:user_id>')
def login_select(user_id):
    user = User.query.get_or_404(user_id)
    users = User.query.filter_by(active=True).all()
    return render_template('login.html', users=users, selected_user=user, error=None)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ─── DASHBOARD ────────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    in_30  = today + timedelta(days=30)
    in_90  = today + timedelta(days=90)

    # Compliance alerts
    overdue = Document.query.filter(
        Document.status == 'active',
        Document.expiry_date != None,
        Document.expiry_date < today
    ).order_by(Document.expiry_date).all()

    due_30 = Document.query.filter(
        Document.status == 'active',
        Document.expiry_date != None,
        Document.expiry_date >= today,
        Document.expiry_date <= in_30
    ).order_by(Document.expiry_date).all()

    due_90 = Document.query.filter(
        Document.status == 'active',
        Document.expiry_date != None,
        Document.expiry_date > in_30,
        Document.expiry_date <= in_90
    ).order_by(Document.expiry_date).all()

    # Open tasks
    open_tasks = Task.query.filter(
        Task.status != 'complete'
    ).order_by(Task.due_date.nullslast(), Task.created_date.desc()).limit(10).all()

    # Recent visits
    recent_visits = Visit.query.order_by(Visit.visit_date.desc()).limit(8).all()

    # Properties summary
    rental_props = Property.query.filter_by(property_type='rental', active=True).all()

    # Stats
    stats = {
        'total_properties': Property.query.filter_by(property_type='rental', active=True).count(),
        'open_tasks': Task.query.filter(Task.status != 'complete').count(),
        'overdue_docs': len(overdue),
        'contacts': Contact.query.filter_by(active=True).count(),
    }

    return render_template('dashboard.html',
        overdue=overdue, due_30=due_30, due_90=due_90,
        open_tasks=open_tasks, recent_visits=recent_visits,
        rental_props=rental_props, stats=stats)


# ─── PROPERTIES ───────────────────────────────────────────────────────────────

@app.route('/properties')
@login_required
def properties():
    ptype = request.args.get('type', 'all')
    ownership = request.args.get('ownership', 'all')
    q = Property.query.filter_by(active=True)
    if ptype != 'all':
        q = q.filter_by(property_type=ptype)
    if ownership != 'all':
        q = q.filter_by(ownership=ownership)
    props = q.order_by(Property.short_name).all()
    return render_template('properties.html', props=props, ptype=ptype, ownership=ownership)

@app.route('/properties/<int:prop_id>')
@login_required
def property_detail(prop_id):
    prop = Property.query.get_or_404(prop_id)
    today = date.today()
    in_90 = today + timedelta(days=90)

    active_docs = Document.query.filter_by(
        entity_type='property', entity_id=prop_id, status='active'
    ).order_by(Document.expiry_date.nullslast()).all()

    archive_docs = Document.query.filter_by(
        entity_type='property', entity_id=prop_id, status='archive'
    ).order_by(Document.expiry_date.desc()).limit(20).all()

    open_tasks = Task.query.filter_by(property_id=prop_id).filter(
        Task.status != 'complete'
    ).order_by(Task.due_date.nullslast(), Task.created_date.desc()).all()

    recent_tasks = Task.query.filter_by(
        property_id=prop_id, status='complete'
    ).order_by(Task.updated_at.desc()).limit(10).all()

    visits = Visit.query.filter_by(property_id=prop_id).order_by(
        Visit.visit_date.desc()
    ).limit(20).all()

    linked_contacts = db.session.query(Contact, PropertyContact).join(
        PropertyContact, Contact.id == PropertyContact.contact_id
    ).filter(PropertyContact.property_id == prop_id).all()

    expenses = Expense.query.filter_by(property_id=prop_id).order_by(
        Expense.expense_date.desc()
    ).limit(20).all()

    return render_template('property_detail.html',
        prop=prop, active_docs=active_docs, archive_docs=archive_docs,
        open_tasks=open_tasks, recent_tasks=recent_tasks,
        visits=visits, linked_contacts=linked_contacts, expenses=expenses)


# ─── COMPLIANCE ───────────────────────────────────────────────────────────────

@app.route('/compliance')
@login_required
def compliance():
    today = date.today()
    in_30 = today + timedelta(days=30)
    in_90 = today + timedelta(days=90)
    doc_type = request.args.get('type', 'all')
    entity_type = request.args.get('entity', 'all')

    q = Document.query.filter_by(status='active')
    if doc_type != 'all':
        q = q.filter_by(doc_type=doc_type)
    if entity_type != 'all':
        q = q.filter_by(entity_type=entity_type)
    docs = q.order_by(Document.expiry_date.nullslast()).all()

    # Enrich with entity names
    enriched = []
    for doc in docs:
        name = '—'
        if doc.entity_type == 'property':
            p = Property.query.get(doc.entity_id)
            name = p.short_name if p else '?'
        elif doc.entity_type == 'vehicle':
            v = Vehicle.query.get(doc.entity_id)
            name = f'{v.make} {v.registration}' if v else '?'
        elif doc.entity_type == 'company':
            name = 'C & M Ltd'
        enriched.append((doc, name))

    doc_types = db.session.query(Document.doc_type).distinct().order_by(Document.doc_type).all()
    doc_types = [d[0] for d in doc_types]

    return render_template('compliance.html',
        docs=enriched, doc_types=doc_types,
        selected_type=doc_type, selected_entity=entity_type,
        today=today, in_30=in_30, in_90=in_90)


# ─── TASKS ────────────────────────────────────────────────────────────────────

@app.route('/tasks')
@login_required
def tasks():
    status = request.args.get('status', 'open')
    prop_id = request.args.get('property', 'all')
    assigned = request.args.get('assigned', 'all')

    q = Task.query
    if status == 'open':
        q = q.filter(Task.status != 'complete')
    elif status != 'all':
        q = q.filter_by(status=status)
    if prop_id != 'all':
        q = q.filter_by(property_id=int(prop_id))
    if assigned != 'all':
        q = q.filter_by(assigned_to_id=int(assigned))

    tasks = q.order_by(Task.status, Task.due_date.nullslast(), Task.created_date.desc()).all()
    props = Property.query.filter_by(active=True).order_by(Property.short_name).all()
    directors = Contact.query.filter_by(role='director', active=True).all()

    return render_template('tasks.html', tasks=tasks, props=props,
        directors=directors, status=status, prop_id=prop_id, assigned=assigned)

@app.route('/tasks/<int:task_id>')
@login_required
def task_detail(task_id):
    task = Task.query.get_or_404(task_id)
    return render_template('task_detail.html', task=task)

@app.route('/tasks/new', methods=['GET', 'POST'])
@login_required
def task_new():
    if request.method == 'POST':
        task = Task(
            property_id=request.form.get('property_id') or None,
            assigned_to_id=request.form.get('assigned_to_id') or None,
            title=request.form.get('title'),
            notes=request.form.get('notes'),
            status=request.form.get('status', 'not_started'),
            priority=int(request.form.get('priority', 0)),
            created_date=date.today(),
            due_date=_parse_date(request.form.get('due_date')),
        )
        db.session.add(task)
        db.session.commit()
        flash('Task created', 'success')
        return redirect(url_for('task_detail', task_id=task.id))
    props = Property.query.filter_by(active=True).order_by(Property.short_name).all()
    directors = Contact.query.filter_by(role='director', active=True).all()
    return render_template('task_form.html', task=None, props=props, directors=directors)

@app.route('/tasks/<int:task_id>/edit', methods=['GET', 'POST'])
@login_required
def task_edit(task_id):
    task = Task.query.get_or_404(task_id)
    if request.method == 'POST':
        task.property_id = request.form.get('property_id') or None
        task.assigned_to_id = request.form.get('assigned_to_id') or None
        task.title = request.form.get('title')
        task.notes = request.form.get('notes')
        task.status = request.form.get('status', task.status)
        task.priority = int(request.form.get('priority', 0))
        task.due_date = _parse_date(request.form.get('due_date'))
        task.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Task updated', 'success')
        return redirect(url_for('task_detail', task_id=task.id))
    props = Property.query.filter_by(active=True).order_by(Property.short_name).all()
    directors = Contact.query.filter_by(role='director', active=True).all()
    return render_template('task_form.html', task=task, props=props, directors=directors)

@app.route('/tasks/<int:task_id>/status', methods=['POST'])
@login_required
def task_status(task_id):
    task = Task.query.get_or_404(task_id)
    new_status = request.form.get('status')
    if new_status in ('not_started', 'in_progress', 'complete'):
        task.status = new_status
        task.updated_at = datetime.utcnow()
        db.session.commit()
    return redirect(request.referrer or url_for('tasks'))


# ─── VISITS ───────────────────────────────────────────────────────────────────

@app.route('/visits')
@login_required
def visits():
    prop_id = request.args.get('property', 'all')
    q = Visit.query
    if prop_id != 'all':
        q = q.filter_by(property_id=int(prop_id))
    visits = q.order_by(Visit.visit_date.desc()).limit(100).all()
    props = Property.query.filter_by(active=True).order_by(Property.short_name).all()
    return render_template('visits.html', visits=visits, props=props, prop_id=prop_id)

@app.route('/visits/new', methods=['GET', 'POST'])
@login_required
def visit_new():
    if request.method == 'POST':
        visit = Visit(
            property_id=request.form.get('property_id') or None,
            visited_by_id=request.form.get('visited_by_id') or None,
            visit_type=request.form.get('visit_type', 'routine'),
            visit_date=_parse_date(request.form.get('visit_date')) or date.today(),
            notes=request.form.get('notes'),
            checked=request.form.get('checked') == 'on',
            status='complete',
        )
        db.session.add(visit)
        db.session.commit()
        flash('Visit recorded', 'success')
        return redirect(url_for('visits'))
    props = Property.query.filter_by(active=True).order_by(Property.short_name).all()
    directors = Contact.query.filter_by(role='director', active=True).all()
    return render_template('visit_form.html', visit=None, props=props, directors=directors)


# ─── EXPENSES ─────────────────────────────────────────────────────────────────

@app.route('/expenses')
@login_required
def expenses():
    prop_id = request.args.get('property', 'all')
    director = request.args.get('director', 'all')
    entity = request.args.get('entity', 'all')
    q = Expense.query
    if prop_id != 'all':
        q = q.filter_by(property_id=int(prop_id))
    if director != 'all':
        q = q.filter_by(director_id=int(director))
    if entity != 'all':
        q = q.filter_by(entity=entity)
    exps = q.order_by(Expense.expense_date.desc()).all()
    props = Property.query.filter_by(active=True).order_by(Property.short_name).all()
    directors = Contact.query.filter_by(role='director', active=True).all()
    total = sum(e.amount_gbp or 0 for e in exps)
    return render_template('expenses.html', expenses=exps, props=props,
        directors=directors, total=total, prop_id=prop_id,
        director=director, entity=entity)

@app.route('/expenses/new', methods=['GET', 'POST'])
@login_required
def expense_new():
    if request.method == 'POST':
        amount_raw = request.form.get('amount_gbp', '0').replace('£', '').replace(',', '').strip()
        exp = Expense(
            property_id=request.form.get('property_id') or None,
            director_id=request.form.get('director_id') or None,
            expense_type=request.form.get('expense_type', 'mileage'),
            from_address=request.form.get('from_address'),
            to_address=request.form.get('to_address'),
            additional_stops=int(request.form.get('additional_stops', 0) or 0),
            amount_gbp=float(amount_raw) if amount_raw else 0.0,
            notes=request.form.get('notes'),
            entity=request.form.get('entity', 'company'),
            checked=request.form.get('checked') == 'on',
            expense_date=_parse_date(request.form.get('expense_date')) or date.today(),
        )
        db.session.add(exp)
        db.session.commit()
        flash('Expense recorded', 'success')
        return redirect(url_for('expenses'))
    props = Property.query.filter_by(active=True).order_by(Property.short_name).all()
    directors = Contact.query.filter_by(role='director', active=True).all()
    return render_template('expense_form.html', expense=None, props=props, directors=directors)


# ─── CONTACTS ─────────────────────────────────────────────────────────────────

@app.route('/contacts')
@login_required
def contacts():
    role = request.args.get('role', 'all')
    q = Contact.query.filter_by(active=True)
    if role != 'all':
        q = q.filter_by(role=role)
    contacts = q.order_by(Contact.last_name, Contact.first_name, Contact.company_name).all()
    return render_template('contacts.html', contacts=contacts, role=role)

@app.route('/contacts/<int:contact_id>')
@login_required
def contact_detail(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    linked = db.session.query(Property, PropertyContact).join(
        PropertyContact, Property.id == PropertyContact.property_id
    ).filter(PropertyContact.contact_id == contact_id).all()
    tasks = Task.query.filter_by(assigned_to_id=contact_id).order_by(Task.created_date.desc()).limit(20).all()
    visits = Visit.query.filter_by(visited_by_id=contact_id).order_by(Visit.visit_date.desc()).limit(20).all()
    expenses = Expense.query.filter_by(director_id=contact_id).order_by(Expense.expense_date.desc()).limit(20).all()
    return render_template('contact_detail.html', contact=contact,
        linked=linked, tasks=tasks, visits=visits, expenses=expenses)


# ─── VEHICLES ─────────────────────────────────────────────────────────────────

@app.route('/properties/<int:prop_id>/edit', methods=['GET', 'POST'])
@login_required
def property_edit(prop_id):
    prop = Property.query.get_or_404(prop_id)
    if request.method == 'POST':
        prop.short_name = request.form.get('short_name', prop.short_name)
        prop.address = request.form.get('address', prop.address)
        prop.property_type = request.form.get('property_type', prop.property_type)
        prop.ownership = request.form.get('ownership', prop.ownership)
        prop.postcode = request.form.get('postcode', prop.postcode)
        prop.region = request.form.get('region', prop.region)
        prop.notes = request.form.get('notes', prop.notes)
        db.session.commit()
        flash('Property updated', 'success')
        return redirect(url_for('property_detail', prop_id=prop_id))
    return render_template('property_form.html', prop=prop)

@app.route('/contacts/new', methods=['GET', 'POST'])
@login_required
def contact_new():
    if request.method == 'POST':
        c = Contact(
            first_name=request.form.get('first_name') or None,
            last_name=request.form.get('last_name') or None,
            company_name=request.form.get('company_name') or None,
            role=request.form.get('role', 'other'),
            mobile=request.form.get('mobile') or None,
            landline=request.form.get('landline') or None,
            email=request.form.get('email') or None,
            speciality=request.form.get('speciality') or None,
            region=request.form.get('region') or None,
            rating=request.form.get('rating', 'unrated'),
            notes=request.form.get('notes') or None,
        )
        db.session.add(c)
        db.session.commit()
        flash('Contact added', 'success')
        return redirect(url_for('contact_detail', contact_id=c.id))
    return render_template('contact_form.html', contact=None)

@app.route('/contacts/<int:contact_id>/edit', methods=['GET', 'POST'])
@login_required
def contact_edit(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    if request.method == 'POST':
        contact.first_name = request.form.get('first_name') or None
        contact.last_name = request.form.get('last_name') or None
        contact.company_name = request.form.get('company_name') or None
        contact.role = request.form.get('role', contact.role)
        contact.mobile = request.form.get('mobile') or None
        contact.landline = request.form.get('landline') or None
        contact.email = request.form.get('email') or None
        contact.speciality = request.form.get('speciality') or None
        contact.region = request.form.get('region') or None
        contact.rating = request.form.get('rating', contact.rating)
        contact.notes = request.form.get('notes') or None
        db.session.commit()
        flash('Contact updated', 'success')
        return redirect(url_for('contact_detail', contact_id=contact_id))
    return render_template('contact_form.html', contact=contact)

@app.route('/documents/new', methods=['GET', 'POST'])
@login_required
def document_new():
    if request.method == 'POST':
        doc = Document(
            entity_type=request.form.get('entity_type', 'property'),
            entity_id=int(request.form.get('entity_id', 0)),
            doc_type=request.form.get('doc_type'),
            category=request.form.get('category') or None,
            issued_date=_parse_date(request.form.get('issued_date')),
            expiry_date=_parse_date(request.form.get('expiry_date')),
            reminder_date=_parse_date(request.form.get('reminder_date')),
            notes=request.form.get('notes') or None,
            status=request.form.get('status', 'active'),
            drive_url=request.form.get('drive_url') or None,
            verified=request.form.get('verified') == 'on',
        )
        db.session.add(doc)
        db.session.commit()
        flash('Document added', 'success')
        if doc.entity_type == 'property':
            return redirect(url_for('property_detail', prop_id=doc.entity_id))
        return redirect(url_for('compliance'))
    props = Property.query.filter_by(active=True).order_by(Property.short_name).all()
    vehicles = Vehicle.query.filter_by(active=True).all()
    return render_template('document_form.html', doc=None, props=props, vehicles=vehicles)

@app.route('/documents/<int:doc_id>/edit', methods=['GET', 'POST'])
@login_required
def document_edit(doc_id):
    doc = Document.query.get_or_404(doc_id)
    if request.method == 'POST':
        doc.doc_type = request.form.get('doc_type', doc.doc_type)
        doc.category = request.form.get('category') or None
        doc.issued_date = _parse_date(request.form.get('issued_date'))
        doc.expiry_date = _parse_date(request.form.get('expiry_date'))
        doc.reminder_date = _parse_date(request.form.get('reminder_date'))
        doc.notes = request.form.get('notes') or None
        doc.status = request.form.get('status', doc.status)
        doc.drive_url = request.form.get('drive_url') or None
        doc.verified = request.form.get('verified') == 'on'
        db.session.commit()
        flash('Document updated', 'success')
        if doc.entity_type == 'property':
            return redirect(url_for('property_detail', prop_id=doc.entity_id))
        return redirect(url_for('compliance'))
    props = Property.query.filter_by(active=True).order_by(Property.short_name).all()
    vehicles = Vehicle.query.filter_by(active=True).all()
    return render_template('document_form.html', doc=doc, props=props, vehicles=vehicles)

@app.route('/visits/<int:visit_id>/edit', methods=['GET', 'POST'])
@login_required
def visit_edit(visit_id):
    visit = Visit.query.get_or_404(visit_id)
    if request.method == 'POST':
        visit.property_id = request.form.get('property_id') or None
        visit.visited_by_id = request.form.get('visited_by_id') or None
        visit.visit_type = request.form.get('visit_type', visit.visit_type)
        visit.visit_date = _parse_date(request.form.get('visit_date')) or visit.visit_date
        visit.notes = request.form.get('notes') or None
        visit.checked = request.form.get('checked') == 'on'
        db.session.commit()
        flash('Visit updated', 'success')
        return redirect(url_for('visits'))
    props = Property.query.filter_by(active=True).order_by(Property.short_name).all()
    directors = Contact.query.filter_by(role='director', active=True).all()
    return render_template('visit_form.html', visit=visit, props=props, directors=directors)

@app.route('/expenses/<int:exp_id>/edit', methods=['GET', 'POST'])
@login_required
def expense_edit(exp_id):
    exp = Expense.query.get_or_404(exp_id)
    if request.method == 'POST':
        amount_raw = request.form.get('amount_gbp', '0').replace('£', '').replace(',', '').strip()
        exp.property_id = request.form.get('property_id') or None
        exp.director_id = request.form.get('director_id') or None
        exp.expense_type = request.form.get('expense_type', exp.expense_type)
        exp.from_address = request.form.get('from_address') or None
        exp.to_address = request.form.get('to_address') or None
        exp.additional_stops = int(request.form.get('additional_stops', 0) or 0)
        exp.amount_gbp = float(amount_raw) if amount_raw else 0.0
        exp.notes = request.form.get('notes') or None
        exp.entity = request.form.get('entity', exp.entity)
        exp.checked = request.form.get('checked') == 'on'
        exp.expense_date = _parse_date(request.form.get('expense_date')) or exp.expense_date
        db.session.commit()
        flash('Expense updated', 'success')
        return redirect(url_for('expenses'))
    props = Property.query.filter_by(active=True).order_by(Property.short_name).all()
    directors = Contact.query.filter_by(role='director', active=True).all()
    return render_template('expense_form.html', expense=exp, props=props, directors=directors)
    vehs = Vehicle.query.filter_by(active=True).order_by(Vehicle.registration).all()
    return render_template('vehicles.html', vehicles=vehs)


# ─── INTELLIGENCE (EstateIQ) ──────────────────────────────────────────────────

@app.route('/intelligence')
@login_required
def intelligence():
    props = Property.query.filter_by(property_type='rental', active=True).all()
    return render_template('intelligence.html', props=props)


# ─── VAULT (placeholder) ──────────────────────────────────────────────────────

@app.route('/vault')
@login_required
def vault():
    return render_template('vault.html')


# ─── API ENDPOINTS (for EstateIQ JS) ─────────────────────────────────────────

@app.route('/api/properties')
@login_required
def api_properties():
    props = Property.query.filter_by(property_type='rental', active=True).all()
    return jsonify([{
        'id': p.id, 'name': p.short_name, 'address': p.address,
        'ownership': p.ownership, 'notes': p.notes,
    } for p in props])


# ─── UTILITIES ────────────────────────────────────────────────────────────────

def _parse_date(s):
    if not s:
        return None
    from dateutil import parser as dp
    try:
        return dp.parse(str(s), dayfirst=True).date()
    except:
        return None


@app.template_filter('fmt_date')
def fmt_date(d):
    if not d:
        return '—'
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime('%-d %b %Y')

@app.template_filter('days_label')
def days_label(d):
    if not d:
        return ''
    today = date.today()
    if isinstance(d, datetime):
        d = d.date()
    delta = (d - today).days
    if delta < 0:
        return f'Overdue {abs(delta)}d'
    if delta == 0:
        return 'Today'
    if delta <= 30:
        return f'{delta}d'
    if delta <= 90:
        return f'{delta//7}w'
    return f'{delta//30}mo'


# ─── INIT ─────────────────────────────────────────────────────────────────────

def create_default_users():
    if User.query.count() == 0:
        chris = User(
            username='chris',
            display_name='Chris',
            role='admin',
            avatar_initials='CC',
            avatar_colour='#2a4a7f',
            active=True
        )
        chris.set_password('chambers2026')

        ash = User(
            username='ash',
            display_name='Ash',
            role='admin',
            avatar_initials='AM',
            avatar_colour='#4a6741',
            active=True
        )
        ash.set_password('morgan2026')

        db.session.add_all([chris, ash])
        db.session.commit()
        print('Default users created: chris / ash')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_default_users()
    app.run(host='0.0.0.0', port=5200, debug=False)
