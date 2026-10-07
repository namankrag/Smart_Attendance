import librosa
import numpy as np
import io
import streamlit as st
from resemblyzer import VoiceEncoder, preprocess_wav

@st.cache_resource
def load_voice_encoder():
    return VoiceEncoder()


def get_voice_embedding(audio_bytes):
    try:
        encoder = load_voice_encoder()
        audio, sr = librosa.load(io.BytesIO(audio_bytes), sr=16000)
        wav = preprocess_wav(audio)
        embedding = encoder.embed_utterance(wav)
        return embedding.tolist()

    except Exception as e:
        st.error("Voice recognition error")
        return None


def identify_speaker(new_embedding, candidate_dict, threshold = 0.65):
    if new_embedding is None or not candidate_dict:
        return None, 0.0

    valid_candidates = [(sid, emb) for sid, emb in candidate_dict.items() if emb]
    if not valid_candidates:
        return None, 0.0

    sids, embeddings = zip(*valid_candidates)
    emb_matrix = np.array(embeddings, dtype=np.float32)  # (N_candidates, 256)
    new_vec = np.array(new_embedding, dtype=np.float32)

    # Vectorized cosine similarity dot product in one matrix operation
    similarities = np.dot(emb_matrix, new_vec)
    best_idx = int(np.argmax(similarities))
    best_score = float(similarities[best_idx])

    if best_score >= threshold:
        return sids[best_idx], best_score

    return None, best_score


def process_bulk_audio(audio_bytes, candidate_dict, threshold = 0.65):
    try:
        encoder = load_voice_encoder()
        audio, sr = librosa.load(io.BytesIO(audio_bytes), sr = 16000)
        segments = librosa.effects.split(audio, top_db=30)
        identified_result = {}

        for start, end in segments:
            if (end-start) < sr * 0.5:
                continue
            segment_audio = audio[start:end]
            wav = preprocess_wav(segment_audio)
            embedding = encoder.embed_utterance(wav)

            sid, score = identify_speaker(embedding, candidate_dict, threshold)
            if sid:
                if sid not in identified_result or score > identified_result[sid]:
                    identified_result[sid] = score
        return identified_result
    except Exception as e:
        st.error(f"Bulk Process Error: {e}")
        return {}