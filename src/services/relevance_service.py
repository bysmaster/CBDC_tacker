import concurrent.futures
import json
import re
from typing import Dict, Optional, Tuple, Any
from src.clients.zai_client import ZaiClient
from src.clients.openrouter_client import OpenRouterClient

class RelevanceService:
    def __init__(self):
        self.zai = ZaiClient()
        self.openrouter = OpenRouterClient()
        self.KEYWORDS_CBDC = [
            "cbdc", "central bank digital currency", "digital currency", "digital euro", 
            "digital dollar", "e-cny", "digital yuan", "digital pound", "digital rupee",
            "digital ruble", "digital real", "digital won", "tokenized deposit", 
            "rln", "regulated liability network", "wholesale cbdc", "retail cbdc",
            "stablecoin", "crypto asset", "ledger technology", "dlt", "blockchain"
        ]

    def _parse_json(self, text: str) -> Optional[Dict]:
        if not text:
            return None
        try:
            # Clean markdown code blocks if present
            text = text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
                
            # Try to find JSON block if mixed with text
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                text = match.group(0)
                
            data = json.loads(text)
            if isinstance(data, dict):
                return data
            return None # Reject lists or primitives
        except:
            return None

    def _call_model(self, client, prompt, name) -> Tuple[str, Optional[Dict], bool]:
        # Returns (ClientName, ResultDict, IsConnectionSuccess)
        raw = client.chat_completion(prompt)
        
        # If raw is None, it means connection/API failed (client returns None on error)
        if raw is None:
            return name, None, False
            
        parsed = self._parse_json(raw)
        return name, parsed, True

    def assess_relevance(self, title: str, abstract: str, content: str) -> Dict[str, Any]:
        """
        Dual-path analysis.
        Returns dict with keys: 
            is_relevant (bool or "ERROR"), 
            title_cn, summary, reasoning, confidence,
            details: { zai: {...}, or: {...} }
        """
        # 1. Keyword Filter
        full_text = (str(title) + " " + str(abstract) + " " + str(content)).lower()
        if not any(k in full_text for k in self.KEYWORDS_CBDC):
             return {
                "is_relevant": False,
                "reasoning": "关键词不匹配 (No Keywords)",
                "confidence": 0.0,
                "title_cn": title,
                "summary": "",
                "details": {
                    "zai": {"is_relevant": False, "reason": "Skipped (Keyword)", "status": "skipped"},
                    "or": {"is_relevant": False, "reason": "Skipped (Keyword)", "status": "skipped"}
                }
            }

        # 2. Prepare Prompt
        prompt = f"""
        你是一位服务于人民银行总行的资深金融情报分析师。请对以下金融资讯进行深度研判，判断是否涉及央行数字货币(CBDC)领域。

        【资讯内容】
        Title: {title}
        Abstract: {abstract}
        Content Sample: {str(content)[:1000]}
        
        【研判标准】
        1. 核心相关性：是否明确提及CBDC (如数字人民币/e-CNY、数字欧元、数字美元等)、数字货币政策框架、法律监管或技术基础设施(DLT/RLN/Tokenized Deposits)。
        2. 排除标准：仅提及加密货币(如比特币)价格波动、一般性货币供应数据、传统银行人事变动或非CBDC相关的反洗钱/数字信贷业务。

        【输出要求】
        请返回且仅返回一个标准 JSON 对象（不要包含Markdown代码块）：
        {{
            "is_relevant": true/false,
            "confidence_score": 0.95,
            "title_cn": "中文标题（请按正式公文风格翻译，准确简练）",
            "summary": "中文摘要（请按《金融时报》或政府内参简报风格撰写。使用第三人称，客观陈述事实，避免使用'本文'、'我'等主观词汇。重点提炼政策动向、核心观点或关键数据。字数控制在200-300字。）",
            "reasoning": "研判依据（简明扼要，<30字）"
        }}
        """

        # 3. Dual Call
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_zai = executor.submit(self._call_model, self.zai, prompt, "Z.AI")
            future_or = executor.submit(self._call_model, self.openrouter, prompt, "OpenRouter")
            
            results = {}
            for future in concurrent.futures.as_completed([future_zai, future_or]):
                name, res, success = future.result()
                results[name] = {"data": res, "success": success}

        zai_res = results.get("Z.AI", {}).get("data")
        zai_success = results.get("Z.AI", {}).get("success", False)
        
        or_res = results.get("OpenRouter", {}).get("data")
        or_success = results.get("OpenRouter", {}).get("success", False)
        
        # 4. Detailed Status Construction
        details = {}
        
        # Z.AI Status
        if not zai_success:
            details["zai"] = {"is_relevant": None, "reason": "Connection Failed", "status": "error"}
        elif not zai_res:
            details["zai"] = {"is_relevant": None, "reason": "Parse Error", "status": "parse_error"}
        else:
            details["zai"] = {
                "is_relevant": zai_res.get("is_relevant"),
                "reason": zai_res.get("reasoning", ""),
                "status": "success"
            }
            
        # OpenRouter Status
        if not or_success:
            details["or"] = {"is_relevant": None, "reason": "Connection Failed", "status": "error"}
        elif not or_res:
            details["or"] = {"is_relevant": None, "reason": "Parse Error", "status": "parse_error"}
        else:
            details["or"] = {
                "is_relevant": or_res.get("is_relevant"),
                "reason": or_res.get("reasoning", ""),
                "status": "success"
            }

        # 5. Merge Logic & Critical Failure Check
        
        # Critical Failure: Both connections failed
        if not zai_success and not or_success:
            return {
                "is_relevant": "ERROR", 
                "reasoning": "双路API调用均失败 (Connection Error)",
                "confidence": 0.0,
                "title_cn": title,
                "summary": "",
                "details": details,
                "alert_needed": True  # Flag for processor to send alert
            }

        # Logic: If ANY says True -> True (OR logic)
        is_rel_zai = zai_res.get("is_relevant", False) if zai_res else False
        is_rel_or = or_res.get("is_relevant", False) if or_res else False
        
        final_is_relevant = is_rel_zai or is_rel_or
        
        # Pick best content (Prioritize Z.AI if successful as it's likely better at Chinese)
        if zai_res and is_rel_zai:
            best_res = zai_res
        elif or_res and is_rel_or:
            best_res = or_res
        elif zai_res:
            best_res = zai_res
        elif or_res:
            best_res = or_res
        else:
            # Should be covered by error check above, but safe fallback
            best_res = {}
            
        return {
            "is_relevant": final_is_relevant,
            "confidence": best_res.get("confidence_score", 0.0),
            "title_cn": best_res.get("title_cn", title),
            "summary": best_res.get("summary", ""),
            "reasoning": best_res.get("reasoning", ""),
            "details": details,
            "alert_needed": False
        }
