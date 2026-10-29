import unittest

from wordstats.counter import top_words


class TestTopWords(unittest.TestCase):
    def test_counts_are_case_insensitive(self):
        self.assertEqual(top_words("The the THE cat", 2), [("the", 3), ("cat", 1)])

    def test_ties_are_alphabetical(self):
        self.assertEqual(top_words("b a", 2), [("a", 1), ("b", 1)])

    def test_limit(self):
        self.assertEqual(len(top_words("a b c d", 2)), 2)

    def test_contractions_count_as_one_word(self):
        self.assertEqual(top_words("don't don't do", 1), [("don't", 2)])


if __name__ == "__main__":
    unittest.main()
