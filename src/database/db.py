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
    """Enroll a student and mark every already-held session as absent.

    A class session is represented by one shared timestamp across its attendance
    rows. Backfilling a false row makes historic teacher percentages include the
    newly enrolled student immediately, while preserving the original session.
    """
    prior_sessions = (
        supabase.table('attendance_logs')
        .select('timestamp')
        .eq('subject_id', subject_id)
        .execute()
    )
    timestamps = sorted({row.get('timestamp') for row in prior_sessions.data if row.get('timestamp')})

    data = {'student_id': student_id, 'subject_id': subject_id}
    response = supabase.table('subject_students').insert(data).execute()

    if timestamps:
        historic_absences = [
            {
                'student_id': student_id,
                'subject_id': subject_id,
                'timestamp': timestamp,
                'is_present': False,
            }
            for timestamp in timestamps
        ]
        supabase.table('attendance_logs').insert(historic_absences).execute()
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
            session_timestamps = sorted({log['timestamp'] for log in attend if log.get('timestamp')})
            unique_session = len(session_timestamps)
            sub['total_classes'] = unique_session
            # Kept for the student UI so legacy enrollments can still show
            # historic sessions as absent even before their rows were backfilled.
            sub['session_timestamps'] = session_timestamps
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
    """Return teacher records after repairing any legacy enrollment gaps.

    Older enrollments may predate the attendance backfill added to
    ``enroll_student_to_subject``. Before calculating a teacher's records, add
    an absent row for every active enrolled student missing from a held session.
    This keeps each session's total aligned with current enrollment.
    """
    response = supabase.table('attendance_logs').select('*, subjects!inner(*)').eq('subjects.teacher_id', teacher_id).execute()
    records = response.data

    sessions_by_subject = {}
    recorded_rows = set()
    for record in records:
        subject_id = record.get('subject_id')
        timestamp = record.get('timestamp')
        student_id = record.get('student_id')
        if subject_id is None or timestamp is None:
            continue
        sessions_by_subject.setdefault(subject_id, set()).add(timestamp)
        recorded_rows.add((subject_id, timestamp, student_id))

    missing_rows = []
    for subject_id, timestamps in sessions_by_subject.items():
        enrolled = (
            supabase.table('subject_students')
            .select('student_id')
            .eq('subject_id', subject_id)
            .execute()
        )
        for enrollment in enrolled.data:
            student_id = enrollment.get('student_id')
            for timestamp in timestamps:
                if (subject_id, timestamp, student_id) not in recorded_rows:
                    missing_rows.append({
                        'student_id': student_id,
                        'subject_id': subject_id,
                        'timestamp': timestamp,
                        'is_present': False,
                    })

    if missing_rows:
        supabase.table('attendance_logs').insert(missing_rows).execute()
        # Re-read so the caller receives the repaired totals in this same view.
        response = supabase.table('attendance_logs').select('*, subjects!inner(*)').eq('subjects.teacher_id', teacher_id).execute()

    return response.data

@db_retry()
def get_session_details(subject_id, timestamp):
    """Fetch all attendance log entries for a specific session, joined with student names."""
    response = (
        supabase.table('attendance_logs')
        .select('*, students(name, student_id)')
        .eq('subject_id', subject_id)
        .eq('timestamp', timestamp)
        .execute()
    )
    return response.data

@db_retry()
def update_attendance_status(log_id, is_present):
    """Toggle the is_present status of a single attendance log entry."""
    response = (
        supabase.table('attendance_logs')
        .update({'is_present': is_present})
        .eq('id', log_id)
        .execute()
    )
    return response.data

@db_retry()
def delete_subject(subject_id):
    """Cascade-delete a subject and all its related data:
       attendance_logs → subject_students → subjects
    """
    supabase.table('attendance_logs').delete().eq('subject_id', subject_id).execute()
    supabase.table('subject_students').delete().eq('subject_id', subject_id).execute()
    supabase.table('subjects').delete().eq('subject_id', subject_id).execute()
