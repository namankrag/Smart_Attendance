from typing import Dict, Tuple, Optional, Any
import io
import librosa
import numpy as np
import streamlit as st
from resemblyzer import VoiceEncoder, preprocess_wav

@st.cache_resource(show_spinner=False)
def load_voice_encoder() -> VoiceEncoder:
    """Load and cache pre-trained speaker embedding network."""
    return VoiceEncoder()

def _normalize(v: np.ndarray) -> np.ndarray:
    """L2-normalize an embedding vector for true cosine dot product."""
    norm = np.linalg.norm(v)
    return v / (norm + 1e-10)

def get_voice_embedding(audio_bytes: Optional[bytes]) -> Optional[list]:
    """Generate normalized 256-D voice embedding from raw audio bytes."""
    if not audio_bytes:
        return None
    try:
        encoder = load_voice_encoder()
        audio, _ = librosa.load(io.BytesIO(audio_bytes), sr=16000)
        wav = preprocess_wav(audio)
        embedding = encoder.embed_utterance(wav)
        normalized = _normalize(embedding)
        return normalized.tolist()
    except Exception as exc:
        st.warning(f"Voice feature extraction note: {exc}")
        return None

def identify_speaker(
    new_embedding: Optional[list], 
    candidate_dict: Dict[int, list], 
    threshold: float = 0.65
) -> Tuple[Optional[int], float]:
    """
    Match query speaker embedding against candidate dictionary via normalized cosine similarity.
    Returns: (matched_student_id, confidence_score)
    """
    if not new_embedding or not candidate_dict:
        return None, 0.0

    valid_candidates = [(sid, emb) for sid, emb in candidate_dict.items() if emb and len(emb) == 256]
    if not valid_candidates:
        return None, 0.0

    sids, embeddings = zip(*valid_candidates)
    
    # Ensure all vectors are L2-normalized
    emb_matrix = np.array([_normalize(np.array(e, dtype=np.float32)) for e in embeddings], dtype=np.float32)
    query_vec = _normalize(np.array(new_embedding, dtype=np.float32))

    # Vectorized cosine similarity dot product
    similarities = np.dot(emb_matrix, query_vec)
    best_idx = int(np.argmax(similarities))
    best_score = float(similarities[best_idx])

    if best_score >= threshold:
        return sids[best_idx], best_score

    return None, best_score

def process_bulk_audio(
    audio_bytes: Optional[bytes], 
    candidate_dict: Dict[int, list], 
    threshold: float = 0.65
) -> Dict[int, float]:
    """
    Segment classroom speech audio and identify all present speakers.
    Returns mapping: student_id -> highest_confidence_score
    """
    if not audio_bytes:
        return {}

    try:
        encoder = load_voice_encoder()
        audio, sr = librosa.load(io.BytesIO(audio_bytes), sr=16000)
        segments = librosa.effects.split(audio, top_db=28)
        identified_results: Dict[int, float] = {}

        for start, end in segments:
            # Skip noise blips shorter than 0.4s
            if (end - start) < (sr * 0.4):
                continue
            segment_audio = audio[start:end]
            wav = preprocess_wav(segment_audio)
            embedding = encoder.embed_utterance(wav)
            norm_emb = _normalize(embedding).tolist()

            sid, score = identify_speaker(norm_emb, candidate_dict, threshold=threshold)
            if sid:
                if sid not in identified_results or score > identified_results[sid]:
                    identified_results[sid] = score

        return identified_results
    except Exception as exc:
        st.error(f"Bulk voice recognition failure: {exc}")
        return {}