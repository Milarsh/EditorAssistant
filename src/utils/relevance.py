from sklearn.feature_extraction.text import TfidfVectorizer
import pymorphy3
import re

TFIDF_RELEVANCE_THRESHOLD = 0.075

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
    if not text or not keywords:
        return [] if not keywords else [0.0 for _ in keywords]

    processed_text = lemmatize_russian(text)

    processed_keywords = [lemmatize_russian(kw) for kw in keywords]

    vectorizer = TfidfVectorizer(ngram_range=(1, 2))
    try:
        tfidf_matrix = vectorizer.fit_transform([processed_text])
    except ValueError:
        return [0.0 for _ in keywords]

    feature_names = vectorizer.get_feature_names_out()
    scores = tfidf_matrix.toarray()[0]
    score_dict = dict(zip(feature_names, scores))

    scrs = [score_dict.get(kw, 0.0) for kw in processed_keywords]

    return scrs

# ---------------------------

def select_relevance_scores(text, kwords):
    tfidf_scrs = tfidf_relevance(text, kwords)
    return tfidf_scrs, TFIDF_RELEVANCE_THRESHOLD


def Relevance(text, kwords):
    scores, _ = select_relevance_scores(text, kwords)
    return scores