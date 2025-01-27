from gevent import monkey
monkey.patch_all()

# Now import other modules
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import LoginManager, login_required, current_user, login_user, logout_user
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from datetime import datetime, timedelta
from models import db, User, Team, Migration, MigrationFile, MigrationLog, Notification
from ldap3 import Server, Connection, ALL, NTLM
from flask_migrate import Migrate
from sqlalchemy.pool import NullPool

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'  # Change this in production
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///migration_tracker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'poolclass': NullPool,  # Disable connection pooling
    'pool_pre_ping': True,  # Optional: Enable connection health checks
}
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Initialize extensions
# db.init_app(app)
# migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# LDAP Configuration
LDAP_SERVER = '10.10.11.45'
LDAP_PORT = 389
LDAP_BASE_DN = 'OU=WorkTracking,DC=test,DC=net,DC=th'

# Initialize SocketIO
socketio = SocketIO(app, async_mode='gevent')

@socketio.on('disconnect')
def handle_disconnect():
    db.session.remove()

def authenticate_ldap(username, password):
    try:
        server = Server(
            LDAP_SERVER,
            port=LDAP_PORT,
            use_ssl=False,
            get_info=ALL
        )
        
        user_dn = username
        conn = Connection(
            server,
            user=user_dn,
            password=password,
            authentication='SIMPLE'
        )
        
        if conn.bind():
            conn.search(
                LDAP_BASE_DN,
                f'(&(objectClass=person)(sAMAccountName={username}))',
                attributes=['displayName', 'mail', 'memberOf']
            )
            
            if len(conn.entries) > 0:
                user_data = conn.entries[0]
                # Extract group names from memberOf DNs
                groups = []
                if hasattr(user_data, 'memberOf'):
                    for group_dn in user_data.memberOf:
                        try:
                            cn_parts = [part for part in group_dn.split(',') if part.startswith('CN=')]
                            if cn_parts:
                                group_name = cn_parts[0].replace('CN=', '').strip()
                                if group_name == 'GWTK01':
                                    group_name = 'SA'
                                    groups.append(group_name)
                                elif group_name == 'GWTK02':
                                    group_name = 'SD'
                                    groups.append(group_name)
                                elif group_name == 'GWTK03':
                                    group_name = 'NS'
                                    groups.append(group_name)
                                elif group_name == 'GWTKADMIN':
                                    group_name = 'ADMIN'
                                    groups.append(group_name)
                        except Exception as e:
                            continue
                
                # Convert groups list to single string if only one group
                final_groups = groups[0] if len(groups) == 1 else groups
                
                return {
                    'status': 'success',
                    'message': 'Authentication successful',
                    'user': {
                        'displayName': user_data.displayName.value if hasattr(user_data, 'displayName') else None,
                        'email': user_data.mail.value if hasattr(user_data, 'mail') else None,
                        'memberOf': final_groups
                    }
                }
            return {
                'status': 'error',
                'message': 'Authentication successful but no user data found'
            }
        else:
            return {
                'status': 'error',
                'message': 'Invalid credentials'
            }
            
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e)
        }

@login_manager.user_loader
def load_user(user_id):
    if user_id is None:
        return None
    try:
        # Try to load user by numeric ID first
        return User.query.get(int(user_id))
    except ValueError:
        # If user_id is not numeric, try to find user by username
        return User.query.filter_by(username=user_id).first()

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
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Try LDAP authentication
        ldap_result = authenticate_ldap(username, password)
        
        if ldap_result['status'] == 'success':
            # Check if user exists in local database
            user = User.query.filter_by(username=username).first()
            
            if user is None:
                # Get team from LDAP memberOf attribute
                ldap_groups = ldap_result['user']['memberOf']
                
                # Handle if memberOf is a list, string, or None
                if isinstance(ldap_groups, list) and ldap_groups:  # Check if list is not empty
                    # If multiple groups, try to find the first valid team
                    team_name = None
                    for group in ldap_groups:
                        mapped_team = map_ldap_group_to_team(group)
                        if mapped_team:
                            team_name = mapped_team
                            break
                    if team_name is None:
                        team_name = 'NS'  # Default if no valid team found
                elif isinstance(ldap_groups, str) and ldap_groups:  # Check if string is not empty
                    # If single group
                    team_name = map_ldap_group_to_team(ldap_groups)
                else:
                    # If no groups, None, empty list, or empty string
                    team_name = 'NS'  # Default team
                
                # Create new user with team from LDAP
                user = User(
                    username=username,
                    email=ldap_result['user']['email'] if ldap_result['user'].get('email') else f"{username}@symphony.net.th",
                    password=generate_password_hash(password),
                    team_id=get_team_id(team_name),
                    is_admin=True if 'GWTKADMIN' in (ldap_groups if isinstance(ldap_groups, list) else [ldap_groups]) else False
                )
                try:
                    db.session.add(user)
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    flash('Error creating user account', 'error')
                    return redirect(url_for('login'))
            
            # Log the user in
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page if next_page else url_for('index'))
            
        flash('Invalid username or password', 'error')
            
    return render_template('login.html')

