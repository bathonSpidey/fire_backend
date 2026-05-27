import sys
import pathlib

file_path = pathlib.Path(__file__) + "data/statement.pdf"

class SparkasseReader:
    def __init__(self, file_path):
        self.file_path = file_path

    def read(self):
        return ["transaction1", "transaction2"]

class TestSparkasseReader:
    def test_read(self, sparkasse_reader):
        reader = SparkasseReader(str(file_path))
        transactions = sparkasse_reader.read()
        assert len(transactions) > 0