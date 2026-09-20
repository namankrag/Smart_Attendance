import streamlit as st
import time
from functools import wraps
from supabase import create_client, Client
import httpx

_supabase_client = None

def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(
            st.secrets["SUPABASE_URL"],
            st.secrets["SUPABASE_KEY"]
        )
    return _supabase_client

def reset_supabase_client():
    global _supabase_client
    try:
        if _supabase_client and hasattr(_supabase_client, 'postgrest'):
            _supabase_client.postgrest.session.close()
    except Exception:
        pass
    _supabase_client = create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )
    return _supabase_client

class SupabaseProxy:
    """Transparent proxy so existing `supabase.table(...)` code works with auto-reconnection."""
    def __getattr__(self, name):
        return getattr(get_supabase(), name)

supabase = SupabaseProxy()

def db_retry(max_retries=3, delay=0.5):
    """
    Decorator to automatically retry database queries and recreate the Supabase connection
    if a transient socket error (e.g. WinError 10054 remote host closed connection) occurs.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ReadError, ConnectionError, OSError) as e:
                    last_err = e
                    reset_supabase_client()
                    time.sleep(delay * (attempt + 1))
                except Exception as e:
                    err_msg = str(e).lower()
                    if "10054" in err_msg or "connection" in err_msg or "closed" in err_msg or "remote host" in err_msg:
                        last_err = e
                        reset_supabase_client()
                        time.sleep(delay * (attempt + 1))
                    else:
                        raise e
            raise last_err
        return wrapper
    return decorator