
import unittest
from unittest.mock import MagicMock, patch
import sys
import os
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils import to_chinese_numeral
from src.services.relevance_service import RelevanceService

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

class TestRelevanceService(unittest.TestCase):
    def setUp(self):
        self.service = RelevanceService()
        # Mock clients to avoid real API calls
        self.service.zai = MagicMock()
        self.service.openrouter = MagicMock()

    def test_assess_relevance_keyword_filter(self):
        # Test irrelevant keyword
        title = "Banana Prices"
        abstract = "Fruit market update"
        content = "Bananas are yellow."
        
        result = self.service.assess_relevance(title, abstract, content)
        self.assertFalse(result['is_relevant'])
        self.assertEqual(result['reasoning'], "关键词不匹配 (No Keywords)")
        self.assertEqual(result['confidence'], 0.0)

    def test_assess_relevance_ai_true(self):
        # Test relevant keyword + AI returns True
        title = "Digital Euro Launch"
        abstract = "ECB launches digital euro."
        content = "cbdc content."
        
        # Mock Z.AI response
        self.service.zai.chat_completion.return_value = '{"is_relevant": true, "confidence_score": 0.9, "title_cn": "数字欧元发布", "summary": "...", "reasoning": "Explicit mention"}'
        # Mock OpenRouter response (can be anything, maybe failure)
        self.service.openrouter.chat_completion.return_value = None 
        
        result = self.service.assess_relevance(title, abstract, content)
        self.assertTrue(result['is_relevant'])
        self.assertEqual(result['confidence'], 0.9)
        self.assertEqual(result['details']['zai']['status'], 'success')
        self.assertEqual(result['details']['or']['status'], 'error')

    def test_assess_relevance_ai_false(self):
        # Test relevant keyword but AI says False
        title = "Crypto Market Crash"
        abstract = "Bitcoin prices fell."
        content = "cbdc mentioned but not focus."
        
        # Mock both returning False
        self.service.zai.chat_completion.return_value = '{"is_relevant": false, "confidence_score": 0.1, "reasoning": "Not CBDC"}'
        self.service.openrouter.chat_completion.return_value = '{"is_relevant": false, "confidence_score": 0.2}'
        
        result = self.service.assess_relevance(title, abstract, content)
        self.assertFalse(result['is_relevant'])
        self.assertEqual(result['details']['zai']['is_relevant'], False)
        self.assertEqual(result['details']['or']['is_relevant'], False)

    def test_assess_relevance_all_apis_fail(self):
        # Test connection error for both
        title = "Digital Euro"
        abstract = "CBDC"
        content = "CBDC"
        
        self.service.zai.chat_completion.return_value = None
        self.service.openrouter.chat_completion.return_value = None
        
        result = self.service.assess_relevance(title, abstract, content)
        self.assertEqual(result['is_relevant'], "ERROR")
        self.assertTrue(result['alert_needed'])

if __name__ == '__main__':
    unittest.main()
