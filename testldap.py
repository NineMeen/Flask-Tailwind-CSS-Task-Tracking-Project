from ldap3 import Server, Connection, ALL, SUBTREE

LDAP_SERVER = "10.10.11.45"
# ใช้ username อย่างเดียว ไม่ต้องมี domain
BIND_DN = "ADMINWTK"  
BIND_PASS = "ADM1N@WTK"
USER_BASE = "OU=WorkTracking,DC=test,DC=net,DC=th"

try:
    server = Server(
        LDAP_SERVER,
        port=389,
        use_ssl=False,
        get_info=ALL
    )
    
    conn = Connection(
        server,
        user=BIND_DN,
        password=BIND_PASS,
        authentication='SIMPLE'
    )
    
    if not conn.bind():
        print('Error in bind:', conn.result)
    else:
        print('Successfully connected')
        
        # เพิ่ม memberOf ใน attributes
        conn.search(USER_BASE, 
                   '(&(objectclass=person))',
                   SUBTREE,
                   attributes=['cn', 'sn', 'memberOf', 'displayName'])
        
        # แสดงผลแบบอ่านง่าย
        if len(conn.entries) == 0:
            print("User not found")
        else:
            for entry in conn.entries:
                print("\nUser:", entry.cn)
                print(entry.sn)
                print("DisplayName:", entry.displayName)
                if hasattr(entry, 'memberOf'):
                    print("Groups:")
                    for group in entry.memberOf:
                        # แสดงเฉพาะชื่อกลุ่ม ไม่แสดง DN เต็ม
                        group_name = group.split(',')[0].split('=')[1]
                        print(f"- {group_name}")
                print("-" * 30)

except Exception as e:
    print(f"Connection error: {str(e)}")
finally:
    if 'conn' in locals():
        conn.unbind()