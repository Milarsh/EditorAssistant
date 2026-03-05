from sentence_transformers import SentenceTransformer
from transformers import pipeline
import numpy as np

from sklearn.feature_extraction.text import TfidfVectorizer
import pymorphy3
import re
import heapq

#Sentence Transformers ML model

def smlrty(a, b):
    if np.linalg.norm(a) * np.linalg.norm(b) != 0:
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    return 0

def ml_relevance(text, kwords):

    st = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')

    #sentence transformers
    st_text = st.encode(text)
    st_kwords = st.encode(kwords)

    scrs = [smlrty(st_text, kword) for kword in st_kwords]

    return scrs

# TD-IDF

def lemmatize_russian(text: str) -> str:

    morph = pymorphy3.MorphAnalyzer()
    words = re.sub(r'[^\w\s]', ' ', text.lower()).split()
    lemmatized = []

    for word in words:
        parsed = morph.parse(word)[0]
        lemmatized.append(parsed.normal_form)

    return ' '.join(lemmatized)

def tfidf_relevance(text: str, keywords: list) -> list:

    processed_text = lemmatize_russian(text)

    processed_keywords = [lemmatize_russian(kw) for kw in keywords]

    vectorizer = TfidfVectorizer(ngram_range=(1, 2))
    tfidf_matrix = vectorizer.fit_transform([processed_text])

    feature_names = vectorizer.get_feature_names_out()
    scores = tfidf_matrix.toarray()[0]
    score_dict = dict(zip(feature_names, scores))

    scrs = [score_dict.get(kw, 0.0) for kw in processed_keywords]

    return scrs

# ---------------------------

def Relevance(text, kwords):

    ml_scrs = ml_relevance(text, kwords)
    tfidf_scrs = tfidf_relevance(text, kwords)

    if all([el < 0.3 for el in ml_scrs]):

        return tfidf_scrs

    if all([el < 0.3 for el in tfidf_scrs]):

        return ml_scrs

    return [ 0.5*(ml_scrs[i] + tfidf_scrs[i]) for i in range(len(kwords)) ]