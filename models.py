from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date

db = SQLAlchemy()

class Property(db.Model):
    __tablename__ = 'properties'
    id = db.Column(db.Integer, primary_key=True)
    short_name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(300), nullable=False)
    property_type = db.Column(db.String(30), default='rental')  # rental/personal/company
    ownership = db.Column(db.String(30), default='company')     # company/personal_chris/personal_ash/joint
    postcode = db.Column(db.String(20))
    region = db.Column(db.String(50))                           # yeovil/cardiff/liverpool/other
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    legacy_id = db.Column(db.String(50))                        # AppSheet hash
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    documents = db.relationship('Document', backref='property',
                                primaryjoin="and_(Document.entity_type=='property', foreign(Document.entity_id)==Property.id)",
                                foreign_keys='Document.entity_id', overlaps='vehicle,vehicle_docs')
    tasks = db.relationship('Task', backref='property', lazy='dynamic')
    visits = db.relationship('Visit', backref='property', lazy='dynamic')
    expenses = db.relationship('Expense', backref='property', lazy='dynamic')
    contacts = db.relationship('PropertyContact', backref='property', lazy='dynamic')

    @property
    def active_documents(self):
        return Document.query.filter_by(entity_type='property', entity_id=self.id, status='active').all()

    @property
    def expiring_soon(self):
        today = date.today()
        from datetime import timedelta
        in_90 = today + timedelta(days=90)
        return Document.query.filter(
            Document.entity_type == 'property',
            Document.entity_id == self.id,
            Document.status == 'active',
            Document.expiry_date != None,
            Document.expiry_date <= in_90
        ).order_by(Document.expiry_date).all()

    @property
    def open_tasks(self):
        return self.tasks.filter(Task.status != 'complete').order_by(Task.created_date.desc()).all()

    @property
    def overdue_documents(self):
        today = date.today()
        return Document.query.filter(
            Document.entity_type == 'property',
            Document.entity_id == self.id,
            Document.status == 'active',
            Document.expiry_date != None,
            Document.expiry_date < today
        ).all()

    def __repr__(self):
        return f'<Property {self.short_name}>'


class Vehicle(db.Model):
    __tablename__ = 'vehicles'
    id = db.Column(db.Integer, primary_key=True)
    registration = db.Column(db.String(20), nullable=False)
    make = db.Column(db.String(50))
    model = db.Column(db.String(50))
    year = db.Column(db.Integer)
    ownership = db.Column(db.String(30), default='personal_chris')  # personal_chris/personal_ash/company
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    legacy_id = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def active_documents(self):
        return Document.query.filter_by(entity_type='vehicle', entity_id=self.id, status='active').all()

    @property
    def expiring_soon(self):
        today = date.today()
        from datetime import timedelta
        in_90 = today + timedelta(days=90)
        return Document.query.filter(
            Document.entity_type == 'vehicle',
            Document.entity_id == self.id,
            Document.status == 'active',
            Document.expiry_date != None,
            Document.expiry_date <= in_90
        ).order_by(Document.expiry_date).all()

    def __repr__(self):
        return f'<Vehicle {self.registration}>'


class Contact(db.Model):
    __tablename__ = 'contacts'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(10))
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    company_name = db.Column(db.String(200))
    role = db.Column(db.String(30))         # director/tenant/tradesperson/other
    mobile = db.Column(db.String(30))
    landline = db.Column(db.String(30))
    email = db.Column(db.String(200))
    speciality = db.Column(db.String(100))
    region = db.Column(db.String(100))
    rating = db.Column(db.String(20), default='unrated')  # gold/neutral/black/unrated
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    legacy_id = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    property_links = db.relationship('PropertyContact', backref='contact', lazy='dynamic')

    @property
    def display_name(self):
        if self.first_name and self.last_name:
            return f'{self.first_name} {self.last_name}'
        if self.company_name:
            return self.company_name
        return self.first_name or self.last_name or 'Unknown'

    @property
    def rating_class(self):
        return {'gold': 'rating-gold', 'black': 'rating-black',
                'neutral': 'rating-neutral'}.get(self.rating, 'rating-unrated')

    def __repr__(self):
        return f'<Contact {self.display_name}>'


