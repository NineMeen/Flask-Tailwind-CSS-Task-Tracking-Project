from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_login import LoginManager, login_required, current_user, login_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from models import db, User, Team, Migration, MigrationFile, MigrationLog

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'  # Change this in production
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///migration_tracker.db'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def log_action(migration_id, user_id, action, details=None):
    log = MigrationLog(
        migration_id=migration_id,
        user_id=user_id,
        action=action,
        details=details
    )
    db.session.add(log)
    db.session.commit()

@app.route('/')
@login_required
def index():
    if current_user.team.name == 'SD':
        migrations = Migration.query.filter_by(created_by=current_user.id).all()
    elif current_user.team.name in ['SA', 'NS']:
        migrations = Migration.query.filter(
            (Migration.status != 'completed') & 
            ((Migration.assigned_to == current_user.id) | 
             (Migration.assigned_to == None))
        ).all()
    else:  # Admin
        migrations = Migration.query.all()
    
    return render_template('task/task.html', migrations=migrations ,User=User)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('index'))  # Create this route
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            next_page = request.args.get('next')
            if user.is_admin:
                return redirect(next_page if next_page else url_for('index'))  # Admin route
            return redirect(next_page if next_page else url_for('index'))  # Regular user route
        else:
            flash('Invalid username or password', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin_dashboard():
    return render_template('admin/index.html')

# @app.route('/migration/new', methods=['GET', 'POST'])
# @login_required
# def create_migration():
#     if current_user.team.name != 'SD' and not current_user.is_admin:
#         flash('Only SD team members can create migration requests.', 'error')
#         return redirect(url_for('index'))

#     if request.method == 'POST':
#         migration = Migration(
#             title=request.form['title'],
#             description=request.form['description'],
#             customer_name=request.form['customer_name'],
#             customer_contact=request.form['customer_contact'],
#             created_by=current_user.id,
#             status='waiting'
#         )
#         db.session.add(migration)
#         db.session.commit()

#         # Create unique folder for this migration
#         migration_folder = os.path.join(app.config['UPLOAD_FOLDER'], f'migration_{migration.id}')
#         os.makedirs(migration_folder, exist_ok=True)

#         # Handle file upload
#         if 'file' in request.files:
#             file = request.files['file']
#             if file:
#                 filename = secure_filename(file.filename)
#                 file_path = os.path.join(migration_folder, filename)
#                 file.save(file_path)
                
#                 migration_file = MigrationFile(
#                     migration_id=migration.id,
#                     filename=filename,
#                     file_path=file_path,
#                     file_type='attachment'
#                 )
#                 db.session.add(migration_file)
#                 db.session.commit()

#         log_action(migration.id, current_user.id, 'created')
#         flash('Migration request created successfully.', 'success')
#         return redirect(url_for('index'))

#     return render_template('migration/create.html')

@app.route('/migration/new', methods=['GET', 'POST'])
@login_required
def create_migration():
    if current_user.team.name != 'SD' and not current_user.is_admin:
        flash('Only SD team members can create migration requests.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        migration = Migration(
            title=request.form['title'],
            description=request.form['description'],
            customer_name=request.form['customer_name'],
            customer_contact=request.form['customer_contact'],
            created_by=current_user.id,
            status='waiting'
        )
        db.session.add(migration)
        db.session.commit()

        # Create unique folder for this migration
        migration_folder = os.path.join(app.config['UPLOAD_FOLDER'], f'migration_{migration.id}')
        os.makedirs(migration_folder, exist_ok=True)

        # Handle multiple file uploads
        files = request.files.getlist('files[]')
        for file in files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                file_path = os.path.join(migration_folder, filename)
                file.save(file_path)
                
                migration_file = MigrationFile(
                    migration_id=migration.id,
                    filename=filename,
                    file_path=file_path,
                    file_type='attachment'
                )
                db.session.add(migration_file)
        
        db.session.commit()
        log_action(migration.id, current_user.id, 'created')
        flash('Migration request created successfully.', 'success')
        return redirect(url_for('index'))

    return render_template('migration/create.html')

@app.route('/migration/<int:id>', methods=['GET'])
@login_required
def view_migration(id):
    migration = Migration.query.get_or_404(id)
    migration_files = MigrationFile.query.filter_by(migration_id=migration.id).all()
    return render_template('migration/view.html', 
                         migration=migration, 
                         migration_files=migration_files,
                         User=User)

@app.route('/migration/<int:id>/acknowledge', methods=['POST'])
@login_required
def acknowledge_migration(id):
    if current_user.team.name != 'SA':
        flash('Only SA team members can acknowledge migrations.', 'error')
        return redirect(url_for('index'))

    migration = Migration.query.get_or_404(id)
    migration.status = 'acknowledged'
    migration.acknowledged_at = datetime.utcnow()
    db.session.commit()

    log_action(migration.id, current_user.id, 'acknowledged')
    flash('Migration acknowledged successfully.', 'success')
    return redirect(url_for('index'))

@app.route('/migration/<int:id>/assign', methods=['POST'])
@login_required
def assign_migration(id):
    if current_user.team.name != 'SA':
        flash('Only SA team members can assign migrations.', 'error')
        return redirect(url_for('index'))

    migration = Migration.query.get_or_404(id)
    migration.assigned_to = current_user.id
    migration.status = 'in_progress'
    db.session.commit()

    log_action(migration.id, current_user.id, 'assigned', f'Assigned to {current_user.username}')
    flash('Migration assigned successfully.', 'success')
    return redirect(url_for('index'))

@app.route('/migration/<int:id>/update-status', methods=['POST'])
@login_required
def update_migration_status(id):
    if current_user.team.name != 'SA':
        flash('Only SA team members can update migration status.', 'error')
        return redirect(url_for('index'))

    migration = Migration.query.get_or_404(id)
    new_status = request.form.get('status')
    
    if new_status in ['completed', 'rollback', 'in_progress']:
        migration.status = new_status
        migration.completed_at = datetime.utcnow()
        
        # Handle result file upload
        if 'result_file' in request.files:
            file = request.files['result_file']
            if file and file.filename:
                filename = secure_filename(file.filename)
                migration_folder = os.path.join(app.config['UPLOAD_FOLDER'], f'migration_{migration.id}')
                file_path = os.path.join(migration_folder, filename)
                file.save(file_path)
                
                migration_file = MigrationFile(
                    migration_id=migration.id,
                    filename=filename,
                    file_path=file_path,
                    file_type='result'
                )
                db.session.add(migration_file)
        
        db.session.commit()
        log_action(migration.id, current_user.id, f'status_updated', f'Status changed to {new_status}')
        flash(f'Migration status updated to {new_status}', 'success')
    
    return redirect(url_for('view_migration', id=id))

@app.route('/file/<int:file_id>/view')
@login_required
def view_file(file_id):
    file = MigrationFile.query.get_or_404(file_id)
    return send_file(file.file_path, as_attachment=False)

@app.route('/file/<int:file_id>/download')
@login_required
def download_file(file_id):
    file = MigrationFile.query.get_or_404(file_id)
    return send_file(file.file_path, as_attachment=True, download_name=file.filename)

# Initialize the database
with app.app_context():
    db.create_all()
    
    # Create initial teams if they don't exist
    teams = ['SD', 'SA', 'NS']
    for team_name in teams:
        if not Team.query.filter_by(name=team_name).first():
            team = Team(name=team_name)
            db.session.add(team)
    
    # Create admin user if it doesn't exist
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            password=generate_password_hash('admin'),
            email='admin@example.com',
            team_id=1,
            is_admin=True
        )
        db.session.add(admin)
    
    db.session.commit()

@app.route('/admin/create-user', methods=['GET', 'POST'])
@login_required
def create_user():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        team_id = request.form['team_id']
        is_admin = 'is_admin' in request.form

        # Basic validation
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('create_user'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('create_user'))

        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'error')
            return redirect(url_for('create_user'))

        # Create new user
        new_user = User(
            username=username,
            email=email,
            password=generate_password_hash(password),
            team_id=team_id,
            is_admin=is_admin
        )
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('User created successfully', 'success')
            return redirect(url_for('create_user'))
        except Exception as e:
            db.session.rollback()
            flash('Error creating user', 'error')
            return redirect(url_for('create_user'))

    # GET request - display form
    teams = Team.query.all()
    return render_template('admin/create.html', teams=teams)

if __name__ == '__main__':
    app.run(debug=True)