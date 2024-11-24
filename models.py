from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin

db = SQLAlchemy()

class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # SD, SA, NS
    users = db.relationship('User', backref='team', lazy=True)

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_migrations = db.relationship('Migration', backref='creator', lazy=True, 
                                      foreign_keys='Migration.created_by')
    assigned_migrations = db.relationship('Migration', backref='assignee', lazy=True,
                                       foreign_keys='Migration.assigned_to')

class Migration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    customer_name = db.Column(db.String(100), nullable=False)
    customer_contact = db.Column(db.String(200))
    status = db.Column(db.String(50), nullable=False, default='waiting')  # waiting, acknowledged, in_progress, completed
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'))
    acknowledged_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    files = db.relationship('MigrationFile', backref='migration', lazy=True)

class MigrationFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    migration_id = db.Column(db.Integer, db.ForeignKey('migration.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    file_type = db.Column(db.String(50))  # result, attachment, etc.

class MigrationLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    migration_id = db.Column(db.Integer, db.ForeignKey('migration.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(100), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    details = db.Column(db.Text)

# Add notification model
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    message = db.Column(db.String(200))
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    migration_id = db.Column(db.Integer, db.ForeignKey('migration.id'))