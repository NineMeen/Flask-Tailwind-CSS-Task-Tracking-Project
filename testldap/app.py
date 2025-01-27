from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session
from ldap3 import Server, Connection, ALL, NTLM

app = Flask(__name__)
app.secret_key = 'ldaptest1234'  # ควรเปลี่ยนเป็น secret key ที่ปลอดภัย

# LDAP Configuration
LDAP_SERVER = '10.10.11.45'
LDAP_PORT = 389
LDAP_BASE_DN = 'OU=WorkTracking,DC=test,DC=net,DC=th'

def authenticate_ldap(username, password):
    try:
        # สร้าง Server object
        server = Server(
            LDAP_SERVER,
            port=LDAP_PORT,
            use_ssl=False,
            get_info=ALL
        )
        
        # สร้าง Connection object
        user_dn = username
        conn = Connection(
            server,
            user=user_dn,
            password=password,
            authentication='SIMPLE'  # ใช้ NTLM authentication สำหรับ Windows LDAP
        )
        
        # ทำการ bind เพื่อตรวจสอบการ authenticate
        if conn.bind():
            # ค้นหาข้อมูล user
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
                        'memberOf': final_groups  # Will be string if single group, list if multiple groups
                    }
                }
            return {
                'status': 'success',
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

@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
        
    username = request.form.get('username')
    password = request.form.get('password')
    
    if not username or not password:
        flash('กรุณากรอก username และ password', 'error')
        return redirect(url_for('login'))
    
    result = authenticate_ldap(username, password)
    
    if result['status'] == 'success':
        session['username'] = username
        session['user_data'] = result.get('user', {})
        return redirect(url_for('dashboard'))
    else:
        flash('Login ไม่สำเร็จ: ' + result['message'], 'error')
        return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', user_data=session.get('user_data', {}))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