def map_ldap_group_to_team(ldap_group):
    """Helper function to map LDAP GWTK groups to team names"""
    if not ldap_group:
        return 'SA'  # Default team if no group
        
    group_mapping = {
        'GWTK01': 'SA',
        'GWTK02': 'SD',
        'GWTK03': 'NS',
        'GWTKADMIN': 'ADMIN'
    }
    return group_mapping.get(str(ldap_group), 'NS')  # Default to NS if unknown

def get_team_id(team_name):
    """Helper function to map team names to local team IDs"""
    team_mapping = {
        'SA': 1,
        'SD': 2,
        'NS': 3,
        'ADMIN': 1  # Assuming ADMIN users are part of SA team
    }
    return team_mapping.get(team_name, 3)  # Default to NS team if unknown

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin_dashboard():
    return render_template('admin/index.html')


@app.route('/migration/new', methods=['GET', 'POST'])
@login_required
def create_migration():
    if current_user.team.name != 'SD' and not current_user.is_admin:
        flash('Only SD team members can create migration requests.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        scheduled_date_str = request.form.get('scheduled_date')
        scheduled_time_str = request.form.get('scheduled_time')
        
        if scheduled_date_str and scheduled_time_str:
            try:
                scheduled_datetime = datetime.strptime(
                    f"{scheduled_date_str} {scheduled_time_str}",
                    "%Y-%m-%d %H:%M"
                )
            except ValueError:
                flash('Invalid date or time format', 'error')
                return redirect(url_for('create_migration'))
        else:
            scheduled_datetime = None

        migration = Migration(
            title=request.form['title'],
            description=request.form['description'],
            customer_name=request.form['customer_name'],
            customer_contact=request.form['customer_contact'],
            created_by=current_user.id,
            status='waiting',
            scheduled_date=scheduled_datetime
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

        # Send notification to all SA team members
        sa_team = Team.query.filter_by(name='SA').first()
        if sa_team:
            sa_users = User.query.filter_by(team_id=sa_team.id).all()
            for user in sa_users:
                notification = Notification(
                    user_id=user.id,
                    message=f'New migration request: {migration.title}',
                    migration_id=migration.id
                )
                db.session.add(notification)
            db.session.commit()
            
            # Emit socket event
            socketio.emit('new_notification', {
                'message': f'New migration request: {migration.title}',
                'migration_id': migration.id
            }, room='sa_team')

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

@app.route('/team')
@login_required
def team_page():
    if current_user.team.name == 'SA' or current_user.team.name == 'SD':
        team_members = User.query.filter_by(team_id=current_user.team_id).all()
        migrations = Migration.query.filter_by(status='in_progress').all()
        return render_template('task/team.html', team_members=team_members, migrations=migrations,User=User)
    else:
        flash('Access denied. Only SA team members can view this page.', 'error')
        return redirect(url_for('index'))

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

@app.route('/search')
@login_required
def search():
    # Get search parameters
    search_query = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    
    # Base query
    query = Migration.query

    # Apply status filter if specified
    if status_filter:
        query = query.filter(Migration.status == status_filter)
    else:
        # Show all tasks when searching, but only completed and rollback by default
        if search_query:
            query = query.filter(Migration.status.in_(['completed', 'rollback', 'in_progress', 'waiting']))
        else:
            query = query.filter(Migration.status.in_(['completed', 'rollback']))

    # Apply search if specified
    if search_query:
        search = f"%{search_query}%"
        query = query.filter(
            db.or_(
                Migration.title.ilike(search),
                Migration.customer_name.ilike(search)
            )
        )

    # Order by completion date
    migrations = query.order_by(Migration.completed_at.desc()).all()
    
    return render_template('search.html', migrations=migrations)

@app.route('/notifications')
@login_required
def get_notifications():
    notifications = Notification.query.filter_by(
        user_id=current_user.id,
        read=False
    ).order_by(Notification.created_at.desc()).all()
    
    return jsonify([{
        'id': n.id,
        'message': n.message,
        'migration_id': n.migration_id,
        'created_at': n.created_at.strftime('%Y-%m-%d %H:%M:%S')
    } for n in notifications])

@app.route('/notifications/mark-read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    if notification.user_id == current_user.id:
        notification.read = True
        db.session.commit()
    return jsonify({'success': True})

@app.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def mark_all_notifications_read():
    notifications = Notification.query.filter_by(
        user_id=current_user.id,
        read=False
    ).all()
    
    for notification in notifications:
        notification.read = True
    
    db.session.commit()
    return jsonify({'success': True})

# Socket.IO event handlers
@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated and current_user.team.name == 'SA':
        socketio.emit('join', {'room': 'sa_team'})


@app.route('/migration/<int:id>/edit-page')
@login_required
def edit_migration_page(id):
    if current_user.team.name != 'SD' and not current_user.is_admin:
        flash('Only SD team members can edit migrations.', 'error')
        return redirect(url_for('index'))
    
    migration = Migration.query.get_or_404(id)
    if migration.created_by != current_user.id and not current_user.is_admin:
        flash('You can only edit your own migrations.', 'error')
        return redirect(url_for('index'))
        
    return render_template('migration/edit.html', migration=migration)

@app.route('/migration/<int:id>/edit', methods=['POST'])
@login_required
def edit_migration(id):
    if current_user.team.name != 'SD' and not current_user.is_admin:
        flash('Only SD team members can edit migrations.', 'error')
        return redirect(url_for('index'))

    migration = Migration.query.get_or_404(id)
    
    # Check if the user is the creator or admin
    if migration.created_by != current_user.id and not current_user.is_admin:
        flash('You can only edit your own migrations.', 'error')
        return redirect(url_for('index'))
    
    # Update scheduled date if provided
    scheduled_date_str = request.form.get('scheduled_date')
    scheduled_time_str = request.form.get('scheduled_time')
    
    if scheduled_date_str and scheduled_time_str:
        try:
            scheduled_datetime = datetime.strptime(
                f"{scheduled_date_str} {scheduled_time_str}",
                "%Y-%m-%d %H:%M"
            )
            migration.scheduled_date = scheduled_datetime
        except ValueError:
            flash('Invalid date or time format', 'error')
            return redirect(url_for('edit_migration_page', id=id))
    else:
        migration.scheduled_date = None
    
    # Update other migration details
    migration.title = request.form['title']
    migration.description = request.form['description']
    migration.customer_name = request.form['customer_name']
    migration.customer_contact = request.form['customer_contact']
    
    # Handle file uploads
    files = request.files.getlist('files[]')
    if files:
        migration_folder = os.path.join(app.config['UPLOAD_FOLDER'], f'migration_{migration.id}')
        os.makedirs(migration_folder, exist_ok=True)
        
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

    try:
        db.session.commit()
        log_action(migration.id, current_user.id, 'edited', 'Migration details updated')
        flash('Migration updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error updating migration.', 'error')
    
    return redirect(url_for('view_migration', id=id))

@app.route('/migration/<int:id>/delete', methods=['POST'])
@login_required
def delete_migration(id):
    if current_user.team.name != 'SD' and not current_user.is_admin:
        flash('Only SD team members can delete migrations.', 'error')
        return redirect(url_for('index'))

    migration = Migration.query.get_or_404(id)
    
    # Check if user is the creator or admin
    if migration.created_by != current_user.id and not current_user.is_admin:
        flash('You can only delete your own migrations.', 'error')
        return redirect(url_for('index'))

    try:
        # Delete associated files from storage
        migration_files = MigrationFile.query.filter_by(migration_id=id).all()
        for file in migration_files:
            if os.path.exists(file.file_path):
                os.remove(file.file_path)
            db.session.delete(file)

        # Delete the migration folder if it exists
        migration_folder = os.path.join(app.config['UPLOAD_FOLDER'], f'migration_{migration.id}')
        if os.path.exists(migration_folder):
            os.rmdir(migration_folder)

        # Delete associated logs
        MigrationLog.query.filter_by(migration_id=id).delete()
        
        # Delete associated notifications
        Notification.query.filter_by(migration_id=id).delete()

        # Delete the migration
        db.session.delete(migration)
        db.session.commit()

        flash('Migration deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error deleting migration.', 'error')
        print(f"Error: {str(e)}")  # For debugging

    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Get date range from query parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Create base query
    base_query = Migration.query

    # Apply date filtering if dates are provided
    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)  # Include the end date
            base_query = base_query.filter(Migration.created_at.between(start, end))
        except ValueError:
            flash('Invalid date format', 'error')

    # Get migration statistics with date filter
    total_migrations = base_query.count()
    completed = base_query.filter_by(status='completed').count()
    in_progress = base_query.filter_by(status='in_progress').count()
    rollback = base_query.filter_by(status='rollback').count()
    waiting = base_query.filter_by(status='waiting').count()
    acknowledged = base_query.filter_by(status='acknowledged').count()

    stats = {
        'total': total_migrations,
        'completed': completed,
        'in_progress': in_progress,
        'rollback': rollback,
        'waiting': waiting,
        'acknowledged': acknowledged
    }

    return render_template('dashboard.html', 
                         stats=stats, 
                         start_date=start_date, 
                         end_date=end_date)
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
    #socketio.run(app, host='0.0.0.0', port=5000)