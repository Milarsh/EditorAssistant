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
from src.utils.settings import get_setting_bool

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


def _collect_article_text(article: Article) -> str:
    return " ".join(part for part in (article.title, article.description) if part)


def _persist_article_analysis(
    session,
    article: Article,
    stop_counts_by_id: dict,
    stop_total: int,
    category_counts,
    key_counts_by_id: dict,
    key_total: int,
    rubric_counts,
) -> ArticleStat:
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
    stats.key_words_count = int(key_total)
    stats.rubric_id = rubric_id
    stats.stop_category_id = stop_category_id

    session.commit()
    session.refresh(stats)
    return stats


def _analyze_article_words_legacy(session, article: Article) -> ArticleStat:
    full_text = _collect_article_text(article)

    stop_words = session.execute(select(StopWord)).scalars().all()
    stop_items = [(w.id, w.value, w.category_id) for w in stop_words]
    stop_counts_by_id, stop_total, category_counts = count_words_for_items(
        stop_items, full_text
    )

    key_words = session.execute(select(KeyWord)).scalars().all()
    key_items = [(w.id, w.value, w.rubric_id) for w in key_words]
    key_counts_by_id, key_total, rubric_counts = count_words_for_items(
        key_items, full_text
    )

    return _persist_article_analysis(
        session,
        article,
        stop_counts_by_id,
        stop_total,
        category_counts,
        key_counts_by_id,
        key_total,
        rubric_counts,
    )


def _analyze_article_words_ml(session, article: Article) -> ArticleStat:
    full_text = _collect_article_text(article)

    stop_words = session.execute(select(StopWord)).scalars().all()
    stop_items = [(w.id, w.value, w.category_id) for w in stop_words]
    stop_counts_by_id, stop_total, category_counts = count_words_for_items(
        stop_items, full_text
    )

    keywords = session.execute(select(KeyWord)).scalars().all()
    keyword_texts = [kw.value for kw in keywords]
    key_counts_by_id = {}
    rubric_counts = defaultdict(int)

    relevance_scores = Relevance(full_text, keyword_texts) if keyword_texts else []
    if relevance_scores:
        threshold = 0.45
        for kw, score in zip(keywords, relevance_scores):
            if score > threshold:
                key_counts_by_id[kw.id] = float(score)
                rubric_counts[kw.rubric_id] += 1

        if not key_counts_by_id:
            best_idx = max(
                range(len(relevance_scores)),
                key=relevance_scores.__getitem__,
            )
            best_kw = keywords[best_idx]
            key_counts_by_id[best_kw.id] = float(relevance_scores[best_idx])
            rubric_counts[best_kw.rubric_id] += 1

    return _persist_article_analysis(
        session,
        article,
        stop_counts_by_id,
        stop_total,
        category_counts,
        key_counts_by_id,
        len(key_counts_by_id),
        rubric_counts,
    )


def analyze_article_words(
    session,
    article_id: int,
    use_ml_analysis: bool | None = None,
) -> ArticleStat:
    article = session.get(Article, article_id)
    if not article:
        raise ValueError(f"Article {article_id} not found")

    if use_ml_analysis is None:
        use_ml_analysis = get_setting_bool("use_ml_news_analysis", False)

    if use_ml_analysis:
        return _analyze_article_words_ml(session, article)
    return _analyze_article_words_legacy(session, article)


def analyze_all_articles(session) -> int:
    use_ml_analysis = get_setting_bool("use_ml_news_analysis", False)
    processed = 0
    article_ids = session.execute(select(Article.id)).scalars().all()

    for article_id in article_ids:
        try:
            analyze_article_words(
                session,
                article_id,
                use_ml_analysis=use_ml_analysis,
            )
            processed += 1
        except Exception as exception:
            session.rollback()
            print(f"[WARN] failed to analyze article {article_id}: {exception}")

    return processed
