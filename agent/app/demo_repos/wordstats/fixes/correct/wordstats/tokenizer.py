"""Split text into words."""
import re


def tokenize(text):
    """Lower-case words; an apostrophe inside a word (don't) stays part of the word."""
    return re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())
