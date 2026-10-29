"""Count words."""
from collections import Counter

from wordstats.tokenizer import tokenize


def top_words(text, n=3):
    """The n most common words as (word, count), ties broken alphabetically."""
    counts = Counter(tokenize(text))
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:n]
