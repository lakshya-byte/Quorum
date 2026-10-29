"""Plain-text report."""
from wordstats.counter import top_words


def format_report(text, n=3):
    return "\n".join(f"{word}: {count}" for word, count in top_words(text, n))
