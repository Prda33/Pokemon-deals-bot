import unittest

from bot import Listing, evaluate, language_status, norm, price_number


class BotTests(unittest.TestCase):
    def test_price_parser(self):
        self.assertEqual(price_number("12,50 €"), 12.5)
        self.assertEqual(price_number({"amount": "9.99"}), 9.99)

    def test_language_filter(self):
        fr = Listing("Vinted", "1", "Dracaufeu version française", 10, "https://example.test")
        jp = Listing("Vinted", "2", "Dracaufeu japonais", 10, "https://example.test")
        self.assertEqual(language_status(fr), "confirmed")
        self.assertEqual(language_status(jp), "foreign")

    def test_deal_evaluation(self):
        listing = Listing("Vinted", "3", "Dracaufeu ex FR", 50, "https://example.test")
        index = [{"id": 10, "name": "Dracaufeu ex", "norm": norm("Dracaufeu ex"), "reference": 100.0}]
        deal = evaluate(listing, index)
        self.assertIsNotNone(deal)
        self.assertGreaterEqual(deal["discount"], 49)

    def test_fake_is_rejected(self):
        listing = Listing("Vinted", "4", "Dracaufeu proxy française", 2, "https://example.test")
        index = [{"id": 10, "name": "Dracaufeu", "norm": norm("Dracaufeu"), "reference": 100.0}]
        self.assertIsNone(evaluate(listing, index))


if __name__ == "__main__":
    unittest.main()
