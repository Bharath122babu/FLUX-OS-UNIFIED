"""Operator-provided acceptance test. Use with the goal: create hello.py: greet() -> 'hello'."""
import unittest
from hello import greet

class HelloAcceptance(unittest.TestCase):
    def test_greet(self):
        self.assertEqual(greet(), 'hello')
