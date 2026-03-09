"""
Prompt compression and optimization service.

Reduces token usage by:
- Removing redundant instructions
- Using abbreviations where appropriate
- Summarizing conversation history
- Tracking compression savings
"""
import logging
import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading

from app.services.token_estimator import estimate_tokens

logger = logging.getLogger(__name__)


@dataclass
class CompressionStats:
    """Statistics for prompt compression."""
    original_tokens: int = 0
    compressed_tokens: int = 0
    tokens_saved: int = 0
    compression_ratio: float = 0.0
    method: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_tokens": self.original_tokens,
            "compressed_tokens": self.compressed_tokens,
            "tokens_saved": self.tokens_saved,
            "compression_ratio": round(self.compression_ratio, 3),
            "method": self.method,
        }


@dataclass 
class OptimizationResult:
    """Result of prompt optimization."""
    text: str
    stats: CompressionStats
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "stats": self.stats.to_dict(),
        }


# Abbreviation mappings for common terms
ABBREVIATIONS = {
    "description": "desc",
    "information": "info",
    "position": "pos",
    "confidence": "conf",
    "environmental": "env",
    "approximately": "~",
    "for example": "e.g.",
    "such as": "e.g.",
    "in other words": "i.e.",
    "including": "incl.",
    "especially": "esp.",
    "approximately": "approx.",
    "requirements": "reqs",
}

# Redundant phrases that can be removed
REDUNDANT_PHRASES = [
    r"\bplease\s+(?=note|remember|ensure)",
    r"\bit\s+is\s+important\s+to\s+",
    r"\bmake\s+sure\s+to\s+",
    r"\bdon't\s+forget\s+to\s+",
    r"\balways\s+remember\s+to\s+",
    r"\bkeep\s+in\s+mind\s+that\s+",
    r"\bas\s+mentioned\s+(?:earlier|above|before),?\s*",
]


