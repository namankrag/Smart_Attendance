from typing import List, Dict, Any, Optional
from src.database.config import supabase, db_retry
import bcrypt

def hash_pass(pwd: str) -> str:
    """Hash a plaintext password or PIN using bcrypt."""
    if not pwd:
        raise ValueError("Password/PIN cannot be empty")
    return bcrypt.hashpw(pwd.strip().encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def check_pass(pwd: str, hashed: str) -> bool:
    """Validate a plaintext password or PIN against its bcrypt hash."""
    if not pwd or not hashed:
        return False
    try:
        return bcrypt.checkpw(pwd.strip().encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

# ==========================================
# Teacher Authentication & Profiles
# ==========================================

@db_retry()
def check_teacher_exists(username: str) -> bool:
    username = username.strip().lower()
    response = supabase.table("teachers").select("username").eq("username", username).limit(1).execute()
    return bool(response.data)

@db_retry()
def create_teacher(username: str, password: str, name: str) -> List[Dict[str, Any]]:
    username = username.strip().lower()
    name = name.strip()
    data = {
        "username": username,
        "password": hash_pass(password),
        "name": name
    }
    response = supabase.table("teachers").insert(data).execute()
    return response.data or []

@db_retry()
def teacher_login(username: str, password: str) -> Optional[Dict[str, Any]]:
    username = username.strip().lower()
    response = supabase.table("teachers").select("*").eq("username", username).limit(1).execute()
    if response.data:
        teacher = response.data[0]
        if check_pass(password, teacher.get("password", "")):
            return teacher
    return None

# ==========================================
# Student Profiles & Biometrics
# ==========================================

@db_retry()
def get_all_students() -> List[Dict[str, Any]]:
    """Retrieve all student records for facial and voice classifier construction."""
    response = supabase.table("students").select("student_id, name, face_embedding, voice_embedding").execute()
    return response.data or []

@db_retry()
def get_student_by_id(student_id: int) -> Optional[Dict[str, Any]]:
    response = supabase.table("students").select("*").eq("student_id", student_id).limit(1).execute()
    return response.data[0] if response.data else None

@db_retry()
def create_student(
    name: str, 
    face_embedding: Optional[Any] = None, 
    voice_embedding: Optional[Any] = None,
    pin: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Register a new student profile with face/voice biometric embeddings and optional PIN."""
    name = name.strip()
    data: Dict[str, Any] = {
        "name": name,
        "face_embedding": face_embedding,
        "voice_embedding": voice_embedding
    }
    if pin:
        data["pin_hash"] = hash_pass(pin)
    
    try:
        response = supabase.table("students").insert(data).execute()
        return response.data or []
    except Exception as exc:
        # Fallback if pin_hash column does not exist yet in schema
        if "pin_hash" in str(exc).lower() and pin:
            data.pop("pin_hash", None)
            response = supabase.table("students").insert(data).execute()
            return response.data or []
        raise exc

@db_retry()
def add_student_face_embedding(student_id: int, new_embedding: List[float], max_embeddings: int = 5) -> Optional[List[Dict[str, Any]]]:
    """
    Append an additional biometric face embedding to a student profile (e.g. glasses, new haircut).
    Capped at max_embeddings to prevent biometric gallery bloat.
    """
    if not isinstance(new_embedding, list) or len(new_embedding) != 128:
        raise ValueError("New face embedding must be a 128-dimensional vector")

    response = supabase.table("students").select("face_embedding").eq("student_id", student_id).limit(1).execute()
    if not response.data:
        return None

    current_emb = response.data[0].get("face_embedding")
    all_embeddings: List[List[float]] = []

    if current_emb:
        if isinstance(current_emb, list) and len(current_emb) > 0:
            if isinstance(current_emb[0], (int, float)) and len(current_emb) == 128:
                all_embeddings.append(current_emb)
            elif isinstance(current_emb[0], list):
                for item in current_emb:
                    if isinstance(item, list) and len(item) == 128:
                        all_embeddings.append(item)

    all_embeddings.append(new_embedding)
    # Retain the most recent embeddings if max exceeded
    if len(all_embeddings) > max_embeddings:
        all_embeddings = all_embeddings[-max_embeddings:]

    update_resp = supabase.table("students").update({"face_embedding": all_embeddings}).eq("student_id", student_id).execute()
    return update_resp.data

# ==========================================
# Subject & Classroom Management
# ==========================================

@db_retry()
def create_subject(sub_code: str, name: str, sec: str, teacher_id: Any) -> List[Dict[str, Any]]:
    sub_code = sub_code.strip().upper()
    name = name.strip()
    sec = sec.strip().upper()
    data = {
        "subject_code": sub_code,
        "name": name,
        "section": sec,
        "teacher_id": teacher_id
    }
    response = supabase.table("subjects").insert(data).execute()
    return response.data or []

@db_retry()
def get_teacher_subjects(teacher_id: Any) -> List[Dict[str, Any]]:
    """Retrieve all subjects owned by a teacher with computed student counts and session counts."""
    response = (
        supabase.table("subjects")
        .select("*, subject_students(count), attendance_logs(timestamp)")
        .eq("teacher_id", teacher_id)
        .execute()
    )

    subjects = response.data or []
    for sub in subjects:
        sub["total_students"] = sub.get("subject_students", [{}])[0].get("count", 0) if sub.get("subject_students") else 0
        attend = sub.get("attendance_logs", [])
        unique_sessions = len({log["timestamp"] for log in attend if log.get("timestamp")})
        sub["total_classes"] = unique_sessions
        sub.pop("subject_students", None)
        sub.pop("attendance_logs", None)

    return subjects

@db_retry()
def enroll_student_to_subject(student_id: int, subject_id: int) -> List[Dict[str, Any]]:
    """
    Idempotently enroll a student in a subject without writing synthetic historical logs.
    Historical absence is calculated dynamically at query/view time.
    """
    data = {"student_id": student_id, "subject_id": subject_id}
    # Check if already enrolled
    existing = (
        supabase.table("subject_students")
        .select("id")
        .eq("student_id", student_id)
        .eq("subject_id", subject_id)
        .execute()
    )
    if existing.data:
        return existing.data

    response = supabase.table("subject_students").insert(data).execute()
    return response.data or []

@db_retry()
def unenroll_student_to_subject(student_id: int, subject_id: int) -> Dict[str, Any]:
    """Unenroll a student from a subject by removing their enrollment record."""
    try:
        enroll_response = (
            supabase.table("subject_students")
            .delete()
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .execute()
        )
        return {
            "success": True,
            "enrollment_deleted": len(enroll_response.data or [])
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}

@db_retry()
def get_student_subjects(student_id: int) -> List[Dict[str, Any]]:
    """Fetch subjects enrolled by a student along with distinct class sessions."""
    response = (
        supabase.table("subject_students")
        .select("*, subjects(*, attendance_logs(timestamp))")
        .eq("student_id", student_id)
        .execute()
    )
    enrollments = response.data or []

    for item in enrollments:
        sub = item.get("subjects")
        if sub:
            attend = sub.get("attendance_logs", [])
            session_timestamps = sorted({log["timestamp"] for log in attend if log.get("timestamp")})
            sub["total_classes"] = len(session_timestamps)
            sub["session_timestamps"] = session_timestamps
            sub.pop("attendance_logs", None)

    return enrollments

# ==========================================
# Attendance Operations
# ==========================================

@db_retry()
def get_student_attendance(student_id: int) -> List[Dict[str, Any]]:
    """Get all attendance records logged for a student."""
    response = (
        supabase.table("attendance_logs")
        .select("*, subjects(*)")
        .eq("student_id", student_id)
        .execute()
    )
    return response.data or []

@db_retry()
def create_attendance(logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Batch-insert attendance records for a classroom session."""
    if not logs:
        return []
    response = supabase.table("attendance_logs").insert(logs).execute()
    return response.data or []

@db_retry()
def get_attendance_for_teacher(teacher_id: Any) -> List[Dict[str, Any]]:
    """Return all attendance records for subjects owned by this teacher."""
    subjects_response = (
        supabase.table("subjects")
        .select("subject_id, name, subject_code")
        .eq("teacher_id", teacher_id)
        .execute()
    )
    subject_map = {s["subject_id"]: s for s in (subjects_response.data or [])}
    subject_ids = list(subject_map.keys())

    if not subject_ids:
        return []

    # Fetch all logged attendance records for these subjects
    records_response = (
        supabase.table("attendance_logs")
        .select("*")
        .in_("subject_id", subject_ids)
        .execute()
    )
    records = records_response.data or []

    for record in records:
        record["subjects"] = subject_map.get(record.get("subject_id"), {})

    return records

@db_retry()
def get_session_details(subject_id: int, timestamp: str) -> List[Dict[str, Any]]:
    """Fetch attendance records for a single session joined with student names."""
    response = (
        supabase.table("attendance_logs")
        .select("*, students(name, student_id)")
        .eq("subject_id", subject_id)
        .eq("timestamp", timestamp)
        .execute()
    )
    return response.data or []

@db_retry()
def update_attendance_status(log_id: int, is_present: bool) -> List[Dict[str, Any]]:
    """Update individual attendance status for an existing session log."""
    response = (
        supabase.table("attendance_logs")
        .update({"is_present": is_present})
        .eq("id", log_id)
        .execute()
    )
    return response.data or []

@db_retry()
def delete_subject(subject_id: int) -> None:
    """Delete a subject and its associated attendance and enrollment relations."""
    supabase.table("attendance_logs").delete().eq("subject_id", subject_id).execute()
    supabase.table("subject_students").delete().eq("subject_id", subject_id).execute()
    supabase.table("subjects").delete().eq("subject_id", subject_id).execute()
