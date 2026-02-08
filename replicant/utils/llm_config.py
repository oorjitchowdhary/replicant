"""LLM configuration utilities."""
from __future__ import annotations
import os
from pathlib import Path


def check_gemini_setup() -> tuple[bool, str]:
    """Check if Gemini API is properly configured.
    
    Returns:
        (is_configured, message)
    """
    api_key = os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        return False, (
            "Gemini API key not found. Set GEMINI_API_KEY environment variable for enhanced paper analysis.\n"
            "Get your API key from: https://aistudio.google.com/app/apikey\n"
            "Export it: export GEMINI_API_KEY=your_api_key_here"
        )
    
    try:
        import google.genai as genai
    except ImportError:
        return False, "google-genai package not installed. Run: pip install google-genai"
    
    try:
        client = genai.Client(api_key=api_key)
        # Test the API with a simple call
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents="Hello"
        )
        return True, "Gemini API configured successfully"
    except Exception as e:
        return False, f"Gemini API test failed: {e}"


def get_config_instructions() -> str:
    """Get instructions for configuring Gemini API."""
    return """
🤖 Enhanced Paper Analysis with Gemini AI

Replicant can now use Google's Gemini AI for smarter paper analysis instead of 
regex patterns. This provides much better accuracy for:

• GitHub repository detection
• Framework and library identification  
• Dataset recognition (beyond hardcoded lists)
• Hardware requirement extraction
• Download URL classification

Setup:
1. Get a Gemini API key: https://aistudio.google.com/app/apikey
2. Set environment variable: export GEMINI_API_KEY=your_key_here
3. Run replicant normally - it will automatically use AI analysis

If no API key is provided, replicant falls back to the original regex-based approach.
"""