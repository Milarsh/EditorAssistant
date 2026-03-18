from sentence_transformers import SentenceTransformer
import numpy as np


st = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')

ML_RELEVANCE_THRESHOLD = 0.65


def smlrty(a, b):
    if np.linalg.norm(a) * np.linalg.norm(b) != 0:
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    return 0


def ml_relevance(text, kwords):
    if not text or not kwords:
        return []

    st_text = st.encode(text)
    st_kwords = st.encode(kwords)

    scrs = [smlrty(st_text, kword) for kword in st_kwords]

    return scrs

def select_relevance_scores(text, kwords):
    ml_scrs = ml_relevance(text, kwords)
    return ml_scrs, ML_RELEVANCE_THRESHOLD


def Relevance(text, kwords):
    scores, _ = select_relevance_scores(text, kwords)
    return scores