class PropertyContact(db.Model):
    __tablename__ = 'property_contacts'
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'), nullable=False)
    role = db.Column(db.String(30))  # tenant/tradesperson/owner/manager
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Document(db.Model):
    __tablename__ = 'documents'
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(20), nullable=False)   # property/vehicle/company
    entity_id = db.Column(db.Integer, nullable=False)
    doc_type = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50))
    issued_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    reminder_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='active')      # active/archive
    drive_url = db.Column(db.String(500))
    verified = db.Column(db.Boolean, default=False)
    legacy_id = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def days_until_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - date.today()).days

    @property
    def traffic_light(self):
        d = self.days_until_expiry
        if d is None:
            return 'grey'
        if d < 0:
            return 'red'
        if d <= 30:
            return 'red'
        if d <= 90:
            return 'amber'
        return 'green'

    @property
    def traffic_class(self):
        return {'red': 'doc-red', 'amber': 'doc-amber',
                'green': 'doc-green', 'grey': 'doc-grey'}[self.traffic_light]

    def __repr__(self):
        return f'<Document {self.doc_type} exp:{self.expiry_date}>'


class Task(db.Model):
    __tablename__ = 'tasks'
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('contacts.id'))
    title = db.Column(db.String(200), nullable=False)
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='not_started')  # not_started/in_progress/complete
    priority = db.Column(db.Integer, default=0)
    created_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    estimated_days = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assigned_to = db.relationship('Contact', foreign_keys=[assigned_to_id])
    images = db.relationship('TaskImage', backref='task', lazy='dynamic')

    @property
    def status_class(self):
        return {'not_started': 'status-todo', 'in_progress': 'status-progress',
                'complete': 'status-complete'}[self.status]

    @property
    def is_overdue(self):
        return self.due_date and self.due_date < date.today() and self.status != 'complete'

    def __repr__(self):
        return f'<Task {self.title[:40]}>'


class TaskImage(db.Model):
    __tablename__ = 'task_images'
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    image_path = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Visit(db.Model):
    __tablename__ = 'visits'
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'))
    visited_by_id = db.Column(db.Integer, db.ForeignKey('contacts.id'))
    visit_type = db.Column(db.String(50))   # routine/special/emergency
    visit_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    checked = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='complete')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    visited_by = db.relationship('Contact', foreign_keys=[visited_by_id])
    images = db.relationship('VisitImage', backref='visit', lazy='dynamic')

    def __repr__(self):
        return f'<Visit {self.property_id} {self.visit_date}>'


class VisitImage(db.Model):
    __tablename__ = 'visit_images'
    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey('visits.id'), nullable=False)
    image_path = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Expense(db.Model):
    __tablename__ = 'expenses'
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'))
    director_id = db.Column(db.Integer, db.ForeignKey('contacts.id'))
    expense_type = db.Column(db.String(50))   # mileage/food/maintenance/other
    from_address = db.Column(db.String(300))
    to_address = db.Column(db.String(300))
    additional_stops = db.Column(db.Integer, default=0)
    amount_gbp = db.Column(db.Float, default=0.0)
    notes = db.Column(db.Text)
    entity = db.Column(db.String(30))          # company/personal
    checked = db.Column(db.Boolean, default=False)
    expense_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    director = db.relationship('Contact', foreign_keys=[director_id])

    def __repr__(self):
        return f'<Expense {self.expense_type} {self.expense_date}>'


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'))
    username = db.Column(db.String(50), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), default='partner')   # admin/partner/viewer/tenant
    avatar_initials = db.Column(db.String(3))
    avatar_colour = db.Column(db.String(20), default='#2a4a7f')
    active = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    contact = db.relationship('Contact', foreign_keys=[contact_id])

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'
