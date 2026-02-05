from sentence_transformers import SentenceTransformer
from transformers import pipeline
import numpy as np

st = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')

def Relevance(text, kwords):

    #sentence transformers
    st_text = st.encode(text)
    st_kwords = st.encode(kwords)

    def smlrty(a, b):
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

    scores = [smlrty(st_text, kword) for kword in st_kwords]

    best_idx = np.argmax(scores)

    return scores[best_idx], kwords[best_idx], 