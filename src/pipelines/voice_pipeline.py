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
        st.error("Voice recogmition error")
        return None


def identify_speaker(new_embedding, candidate_dict, threshold = 0.65):
    if new_embedding is None or not candidate_dict:
        return None, 0.0

    best_sid = None
    best_score = -1.0

    for sid, stored_embedding in candidate_dict.items():
        if stored_embedding:
            similarity = np.dot(new_embedding, stored_embedding)
            if similarity > best_score:
                best_score = similarity
                best_sid = sid

    if best_score >= threshold:
        return best_sid, best_score

    return None, best_score


def process_bulk_audio(audio_bytes, candidate_dict, threshold = 0.65):
    try:
        encoder = load_voice_encoder()
        audio, sr = librosa.load(io.BytesIO(audio_bytes), sr = 16000)
        segments = librosa.effects.split(audio, top_db=30)
        identified_result = []

        for start, end in segments:
            if (end-start) < sr * 0.5:
                continue
            segment_audio = audio[start:end]
            wav = preprocess_wav(segment_audio)
            embedding = encoder.embed_utterance(wav)

            sid, score = identify_speaker(embedding, candidate_dict, threshold)
            if sid :
                if sid not in identified_result or score > identified_result[sid]:
                    identified_result[sid] = score
        return identified_result
    except Exception as e:
        st.error("Bulk Process Error")
        return {}