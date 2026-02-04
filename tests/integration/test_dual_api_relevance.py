import unittest
from unittest.mock import MagicMock, patch
import json
from src.services.relevance_service import RelevanceService

class TestDualAPIRelevance(unittest.TestCase):
    def setUp(self):
        self.service = RelevanceService()
        self.sample_text = {
            "title": "CBDC Pilot Launch",
            "abstract": "The central bank launched a pilot.",
            "content": "Details about the e-currency."
        }
        
    def test_keyword_filter(self):
        # Test filtering out non-relevant text
        result = self.service.assess_relevance("Crypto prices up", "Bitcoin is high", "Nothing about central banks")
        self.assertFalse(result['is_relevant'])
        self.assertEqual(result['reasoning'], "关键词不匹配 (No Keywords)")

    @patch('src.services.relevance_service.NvidiaClient')
    @patch('src.services.relevance_service.OpenRouterClient')
    def test_dual_success(self, mock_or, mock_nv):
        # Mock successful response from both
        response_json = json.dumps({
            "is_relevant": True,
            "confidence_score": 0.9,
            "title_cn": "Test Title",
            "summary": "Summary",
            "reasoning": "Reason"
        })
        
        # We need to mock the internal clients of the service
        self.service.nvidia.chat_completion = MagicMock(return_value=response_json)
        self.service.openrouter.chat_completion = MagicMock(return_value=response_json)
        
        result = self.service.assess_relevance(**self.sample_text)
        self.assertTrue(result['is_relevant'])
        self.assertEqual(result['confidence'], 0.9)

    def test_one_path_failure(self):
        # Nvidia succeeds, OpenRouter fails
        response_json = json.dumps({
            "is_relevant": True,
            "confidence_score": 0.9,
            "title_cn": "Test Title",
            "summary": "Summary",
            "reasoning": "Reason"
        })
        
        self.service.nvidia.chat_completion = MagicMock(return_value=response_json)
        self.service.openrouter.chat_completion = MagicMock(return_value=None)
        
        result = self.service.assess_relevance(**self.sample_text)
        self.assertTrue(result['is_relevant'])
        
    def test_both_failure(self):
        # Both fail
        self.service.nvidia.chat_completion = MagicMock(return_value=None)
        self.service.openrouter.chat_completion = MagicMock(return_value="Invalid JSON")
        
        result = self.service.assess_relevance(**self.sample_text)
        self.assertEqual(result['is_relevant'], "ERROR")

    def test_disagreement_true_wins(self):
        # Nvidia says True, OpenRouter says False
        res_true = json.dumps({"is_relevant": True, "confidence_score": 0.8})
        res_false = json.dumps({"is_relevant": False, "confidence_score": 0.2})
        
        self.service.nvidia.chat_completion = MagicMock(return_value=res_true)
        self.service.openrouter.chat_completion = MagicMock(return_value=res_false)
        
        result = self.service.assess_relevance(**self.sample_text)
        self.assertTrue(result['is_relevant'])
        self.assertEqual(result['confidence'], 0.8)

if __name__ == '__main__':
    unittest.main()
