"""
Token estimation service for pre-checking API requests against TPM limits.

Provides token counting before sending requests to prevent quota exhaustion.
Uses character-based estimation (4 chars = ~1 token for English text).
"""
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

from app.services.model_selector import MODEL_QUOTAS

logger = logging.getLogger(__name__)


@dataclass
class TokenEstimate:
    """Token estimation result with breakdown."""
    input_tokens: int
    output_tokens_estimate: int  # Estimated based on expected response
    total_tokens: int
    breakdown: Dict[str, int]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens_estimate": self.output_tokens_estimate,
            "total_tokens": self.total_tokens,
            "breakdown": self.breakdown,
        }


@dataclass
class QuotaCheckResult:
    """Result of pre-checking against quota limits."""
    allowed: bool
    estimated_tokens: int
    remaining_tokens: Optional[int]
    limit: Optional[int]
    warning: Optional[str] = None
    rejection_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "allowed": self.allowed,
            "estimated_tokens": self.estimated_tokens,
            "remaining_tokens": self.remaining_tokens,
            "limit": self.limit,
        }
        if self.warning:
            result["warning"] = self.warning
        if self.rejection_reason:
            result["rejection_reason"] = self.rejection_reason
        return result


class TokenEstimator:
    """
    Estimates token count for text before sending to the API.
    
    Uses character-based estimation since tiktoken doesn't support Gemini.
    Rule of thumb: ~4 characters = 1 token for English text.
    """
    
    # Characters per token by content type
    CHARS_PER_TOKEN = {
        "english": 4,
        "code": 3,  # Code tends to have more tokens per character
        "json": 3,
        "default": 4,
    }
    
    # Typical output/input ratios by task type
    OUTPUT_RATIOS = {
        "chat": 1.5,        # Response ~1.5x input length
        "scene": 2.0,       # Scene descriptions can be verbose
        "analysis": 2.0,    # Analysis tends to be detailed
        "classification": 0.1,  # Short classification responses
        "intent": 0.1,      # Short intent responses
        "preprocessing": 0.5,
        "embedding": 0.0,   # No output tokens for embeddings
        "tts": 0.0,         # TTS doesn't return text tokens
        "default": 1.0,
    }
    
    # Warning threshold (warn if request uses >80% of remaining quota)
    WARNING_THRESHOLD = 0.8
    
    def estimate_tokens(
        self,
        text: str,
        content_type: str = "english"
    ) -> int:
        """
        Estimate token count for a piece of text.
        
        Args:
            text: The text to estimate
            content_type: Type of content ("english", "code", "json")
            
        Returns:
            Estimated token count
        """
        if not text:
            return 0
        
        chars_per_token = self.CHARS_PER_TOKEN.get(
            content_type, 
            self.CHARS_PER_TOKEN["default"]
        )
        
        # Basic character-based estimation
        char_estimate = len(text) / chars_per_token
        
        # Adjust for whitespace (fewer tokens than chars suggest)
        whitespace_count = text.count(' ') + text.count('\n') + text.count('\t')
        whitespace_adjustment = whitespace_count * 0.3
        
        # Adjust for special characters (more tokens)
        special_chars = sum(1 for c in text if c in "{}[]()<>.,;:!?\"'`@#$%^&*")
        special_adjustment = special_chars * 0.2
        
        estimated = int(char_estimate - whitespace_adjustment + special_adjustment)
        return max(1, estimated)
    
    def estimate_request(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        task_type: str = "chat",
        content_type: str = "english",
    ) -> TokenEstimate:
        """
        Estimate total tokens for a complete request.
        
        Args:
            prompt: The user's prompt/message
            system_prompt: System instructions (if any)
            history: Conversation history
            task_type: Type of task for output estimation
            content_type: Type of content being processed
            
        Returns:
            TokenEstimate with breakdown
        """
        breakdown = {}
        total_input = 0
        
        # System prompt tokens
        if system_prompt:
            system_tokens = self.estimate_tokens(system_prompt, content_type)
            breakdown["system_prompt"] = system_tokens
            total_input += system_tokens
        
        # History tokens
        if history:
            history_tokens = sum(
                self.estimate_tokens(msg.get("content", ""), content_type)
                for msg in history
            )
            breakdown["history"] = history_tokens
            total_input += history_tokens
        
        # Current prompt tokens
        prompt_tokens = self.estimate_tokens(prompt, content_type)
        breakdown["prompt"] = prompt_tokens
        total_input += prompt_tokens
        
        # Estimate output tokens
        output_ratio = self.OUTPUT_RATIOS.get(
            task_type,
            self.OUTPUT_RATIOS["default"]
        )
        output_estimate = int(prompt_tokens * output_ratio)
        
        # Cap output estimate at reasonable max
        output_estimate = min(output_estimate, 4096)
        breakdown["output_estimate"] = output_estimate
        
        return TokenEstimate(
            input_tokens=total_input,
            output_tokens_estimate=output_estimate,
            total_tokens=total_input + output_estimate,
            breakdown=breakdown,
        )
    
    def check_quota(
        self,
        model_name: str,
        estimated_tokens: int,
        current_usage: int = 0,
        enforce: bool = True,
    ) -> QuotaCheckResult:
        """
        Check if a request would exceed quota limits.
        
        Args:
            model_name: The model to check against
            estimated_tokens: Estimated token count for the request
            current_usage: Current token usage for the day
            enforce: If True, reject requests that would exceed limits
            
        Returns:
            QuotaCheckResult indicating if request is allowed
        """
        # Get model limits
        model_quota = MODEL_QUOTAS.get(model_name, {})
        tpm_limit = model_quota.get("tpm", 0)
        
        # If no TPM limit (0 = unlimited), allow
        if not tpm_limit:
            return QuotaCheckResult(
                allowed=True,
                estimated_tokens=estimated_tokens,
                remaining_tokens=None,
                limit=None,
            )
        
        remaining = tpm_limit - current_usage
        
        # Check if request would exceed limit
        if current_usage + estimated_tokens > tpm_limit:
            if enforce:
                return QuotaCheckResult(
                    allowed=False,
                    estimated_tokens=estimated_tokens,
                    remaining_tokens=max(0, remaining),
                    limit=tpm_limit,
                    rejection_reason=(
                        f"Request ({estimated_tokens:,} tokens) would exceed "
                        f"daily limit ({tpm_limit:,} tokens). "
                        f"Remaining: {remaining:,} tokens."
                    ),
                )
            else:
                # Warn but allow
                return QuotaCheckResult(
                    allowed=True,
                    estimated_tokens=estimated_tokens,
                    remaining_tokens=max(0, remaining),
                    limit=tpm_limit,
                    warning=(
                        f"Request ({estimated_tokens:,} tokens) will exceed "
                        f"daily limit ({tpm_limit:,} tokens)."
                    ),
                )
        
        # Check warning threshold
        usage_ratio = (current_usage + estimated_tokens) / tpm_limit
        if usage_ratio > self.WARNING_THRESHOLD:
            return QuotaCheckResult(
                allowed=True,
                estimated_tokens=estimated_tokens,
                remaining_tokens=remaining - estimated_tokens,
                limit=tpm_limit,
                warning=(
                    f"High quota usage: {usage_ratio:.0%} after this request. "
                    f"Remaining: {remaining - estimated_tokens:,} tokens."
                ),
            )
        
        return QuotaCheckResult(
            allowed=True,
            estimated_tokens=estimated_tokens,
            remaining_tokens=remaining - estimated_tokens,
            limit=tpm_limit,
        )
    
    def estimate_and_check(
        self,
        model_name: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        task_type: str = "chat",
        current_usage: int = 0,
        enforce: bool = True,
    ) -> Tuple[TokenEstimate, QuotaCheckResult]:
        """
        Estimate tokens and check quota in one call.
        
        Returns:
            Tuple of (TokenEstimate, QuotaCheckResult)
        """
        estimate = self.estimate_request(
            prompt=prompt,
            system_prompt=system_prompt,
            history=history,
            task_type=task_type,
        )
        
        check = self.check_quota(
            model_name=model_name,
            estimated_tokens=estimate.total_tokens,
            current_usage=current_usage,
            enforce=enforce,
        )
        
        return estimate, check


# Global singleton
token_estimator = TokenEstimator()


# Convenience functions for backward compatibility
def estimate_tokens(text: str) -> int:
    """Estimate token count for text (4 chars = ~1 token)."""
    return token_estimator.estimate_tokens(text)


def estimate_request_tokens(
    prompt: str,
    system_prompt: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
    task_type: str = "chat",
) -> TokenEstimate:
    """Estimate tokens for a complete request."""
    return token_estimator.estimate_request(
        prompt=prompt,
        system_prompt=system_prompt,
        history=history,
        task_type=task_type,
    )


def check_quota_precheck(
    model_name: str,
    estimated_tokens: int,
    current_usage: int = 0,
    enforce: bool = True,
) -> QuotaCheckResult:
    """Check if a request would exceed quota limits."""
    return token_estimator.check_quota(
        model_name=model_name,
        estimated_tokens=estimated_tokens,
        current_usage=current_usage,
        enforce=enforce,
    )
