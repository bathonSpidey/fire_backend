

from services.transaction_classifier import TransactionClassifier


class TestTransactionClassifier:
    def test_classify_transaction(self):
        # Test cases for each category
        classifier = TransactionClassifier()
        test_cases = [
            ("Lastschrift\nFitness Forum Baden-Baden GmbH Easy Fitness Baden-Baden", "FIXED_COSTS"),
            ("Kartenzahlung\nstar Tankstelle", "AUTOMOTIVE"),
            ("Parkhaus APCOA", "PARKING"),
            ("Kaufland Supermarket", "GROCERIES"),
            ("Amazon Online Shopping", "ONLINE_SHOPPING"),
            ("Wise Europe Transfer", "REMITTANCE"),
            ("Lohn, Gehalt Payment", "SALARY"),
            ("Finanzamt Tax Payment", "TAX_OR_INVEST"),
            ("Unknown Merchant", "OTHER_EXPENSE")
        ]

        for description, expected_category in test_cases:
            category = classifier.assign_category(description, -0.01)
            assert category == expected_category, f"Expected {expected_category} but got {category} for description '{description}'"