class PromptOptimizer:
    """
    Optimizes prompts to reduce token usage while preserving meaning.
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self._total_tokens_saved = 0
        self._total_compressions = 0
        self._savings_by_method: Dict[str, int] = {}
    
    def compress_system_prompt(
        self,
        prompt: str,
        level: str = "moderate"
    ) -> OptimizationResult:
        """
        Compress a system prompt by removing redundancy.
        
        Args:
            prompt: The system prompt to compress
            level: Compression level - "light", "moderate", or "aggressive"
            
        Returns:
            OptimizationResult with compressed prompt and stats
        """
        original_tokens = estimate_tokens(prompt)
        
        compressed = prompt
        
        if level in ("moderate", "aggressive"):
            # Remove redundant phrases
            for pattern in REDUNDANT_PHRASES:
                compressed = re.sub(pattern, "", compressed, flags=re.IGNORECASE)
            
            # Condense multiple spaces/newlines
            compressed = re.sub(r'\n{3,}', '\n\n', compressed)
            compressed = re.sub(r' {2,}', ' ', compressed)
        
        if level == "aggressive":
            # Apply abbreviations
            for full, abbrev in ABBREVIATIONS.items():
                compressed = re.sub(
                    rf'\b{full}\b',
                    abbrev,
                    compressed,
                    flags=re.IGNORECASE
                )
            
            # Remove example lists (keep first example only)
            compressed = re.sub(
                r'(\([^)]+\))\s*,\s*\([^)]+\)(?:\s*,\s*\([^)]+\))*',
                r'\1',
                compressed
            )
        
        compressed = compressed.strip()
        compressed_tokens = estimate_tokens(compressed)
        tokens_saved = original_tokens - compressed_tokens
        
        stats = CompressionStats(
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            tokens_saved=tokens_saved,
            compression_ratio=compressed_tokens / original_tokens if original_tokens > 0 else 1.0,
            method=f"system_prompt_{level}",
        )
        
        self._record_savings(stats)
        
        return OptimizationResult(text=compressed, stats=stats)
    
    def summarize_history(
        self,
        history: List[Dict[str, str]],
        max_messages: int = 6,
        max_tokens_per_message: int = 100
    ) -> Tuple[List[Dict[str, str]], CompressionStats]:
        """
        Summarize conversation history to reduce token count.
        
        Args:
            history: List of message dicts with 'role' and 'content'
            max_messages: Maximum number of recent messages to keep in full
            max_tokens_per_message: Max tokens per older message summary
            
        Returns:
            Tuple of (optimized history, CompressionStats)
        """
        if not history:
            return [], CompressionStats(method="history_summary")
        
        original_tokens = sum(
            estimate_tokens(msg.get("content", ""))
            for msg in history
        )
        
        optimized = []
        
        if len(history) <= max_messages:
            # Keep all messages as-is
            return history, CompressionStats(
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
                tokens_saved=0,
                compression_ratio=1.0,
                method="history_summary_passthrough",
            )
        
        # Summarize older messages
        older = history[:-max_messages]
        recent = history[-max_messages:]
        
        # Create summary of older messages
        if older:
            summary = self._create_history_summary(older, max_tokens_per_message)
            optimized.append({
                "role": "system",
                "content": f"[Previous conversation summary: {summary}]"
            })
        
        # Keep recent messages in full
        optimized.extend(recent)
        
        compressed_tokens = sum(
            estimate_tokens(msg.get("content", ""))
            for msg in optimized
        )
        tokens_saved = original_tokens - compressed_tokens
        
        stats = CompressionStats(
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            tokens_saved=tokens_saved,
            compression_ratio=compressed_tokens / original_tokens if original_tokens > 0 else 1.0,
            method="history_summary",
        )
        
        self._record_savings(stats)
        
        return optimized, stats
    
    def _create_history_summary(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int
    ) -> str:
        """Create a concise summary of older messages."""
        # Extract key facts from older messages
        user_points = []
        assistant_points = []
        
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            # Extract first sentence or key phrase
            first_sentence = content.split('.')[0][:150]
            
            if role == "user":
                user_points.append(first_sentence)
            elif role in ("assistant", "model"):
                assistant_points.append(first_sentence)
        
        # Build compact summary
        parts = []
        if user_points:
            parts.append(f"Witness mentioned: {'; '.join(user_points[:3])}")
        if assistant_points:
            parts.append(f"Agent asked about: {'; '.join(assistant_points[:2])}")
        
        summary = ". ".join(parts)
        
        # Truncate if too long
        while estimate_tokens(summary) > max_tokens and len(summary) > 50:
            summary = summary[:int(len(summary) * 0.8)]
        
        return summary.strip()
    
    def optimize_prompt_for_model(
        self,
        prompt: str,
        model_name: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Optimize prompts based on model capabilities.
        
        Args:
            prompt: The user prompt
            model_name: Target model name
            system_prompt: Optional system prompt
            history: Optional conversation history
            
        Returns:
            Dict with optimized components and total savings
        """
        result = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "history": history or [],
            "total_tokens_saved": 0,
            "optimizations": [],
        }
        
        # Determine compression level based on model
        is_lightweight = any(x in model_name.lower() for x in ["gemma", "lite", "4b", "12b"])
        level = "aggressive" if is_lightweight else "moderate"
        
        # Optimize system prompt
        if system_prompt:
            opt_result = self.compress_system_prompt(system_prompt, level=level)
            result["system_prompt"] = opt_result.text
            result["total_tokens_saved"] += opt_result.stats.tokens_saved
            result["optimizations"].append({
                "component": "system_prompt",
                "stats": opt_result.stats.to_dict(),
            })
        
        # Optimize history
        if history:
            max_msgs = 4 if is_lightweight else 6
            opt_history, hist_stats = self.summarize_history(
                history, 
                max_messages=max_msgs
            )
            result["history"] = opt_history
            result["total_tokens_saved"] += hist_stats.tokens_saved
            result["optimizations"].append({
                "component": "history",
                "stats": hist_stats.to_dict(),
            })
        
        return result
    
    def _record_savings(self, stats: CompressionStats) -> None:
        """Record compression savings for tracking."""
        with self._lock:
            self._total_tokens_saved += stats.tokens_saved
            self._total_compressions += 1
            
            method = stats.method
            self._savings_by_method[method] = (
                self._savings_by_method.get(method, 0) + stats.tokens_saved
            )
    
    def get_savings_stats(self) -> Dict[str, Any]:
        """Get overall compression statistics."""
        with self._lock:
            return {
                "total_tokens_saved": self._total_tokens_saved,
                "total_compressions": self._total_compressions,
                "average_savings": (
                    self._total_tokens_saved / self._total_compressions 
                    if self._total_compressions > 0 else 0
                ),
                "savings_by_method": dict(self._savings_by_method),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    
    def reset_stats(self) -> None:
        """Reset compression statistics."""
        with self._lock:
            self._total_tokens_saved = 0
            self._total_compressions = 0
            self._savings_by_method.clear()


# Global singleton
prompt_optimizer = PromptOptimizer()


# Convenience functions
def compress_prompt(prompt: str, level: str = "moderate") -> OptimizationResult:
    """Compress a prompt with the specified level."""
    return prompt_optimizer.compress_system_prompt(prompt, level=level)


def optimize_for_model(
    prompt: str,
    model_name: str,
    system_prompt: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Optimize all prompts for a specific model."""
    return prompt_optimizer.optimize_prompt_for_model(
        prompt=prompt,
        model_name=model_name,
        system_prompt=system_prompt,
        history=history,
    )


def get_compression_stats() -> Dict[str, Any]:
    """Get current compression statistics."""
    return prompt_optimizer.get_savings_stats()
