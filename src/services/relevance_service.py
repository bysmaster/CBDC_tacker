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
        请对以下金融资讯内容进行全面分析，判断是否与各国央行数字货币(CBDC)相关。
        
        Title: {title}
        Abstract: {abstract}
        Content Sample: {str(content)[:1000]}
        
        评估标准：
        1. 是否明确提及CBDC (如 e-CNY, Digital Euro, Digital Pound, Digital Rupee 等)。
        2. 是否讨论数字货币政策、监管框架或法律修订。
        3. 是否涉及央行数字货币的技术基础设施 (如 DLT, RLN, Tokenized Deposits) 或试点项目。
        4. 排除标准：仅提及一般加密货币价格波动、常规货币供应量数据、传统银行人事变动、或非CBDC相关的数字贷款/反洗钱处罚。

        输出格式：
        请返回且仅返回一个有效的 JSON 对象：
        {{
            "is_relevant": true/false,
            "confidence_score": 0.85,
            "title_cn": "中文标题",
            "summary": "中文摘要 (<300字)",
            "reasoning": "中文判断依据 (<30字)"
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
