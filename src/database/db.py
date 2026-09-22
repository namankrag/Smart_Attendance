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
    """Enroll a student and backfill missing historical sessions as absent.

    If attendance records already exist (from a previous enrollment), they are
    preserved. Only creates absent records for sessions the student has no record for.
    This ensures re-enrollment preserves actual attendance history.
    """
    # Get all timestamps for this subject
    prior_sessions = (
        supabase.table('attendance_logs')
        .select('timestamp')
        .eq('subject_id', subject_id)
        .execute()
    )
    all_timestamps = sorted({row.get('timestamp') for row in prior_sessions.data if row.get('timestamp')})

    # Create the enrollment record
    data = {'student_id': student_id, 'subject_id': subject_id}
    response = supabase.table('subject_students').insert(data).execute()

    if all_timestamps:
        # Check which timestamps already have records for this student
        existing_records = (
            supabase.table('attendance_logs')
            .select('timestamp')
            .eq('student_id', student_id)
            .eq('subject_id', subject_id)
            .execute()
        )
        existing_timestamps = {row.get('timestamp') for row in existing_records.data if row.get('timestamp')}
        
        # Only create absent records for timestamps that don't already exist
        missing_timestamps = [ts for ts in all_timestamps if ts not in existing_timestamps]
        
        if missing_timestamps:
            historic_absences = [
                {
                    'student_id': student_id,
                    'subject_id': subject_id,
                    'timestamp': timestamp,
                    'is_present': False,
                }
                for timestamp in missing_timestamps
            ]
            supabase.table('attendance_logs').insert(historic_absences).execute()
    
    return response.data

@db_retry()
def unenroll_student_to_subject(student_id, subject_id):
    """Unenroll a student from a subject.
    
    Only removes the enrollment record from subject_students table.
    Attendance logs are preserved for historical record - they will be filtered
    out of teacher views but restored if the student re-enrolls.
    """
    try:
        # Delete only the enrollment record, keep attendance history
        enroll_response = supabase.table('subject_students').delete().eq('student_id', student_id).eq('subject_id', subject_id).execute()
        return {"success": True, "enrollment_deleted": len(enroll_response.data)}
    except Exception as e:
        return {"success": False, "error": str(e)}

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
    """Get all attendance records for a student."""
    response = supabase.table('attendance_logs').select('*, subjects(*)').eq('student_id', student_id).execute()
    return response.data

@db_retry()
def create_attendance(logs):
    response = supabase.table('attendance_logs').insert(logs).execute()
    return response.data

@db_retry()
def get_attendance_for_teacher(teacher_id):
    """Return attendance records filtered to currently-enrolled students only.

    Only includes attendance logs for students who are actively enrolled in each
    subject. When a student unenrolls, their historical attendance is hidden from
    the teacher's view. When they re-enroll, it reappears.
    """
    # Get all attendance logs for this teacher's subjects
    response = supabase.table('attendance_logs').select('*, subjects!inner(*)').eq('subjects.teacher_id', teacher_id).execute()
    records = response.data

    # Get all subjects for this teacher
    subjects_response = supabase.table('subjects').select('subject_id').eq('teacher_id', teacher_id).execute()
    subject_ids = [s['subject_id'] for s in subjects_response.data]
    
    if not subject_ids:
        return []
    
    # Get currently enrolled students for all these subjects
    enrolled_response = supabase.table('subject_students').select('student_id, subject_id').in_('subject_id', subject_ids).execute()
    
    # Build set of (subject_id, student_id) tuples for currently enrolled students
    current_enrollments = {(e['subject_id'], e['student_id']) for e in enrolled_response.data}
    
    # Filter records to only include currently-enrolled students
    filtered_records = [
        record for record in records
        if (record.get('subject_id'), record.get('student_id')) in current_enrollments
    ]

    return filtered_records

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
