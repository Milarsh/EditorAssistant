import re
from collections import Counter, defaultdict

import pymorphy3
from sqlalchemy import select, delete

from src.db.models.article import Article
from src.db.models.stop_word import StopWord
from src.db.models.key_word import KeyWord
from src.db.models.article_stop_word import ArticleStopWord
from src.db.models.article_key_word import ArticleKeyWord
from src.db.models.article_stat import ArticleStat
from src.utils.relevance import Relevance

_morph = pymorphy3.MorphAnalyzer()

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+")


def _normalize_text_to_counter(text: str) -> Counter:
    text = text or ""
    lemmas = []
    for match in _WORD_RE.finditer(text):
        word = match.group(0).lower()
        parsed = _morph.parse(word)[0]
        lemmas.append(parsed.normal_form)
    return Counter(lemmas)


def _build_index(word_items):
    index = {}

    for wid, value, group_id in word_items:
        value = (value or "").strip()
        if not value:
            continue

        parsed = _morph.parse(value.lower())[0]
        lemma = parsed.normal_form

        data = index.get(lemma)
        if data is None:
            data = {"ids": [], "group_ids": set()}
            index[lemma] = data

        data["ids"].append(wid)
        if group_id is not None:
            data["group_ids"].add(group_id)

    return index


def count_words_for_items(word_items, text: str):
    tokens_counter = _normalize_text_to_counter(text)
    index = _build_index(word_items)

    counts_by_id = {}
    total = 0
    group_counts = defaultdict(int)

    for lemma, data in index.items():
        c = tokens_counter.get(lemma, 0)
        if not c:
            continue

        total += c

        for wid in data["ids"]:
            counts_by_id[wid] = counts_by_id.get(wid, 0) + c

        for gid in data["group_ids"]:
            group_counts[gid] += c

    return counts_by_id, total, group_counts


def analyze_article_words(session, article_id: int) -> ArticleStat:
    article = session.get(Article, article_id)
    if not article:
        raise ValueError(f"Article {article_id} not found")

    text_parts = []
    if getattr(article, "title", None):
        text_parts.append(article.title)
    if getattr(article, "description", None):
        text_parts.append(article.description)
    full_text = " ".join(text_parts)

    stop_words = session.execute(select(StopWord)).scalars().all()
    stop_items = [(w.id, w.value, w.category_id) for w in stop_words]

    stop_counts_by_id, stop_total, category_counts = count_words_for_items(
        stop_items, full_text
    )

    # ave -
    key_words = session.execute(select(KeyWord)).scalars().all()
    key_items = [(w.id, w.value, w.rubric_id) for w in key_words]

    key_texts = [w.value for w in key_words if w.value and w.value.strip()]

    key_counts_by_id = {}
    key_total = 0
    rubric_counts = defaultdict(int)

    for idx, key_word in enumerate(key_words):
            rel, _ = Relevance(full_text, key_word) # in [0;1]
            if rel > 0.3:
                key_counts_by_id[key_word.id] = rel
                key_total += 1
                rubric_counts[key_word.rubric_id] += 1
    # - ave
    
    session.execute(
        delete(ArticleStopWord).where(ArticleStopWord.entity_id == article.id)
    )
    session.execute(
        delete(ArticleKeyWord).where(ArticleKeyWord.entity_id == article.id)
    )

    for stop_id, count in stop_counts_by_id.items():
        if count > 0:
            session.add(
                ArticleStopWord(entity_id=article.id, stop_word_id=stop_id)
            )

    for key_id, count in key_counts_by_id.items():
        if count > 0:
            session.add(
                ArticleKeyWord(entity_id=article.id, key_word_id=key_id)
            )

    rubric_id = None
    if rubric_counts:
        rubric_id = sorted(
            rubric_counts.items(), key=lambda it: (-it[1], it[0])
        )[0][0]

    stop_category_id = None
    if category_counts:
        stop_category_id = sorted(
            category_counts.items(), key=lambda it: (-it[1], it[0])
        )[0][0]

    stats = session.get(ArticleStat, article.id)
    if not stats:
        stats = ArticleStat(entity_id=article.id)
        session.add(stats)

    stats.stop_words_count = int(stop_total)
    stats.key_words_count = int(key_counts_by_id)
    stats.rubric_id = rubric_id
    stats.stop_category_id = stop_category_id

    session.commit()
    session.refresh(stats)
    return stats
