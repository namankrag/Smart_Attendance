from src.database.config import supabase, db_retry
import bcrypt

def hash_pass(pwd):
    return bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()

def check_pass(pwd, hashed):
    return bcrypt.checkpw(pwd.encode(), hashed.encode())

@db_retry()
def check_teacher_exists(username):
    response = supabase.table("teachers").select("username").eq("username", username).execute()
    return len(response.data) > 0

@db_retry()
def create_teacher(username, password, name):
    data = {"username" : username, "password" : hash_pass(password), "name" : name}
    response = supabase.table("teachers").insert(data).execute()
    return response.data

@db_retry()
def teacher_login(username, password):
    response = supabase.table("teachers").select("*").eq("username", username).execute()
    if response.data:
        teacher = response.data[0]
        if check_pass(password, teacher['password']):
            return teacher
    return None

@db_retry()
def get_all_students():
    response = supabase.table('students').select("*").execute()
    return response.data

@db_retry()
def create_student(new_name, face_embedding = None, voice_embedding = None):
    data = {'name' : new_name, 'face_embedding' : face_embedding, 'voice_embedding' : voice_embedding}
    response = supabase.table('students').insert(data).execute()
    return response.data

@db_retry()
def create_subject(sub_code, name, sec, teach_id):
    data = {'subject_code' : sub_code, 'name' : name, 'section' : sec, 'teacher_id' : teach_id}
    response = supabase.table('subjects').insert(data).execute()
    return response.data

@db_retry()
def get_teacher_subjects(teach_id):
    response = supabase.table('subjects').select("*, subject_students(count), attendance_logs(timestamp)").eq("teacher_id", teach_id).execute()

    subjects = response.data

    for sub in subjects:
        sub['total_students'] = sub.get("subject_students", [{}])[0].get('count', 0) if sub.get('subject_students') else 0
        attend = sub.get('attendance_logs', [])
        unique_session = len(set(log['timestamp'] for log in attend))
        sub['total_classes'] = unique_session

        sub.pop('subject_students', None)
        sub.pop('attendance_logs', None)

    return subjects

@db_retry()
def enroll_student_to_subject(student_id, subject_id):
    data = {'student_id' : student_id, 'subject_id' : subject_id}
    response = supabase.table('subject_students').insert(data).execute()
    return response.data

@db_retry()
def unenroll_student_to_subject(student_id, subject_id):
    response = supabase.table('subject_students').delete().eq('student_id', student_id).eq('subject_id', subject_id).execute()
    return response.data

@db_retry()
def get_student_subjects(student_id):
    response = supabase.table('subject_students').select('*, subjects(*, attendance_logs(timestamp))').eq('student_id', student_id).execute()
    subjects = response.data

    for item in subjects:
        sub = item.get('subjects', {})
        if sub:
            attend = sub.get('attendance_logs', [])
            unique_session = len(set(log['timestamp'] for log in attend))
            sub['total_classes'] = unique_session
            sub.pop('attendance_logs', None)

    return subjects

@db_retry()
def get_student_attendance(student_id):
    response = supabase.table('attendance_logs').select('*, subjects(*)').eq('student_id', student_id).execute()
    return response.data

@db_retry()
def create_attendance(logs):
    response = supabase.table('attendance_logs').insert(logs).execute()
    return response.data

@db_retry()
def get_attendance_for_teacher(teacher_id):
    response = supabase.table('attendance_logs').select('*, subjects!inner(*)').eq('subjects.teacher_id', teacher_id).execute()
    return response.data

@db_retry()
def delete_subject(subject_id):
    """Cascade-delete a subject and all its related data:
       attendance_logs → subject_students → subjects
    """
    supabase.table('attendance_logs').delete().eq('subject_id', subject_id).execute()
    supabase.table('subject_students').delete().eq('subject_id', subject_id).execute()
    supabase.table('subjects').delete().eq('subject_id', subject_id).execute()
