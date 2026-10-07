import streamlit as st
import time
from functools import wraps
from supabase import create_client, Client
import httpx

@st.cache_resource(show_spinner=False)
def _init_supabase_client() -> Client:
    """Thread-safe singleton Supabase client cached in Streamlit resource pool."""
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]
    return create_client(supabase_url, supabase_key)

def get_supabase() -> Client:
    """Retrieve the shared Supabase client."""
    return _init_supabase_client()

class SupabaseProxy:
    """Transparent thread-safe proxy forwarding calls to the cached Supabase client."""
    def __getattr__(self, name):
        return getattr(get_supabase(), name)

supabase = SupabaseProxy()

def db_retry(max_retries: int = 3, initial_delay: float = 0.5):
    """
    Exponential-backoff retry decorator for handling transient socket timeouts,
    connection resets, and temporary network disruptions.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (
                    httpx.ConnectError,
                    httpx.RemoteProtocolError,
                    httpx.ReadTimeout,
                    httpx.ConnectTimeout,
                    httpx.ReadError,
                    ConnectionError,
                    OSError
                ) as exc:
                    last_err = exc
                    sleep_time = initial_delay * (2 ** attempt)
                    time.sleep(sleep_time)
                except Exception as exc:
                    err_msg = str(exc).lower()
                    if any(token in err_msg for token in ("10054", "connection", "closed", "remote host", "timeout")):
                        last_err = exc
                        sleep_time = initial_delay * (2 ** attempt)
                        time.sleep(sleep_time)
                    else:
                        raise exc
            raise last_err
        return wrapper
    return decorator