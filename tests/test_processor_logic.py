
import unittest
from unittest.mock import MagicMock, patch
import sys
import os
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils import to_chinese_numeral
from src.processor import AIProcessor

class TestUtils(unittest.TestCase):
    def test_to_chinese_numeral(self):
        self.assertEqual(to_chinese_numeral(1), "一")
        self.assertEqual(to_chinese_numeral(10), "十")
        self.assertEqual(to_chinese_numeral(11), "十一")
        self.assertEqual(to_chinese_numeral(20), "二十")
        self.assertEqual(to_chinese_numeral(21), "二十一")
        self.assertEqual(to_chinese_numeral(99), "九十九")
        # Test fallback
        self.assertEqual(to_chinese_numeral(100), "100")

class TestAIProcessor(unittest.TestCase):
    def setUp(self):
        # Patch environment variables if needed, or just mock the methods
        self.processor = AIProcessor()
        # Mock the internal API calls to avoid real network requests
        self.processor.translate_content = MagicMock(return_value="Translated Content")
        self.processor.analyze_relevance = MagicMock()

    def test_process_article_keyword_filter(self):
        # Test irrelevant keyword
        title = "Banana Prices"
        abstract = "Fruit market update"
        content = "Bananas are yellow."
        
        result = self.processor.process_article(title, abstract, content)
        self.assertFalse(result['is_relevant'])
        self.assertEqual(result['reasoning'], "关键词不匹配 (No Keywords)")
        self.assertEqual(result['confidence_score'], 0.0)

    def test_process_article_keyword_pass_ai_fail(self):
        # Test relevant keyword but AI says no
        title = "Digital Currency Update"
        abstract = "CBDC is discussed."
        content = "Some content about cbdc."
        
        # Mock analyze_relevance to return irrelevant
        self.processor.analyze_relevance.return_value = {
            "is_relevant": False,
            "confidence_score": 0.1,
            "reasoning": "Not about central bank",
            "title_cn": "Title CN"
        }
        
        result = self.processor.process_article(title, abstract, content)
        self.assertFalse(result['is_relevant'])
        self.assertEqual(result['reasoning'], "Not about central bank")

    def test_process_article_keyword_pass_ai_pass(self):
        # Test relevant keyword and AI says yes
        title = "Digital Euro Launch"
        abstract = "ECB launches digital euro."
        content = "cbdc content."
        
        # Mock analyze_relevance to return relevant
        self.processor.analyze_relevance.return_value = {
            "is_relevant": True,
            "confidence_score": 0.9,
            "reasoning": "Core CBDC topic",
            "title_cn": "Title CN"
        }
        
        result = self.processor.process_article(title, abstract, content)
        self.assertTrue(result['is_relevant'])
        self.assertEqual(result['confidence_score'], 0.9)

    def test_process_article_low_confidence(self):
        # Test relevant keyword and AI says yes but low score
        title = "Digital Euro Launch"
        abstract = "ECB launches digital euro."
        content = "cbdc content."
        
        # Mock analyze_relevance to return relevant but low score
        self.processor.analyze_relevance.return_value = {
            "is_relevant": True,
            "confidence_score": 0.5, # < 0.6
            "reasoning": "Mentioned briefly",
            "title_cn": "Title CN"
        }
        
        result = self.processor.process_article(title, abstract, content)
        self.assertFalse(result['is_relevant'])
        self.assertIn("置信度过低", result['reasoning'])

if __name__ == '__main__':
    unittest.main()
