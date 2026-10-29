import unittest

from wordstats.tokenizer import tokenize


class TestTokenize(unittest.TestCase):
    def test_splits_words(self):
        self.assertEqual(tokenize("hello world"), ["hello", "world"])

    def test_lowercases(self):
        self.assertEqual(tokenize("Hello WORLD"), ["hello", "world"])

    def test_keeps_contractions_whole(self):
        self.assertEqual(tokenize("don't stop"), ["don't", "stop"])

    def test_ignores_punctuation(self):
        self.assertEqual(tokenize("a, b; c!"), ["a", "b", "c"])

    def test_digits_split_words(self):
        self.assertEqual(tokenize("abc123def"), ["abc", "def"])


if __name__ == "__main__":
    unittest.main()
