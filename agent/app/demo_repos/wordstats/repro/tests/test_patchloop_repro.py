import unittest

from wordstats.counter import top_words


class TestContractionReproducer(unittest.TestCase):
    def test_apostrophe_words_are_counted_as_one_word(self):
        self.assertEqual(top_words("Can't stop, can't won't", 2), [("can't", 2), ("stop", 1)])


if __name__ == "__main__":
    unittest.main()
